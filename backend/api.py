"""Nashik street-vendor zoning decision-support API.

Run locally with:

    python -m uvicorn api:app --app-dir backend --reload --port 8000

The application combines:

- operational vendor registration and authentication,
- live municipal zone status,
- explainable GIS + MCDA recommendations,
- recommendation robustness evaluation,
- advisory Goal Programming allocation planning,
- allocation request / approval workflows,
- expert-review and experimental-model readiness reporting.

Important
---------
MCDA scores are decision-support values, not probabilities of business success.

Goal Programming output is advisory. It does not reserve a zone, create a
permit, or modify occupancy.

Experimental supervised models are not used by the production recommendation
path unless a future explicitly reviewed integration changes that policy.
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request as FastAPIRequest,
    Response,
    status as http_status,
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
)


# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(
    __file__
).resolve().parent

sys.path.insert(
    0,
    str(
        BACKEND_DIR
    ),
)


from mcda_engine import (  # noqa: E402
    ROOT,
    DATA,
    CATEGORIES,
    recommend,
)

from decision_policy import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    FACTOR_ORDER,
    RESEARCH_BASELINE_WEIGHTS,
    derive_mcda_weights,
    load_base_weight_policy,
)

from recommendation_evaluation import (  # noqa: E402
    SensitivityConfig,
    evaluate_weight_sensitivity,
)

from allocation_optimizer import (  # noqa: E402
    AllocationOptimizationError,
)

from allocation_planning_service import (  # noqa: E402
    AllocationPlanningValidationError,
    plan_vendor_allocations,
)

from database import (  # noqa: E402
    DATABASE_PATH,
    OperationalConflictError,
    OperationalNotFoundError,
    OperationalValidationError,
    approve_allocation_request,
    cancel_allocation_request,
    create_allocation_request,
    get_allocation,
    get_admin_overview,
    get_allocation_request,
    get_active_allocation_for_vendor,
    get_zone_live_status,
    get_live_zone_status_map,
    get_vendor_dashboard_activity,
    list_allocations,
    list_allocation_requests,
    reject_allocation_request,
    update_zone_live_status,
)

from bootstrap import (  # noqa: E402
    initialize_application,
)

from vendor_service import (  # noqa: E402
    get_vendor_profile,
    register_vendor,
    update_vendor_profile,
)

from auth_service import (  # noqa: E402
    AuthError,
    SESSION_COOKIE_NAME,
    bind_onboarding_session,
    cookie_secure,
    create_admin_session,
    create_otp_challenge,
    get_session,
    revoke_session,
    verify_otp_challenge,
)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def validate_configuration_and_schema() -> None:
    """Validate configuration and safely initialize operational storage."""

    initialize_application(
        DATABASE_PATH
    )


@asynccontextmanager
async def lifespan(
    _: FastAPI,
):
    validate_configuration_and_schema()

    yield


app = FastAPI(
    title=(
        "Nashik Vendor Zoning "
        "Decision-Support API"
    ),
    version="0.2.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PATCH",
    ],
    allow_headers=[
        "Content-Type",
    ],
)


# Explicitly patched by legacy tests only.
# Production must never enable this.
AUTH_TEST_BYPASS = False


# ---------------------------------------------------------------------------
# Generic serialization
# ---------------------------------------------------------------------------


def clean(
    value: Any,
):
    """Convert pandas/numpy values into JSON-safe Python values."""

    if isinstance(
        value,
        dict,
    ):

        return {
            key:
                clean(
                    item
                )

            for (
                key,
                item,
            ) in value.items()
        }


    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):

        return [
            clean(
                item
            )
            for item
            in value
        ]


    if isinstance(
        value,
        np.integer,
    ):

        return int(
            value
        )


    if isinstance(
        value,
        np.floating,
    ):

        if not np.isfinite(
            value
        ):
            return None

        return float(
            value
        )


    if isinstance(
        value,
        np.bool_,
    ):

        return bool(
            value
        )


    if (
        value is None
        or value is pd.NA
    ):

        return None


    if (
        isinstance(
            value,
            float,
        )
        and not np.isfinite(
            value
        )
    ):

        return None


    try:

        if pd.isna(
            value
        ):
            return None

    except (
        TypeError,
        ValueError,
    ):
        pass


    return value


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class Request(
    BaseModel
):
    """Single-vendor recommendation request."""

    business: str = ""

    division: str = ""

    vendor_id: str = ""

    exclude_zone: str = ""

    top_n: int = Field(
        default=3,
        ge=1,
        le=20,
    )

    require_verified: bool = False


class SensitivityRequest(
    BaseModel
):
    """MCDA robustness evaluation request."""

    business: str = ""

    division: str = ""

    vendor_id: str = ""

    exclude_zone: str = ""

    top_n: int = Field(
        default=3,
        ge=1,
        le=20,
    )

    require_verified: bool = False

    monte_carlo_samples: int = Field(
        default=200,
        ge=0,
        le=1000,
    )

    monte_carlo_delta: float = Field(
        default=0.20,
        ge=0.0,
        lt=1.0,
    )

    random_seed: int = 42

    include_scenarios: bool = False


class AllocationPlanningBody(
    BaseModel
):
    """Read-only batch allocation-planning request."""

    vendor_ids: list[str] = Field(
        min_length=1,
        max_length=500,
    )

    require_verified: bool = True

    candidate_pool_size: (
        int
        | None
    ) = Field(
        default=None,
        ge=1,
        le=500,
    )

    reject_pending_requests: bool = True

    max_vendors: int = Field(
        default=500,
        ge=1,
        le=500,
    )

    time_limit_seconds: (
        float
        | None
    ) = Field(
        default=30.0,
        gt=0,
        le=120,
    )


class AllocationRequestCreate(
    BaseModel
):

    vendor_id: str

    zone_id: str

    request_type: Literal[
        "NEW_ALLOCATION",
        "RELOCATION",
    ]

    business_category: (
        str
        | None
    ) = None

    preferred_division: (
        str
        | None
    ) = None

    notes: (
        str
        | None
    ) = None


class AllocationRequestResponse(
    BaseModel
):

    request_id: str

    vendor_id: str

    zone_id: str

    request_type: Literal[
        "NEW_ALLOCATION",
        "RELOCATION",
    ]

    status: Literal[
        "PENDING",
        "APPROVED",
        "REJECTED",
        "CANCELLED",
    ]

    business_category: (
        str
        | None
    ) = None

    preferred_division: (
        str
        | None
    ) = None

    created_at: str

    updated_at: str

    reviewed_at: (
        str
        | None
    ) = None

    reviewed_by: (
        str
        | None
    ) = None

    rejection_reason: (
        str
        | None
    ) = None

    vendor_name: (
        str
        | None
    ) = None

    business_name: (
        str
        | None
    ) = None

    application_vendor_id: (
        str
        | None
    ) = None

    vendor_type: (
        Literal[
            "NEW",
            "EXISTING_IMPORTED",
        ]
        | None
    ) = None


class AllocationRequestListResponse(
    BaseModel
):

    requests: list[
        AllocationRequestResponse
    ]

    count: int

    status_filter: (
        Literal[
            "PENDING",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
        ]
        | None
    ) = None


class ApprovalBody(
    BaseModel
):

    notes: (
        str
        | None
    ) = None

    # Backward compatibility for tests.
    # Session identity remains authoritative.
    approved_by: (
        str
        | None
    ) = None


class RejectionBody(
    BaseModel
):

    rejection_reason: str

    notes: (
        str
        | None
    ) = None

    # Backward compatibility for tests.
    reviewed_by: (
        str
        | None
    ) = None


class AllocationResponse(
    BaseModel
):

    allocation_id: str

    vendor_id: str

    zone_id: str

    request_id: (
        str
        | None
    ) = None

    status: Literal[
        "ACTIVE",
        "RELEASED",
    ]

    allocated_at: str

    released_at: (
        str
        | None
    ) = None

    approved_by: (
        str
        | None
    ) = None

    created_at: str

    updated_at: str

    application_vendor_id: (
        str
        | None
    ) = None

    vendor_name: (
        str
        | None
    ) = None

    vendor_type: (
        Literal[
            "NEW",
            "EXISTING_IMPORTED",
        ]
        | None
    ) = None


class AllocationListResponse(
    BaseModel
):

    allocations: list[
        AllocationResponse
    ]

    count: int

    status_filter: (
        Literal[
            "ACTIVE",
            "RELEASED",
        ]
        | None
    ) = None


class ApprovalResponse(
    BaseModel
):

    request: (
        AllocationRequestResponse
    )

    allocation: (
        AllocationResponse
    )

    released_allocation: (
        AllocationResponse
        | None
    ) = None


class ZoneLiveStatusResponse(
    BaseModel
):

    zone_id: str

    official_capacity: (
        int
        | None
    ) = None

    current_vendor_count: int

    available_capacity: (
        int
        | None
    ) = None

    status: Literal[
        "OPEN",
        "FULL",
        "CLOSED",
        "SUSPENDED",
        "RESTRICTED",
        "NO_VENDING",
    ]

    verified_at: (
        str
        | None
    ) = None

    verified_by: (
        str
        | None
    ) = None

    updated_at: str


class VendorRegistrationBody(
    BaseModel
):

    full_name: (
        str
        | None
    ) = None

    business_name: (
        str
        | None
    ) = None

    business_category: str

    preferred_division: (
        str
        | None
    ) = None

    preferred_locality: (
        str
        | None
    ) = None

    priority_profile: str = (
        "BALANCED"
    )

    parking_preference: (
        StrictBool
    ) = False

    transport_preference: (
        StrictBool
    ) = False

    market_preference: (
        StrictBool
    ) = False

    preferred_language: str = "en"


class VendorProfileUpdateBody(
    BaseModel
):

    full_name: (
        str
        | None
    ) = None

    business_name: (
        str
        | None
    ) = None

    business_category: (
        str
        | None
    ) = None

    preferred_division: (
        str
        | None
    ) = None

    preferred_locality: (
        str
        | None
    ) = None

    priority_profile: (
        str
        | None
    ) = None

    parking_preference: (
        StrictBool
        | None
    ) = None

    transport_preference: (
        StrictBool
        | None
    ) = None

    market_preference: (
        StrictBool
        | None
    ) = None

    preferred_language: (
        str
        | None
    ) = None


class VendorProfileResponse(
    BaseModel
):

    vendor_id: str

    application_vendor_id: (
        str
        | None
    ) = None

    vendor_type: Literal[
        "NEW",
        "EXISTING_IMPORTED",
    ]

    full_name: (
        str
        | None
    ) = None

    business_name: (
        str
        | None
    ) = None

    business_category: str

    preferred_division: (
        str
        | None
    ) = None

    preferred_locality: (
        str
        | None
    ) = None

    priority_profile: Literal[
        "BALANCED",
        "COMMERCIAL",
        "ACCESSIBILITY",
        "FACILITIES",
    ]

    parking_preference: bool

    transport_preference: bool

    market_preference: bool

    preferred_language: Literal[
        "en",
        "mr",
        "hi",
    ]

    status: Literal[
        "ACTIVE",
        "INACTIVE",
    ]

    created_at: (
        str
        | None
    ) = None

    updated_at: (
        str
        | None
    ) = None


class ActiveVendorAllocationResponse(
    BaseModel
):

    allocation: (
        AllocationResponse
        | None
    ) = None


class AdminZoneStatusBody(
    BaseModel
):

    status: Literal[
        "OPEN",
        "CLOSED",
        "SUSPENDED",
    ]

    # Backward compatibility for tests.
    verified_by: (
        str
        | None
    ) = None


class VendorOtpRequestBody(
    BaseModel
):

    mobile: str


class VendorOtpVerifyBody(
    BaseModel
):

    challenge_id: str

    otp: str


class AdminLoginBody(
    BaseModel
):

    username: str

    password: str


# ---------------------------------------------------------------------------
# Shared response fields
# ---------------------------------------------------------------------------


ALLOCATION_REQUEST_RESPONSE_FIELDS = [
    "request_id",
    "vendor_id",
    "zone_id",
    "request_type",
    "status",
    "business_category",
    "preferred_division",
    "created_at",
    "updated_at",
    "reviewed_at",
    "reviewed_by",
    "rejection_reason",
]


ALLOCATION_RESPONSE_FIELDS = [
    "allocation_id",
    "vendor_id",
    "zone_id",
    "request_id",
    "status",
    "allocated_at",
    "released_at",
    "approved_by",
    "created_at",
    "updated_at",
]


ZONE_LIVE_STATUS_RESPONSE_FIELDS = [
    "zone_id",
    "official_capacity",
    "current_vendor_count",
    "available_capacity",
    "status",
    "verified_at",
    "verified_by",
    "updated_at",
]


# ---------------------------------------------------------------------------
# Operational response helpers
# ---------------------------------------------------------------------------


def allocation_request_response(
    row,
):
    """Add safe vendor context to an allocation-request row."""

    response = {
        field:
            row[
                field
            ]

        for field
        in ALLOCATION_REQUEST_RESPONSE_FIELDS
    }


    profile = get_vendor_profile(
        row[
            "vendor_id"
        ],
        database_path=DATABASE_PATH,
    )


    response[
        "vendor_name"
    ] = (
        profile.get(
            "full_name"
        )
        if profile
        else None
    )


    response[
        "business_name"
    ] = (
        profile.get(
            "business_name"
        )
        if profile
        else None
    )


    response[
        "application_vendor_id"
    ] = (
        profile.get(
            "application_vendor_id"
        )
        if profile
        else None
    )


    response[
        "vendor_type"
    ] = (
        profile.get(
            "vendor_type"
        )
        if profile
        else None
    )


    return response


def allocation_response(
    row,
):
    """Add safe vendor context to an allocation row."""

    response = {
        field:
            row[
                field
            ]

        for field
        in ALLOCATION_RESPONSE_FIELDS
    }


    profile = get_vendor_profile(
        row[
            "vendor_id"
        ],
        database_path=DATABASE_PATH,
    )


    response[
        "application_vendor_id"
    ] = (
        profile.get(
            "application_vendor_id"
        )
        if profile
        else None
    )


    response[
        "vendor_name"
    ] = (
        profile.get(
            "full_name"
        )
        if profile
        else None
    )


    response[
        "vendor_type"
    ] = (
        profile.get(
            "vendor_type"
        )
        if profile
        else None
    )


    return response


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def operational_error(
    exc: ValueError,
):
    """Translate domain errors into HTTP responses."""

    if isinstance(
        exc,
        OperationalNotFoundError,
    ):

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            str(
                exc
            ),
        ) from exc


    if isinstance(
        exc,
        OperationalConflictError,
    ):

        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            str(
                exc
            ),
        ) from exc


    raise HTTPException(
        422,
        str(
            exc
        ),
    ) from exc


def auth_error(
    exc: AuthError,
):
    """Translate authentication errors."""

    raise HTTPException(
        exc.status_code,
        str(
            exc
        ),
    ) from exc


# ---------------------------------------------------------------------------
# Session / authorization helpers
# ---------------------------------------------------------------------------


def request_session(
    request: FastAPIRequest,
    *roles: str,
) -> dict:

    if AUTH_TEST_BYPASS:

        return {
            "session_id":
                "TEST",

            "role":
                "ADMIN",

            "admin_id":
                "test_admin",

            "vendor_id":
                None,
        }


    session = get_session(
        request.cookies.get(
            SESSION_COOKIE_NAME
        ),
        database_path=DATABASE_PATH,
    )


    if session is None:

        raise HTTPException(
            http_status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
        )


    if (
        roles
        and session[
            "role"
        ] not in roles
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You do not have permission "
                "to perform this action"
            ),
        )


    return session


def require_vendor_owner(
    request: FastAPIRequest,
    vendor_id: str,
    *,
    allow_admin: bool = True,
) -> dict:

    permitted_roles = (
        (
            "VENDOR",
            "ADMIN",
        )
        if allow_admin
        else (
            "VENDOR",
        )
    )


    session = request_session(
        request,
        *permitted_roles,
    )


    if (
        session[
            "role"
        ]
        == "VENDOR"

        and session[
            "vendor_id"
        ]
        != vendor_id
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You may only access "
                "your own vendor record"
            ),
        )


    return session


def require_request_owner(
    request: FastAPIRequest,
    row,
) -> dict:

    session = request_session(
        request,
        "VENDOR",
        "ADMIN",
    )


    if (
        session[
            "role"
        ]
        == "VENDOR"

        and session[
            "vendor_id"
        ]
        != row[
            "vendor_id"
        ]
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You may only access "
                "your own request"
            ),
        )


    return session


def set_session_cookie(
    response: Response,
    token: str,
) -> None:

    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=(
            12
            * 60
            * 60
        ),
        path="/",
    )


def session_payload(
    session: dict,
) -> dict:

    payload = {
        "authenticated":
            True,

        "role":
            session[
                "role"
            ],
    }


    if (
        session[
            "role"
        ]
        == "VENDOR"
    ):

        payload[
            "vendor_id"
        ] = session[
            "vendor_id"
        ]


        payload[
            "vendor_profile"
        ] = get_vendor_profile(
            session[
                "vendor_id"
            ],
            database_path=DATABASE_PATH,
        )


    elif (
        session[
            "role"
        ]
        == "ADMIN"
    ):

        payload[
            "admin_id"
        ] = session[
            "admin_id"
        ]


    return payload


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _read_json(
    path: Path,
) -> dict[str, Any]:

    if not path.exists():
        return {}


    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):

        return {}


def _csv_row_count(
    path: Path,
) -> int:

    if not path.exists():
        return 0


    try:

        return int(
            len(
                pd.read_csv(
                    path
                )
            )
        )

    except Exception:
        return 0


@lru_cache(
    maxsize=1
)
def official_zone_descriptions() -> dict[
    str,
    str,
]:

    zones = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    return dict(
        zip(
            zones[
                "zone_id"
            ],
            zones[
                "official_description"
            ],
        )
    )


# ---------------------------------------------------------------------------
# Explanation helpers
# ---------------------------------------------------------------------------


def metric(
    row,
    name: str,
    digits: int = 0,
):

    value = row.get(
        name
    )


    try:

        numeric = float(
            value
        )


        if np.isfinite(
            numeric
        ):

            return (
                f"{numeric:,.{digits}f}"
            )


    except (
        TypeError,
        ValueError,
    ):
        pass


    return None


def explain(
    row,
    factor_weights=None,
):
    """Return deterministic factor-level explanations."""

    def count(
        name: str,
    ):

        value = metric(
            row,
            name,
        )

        return (
            value
            if value
            is not None
            else "unknown"
        )


    def distance(
        name: str,
    ):

        value = metric(
            row,
            name,
        )

        return (
            f"{value} m"
            if value
            is not None
            else "unknown"
        )


    evidence_count = metric(
        row,
        "evidence_count",
    )


    same_business = metric(
        row,
        "same_business_count",
    )


    items = {

        "business": {
            "title":
                "Business compatibility",

            "summary":
                (
                    f"{same_business or '0'} same-business records "
                    f"among {evidence_count or '0'} historical "
                    "associations."
                ),

            "details":
                (
                    "The score compares the business's historical "
                    "concentration with its citywide share, using "
                    "smoothing to reduce the influence of small samples. "
                    "Presence is not evidence of successful sales."
                ),

            "evidence": [
                {
                    "label":
                        "Same-business records",

                    "value":
                        same_business
                        or "0",
                },
                {
                    "label":
                        "Historical associations",

                    "value":
                        evidence_count
                        or "0",
                },
                {
                    "label":
                        "Evidence source",

                    "value":
                        "Text-associated vendor records",
                },
            ],
        },


        "commercial": {
            "title":
                "Commercial surroundings",

            "summary":
                (
                    f"{count('commercial_poi_count_250m')} mapped "
                    "commercial POIs within 250 m; "
                    f"{count('market_poi_count_500m')} markets "
                    "within 500 m."
                ),

            "details":
                (
                    "Nearby mapped commercial activity provides "
                    "context for possible customer activity. "
                    "It is not measured footfall, sales, or "
                    "a guarantee of demand."
                ),

            "evidence": [
                {
                    "label":
                        "Commercial POIs · 250 m",

                    "value":
                        count(
                            "commercial_poi_count_250m"
                        ),
                },
                {
                    "label":
                        "Markets · 500 m",

                    "value":
                        count(
                            "market_poi_count_500m"
                        ),
                },
                {
                    "label":
                        "Food POIs · 250 m",

                    "value":
                        count(
                            "food_poi_count_250m"
                        ),
                },
            ],
        },


        "access": {
            "title":
                "Road and transport access",

            "summary":
                (
                    f"{distance('distance_to_major_road_m')} "
                    "from a major road and "
                    f"{distance('distance_to_bus_access_m')} "
                    "from mapped bus access."
                ),

            "details":
                (
                    "Distances are measured from an approximate "
                    "analytical reference point. Road density and "
                    "transport proximity describe access, not "
                    "pedestrian footfall or traffic safety."
                ),

            "evidence": [
                {
                    "label":
                        "Major-road distance",

                    "value":
                        distance(
                            "distance_to_major_road_m"
                        ),
                },
                {
                    "label":
                        "Bus-access distance",

                    "value":
                        distance(
                            "distance_to_bus_access_m"
                        ),
                },
                {
                    "label":
                        "Pedestrian-road density",

                    "value":
                        (
                            metric(
                                row,
                                "pedestrian_road_density_250m_per_km2",
                            )
                            or "unknown"
                        )
                        + " m/km²",
                },
            ],
        },


        "facilities": {
            "title":
                "Nearby facilities",

            "summary":
                (
                    f"{count('healthcare_count_500m')} healthcare "
                    f"and {count('education_count_500m')} education "
                    "features mapped within 500 m."
                ),

            "details":
                (
                    "Infrastructure counts describe the surrounding "
                    "environment. Missing OSM records should not be "
                    "interpreted as proof that facilities do not exist."
                ),

            "evidence": [
                {
                    "label":
                        "Healthcare · 500 m",

                    "value":
                        count(
                            "healthcare_count_500m"
                        ),
                },
                {
                    "label":
                        "Education · 500 m",

                    "value":
                        count(
                            "education_count_500m"
                        ),
                },
                {
                    "label":
                        "Public toilets · 500 m",

                    "value":
                        count(
                            "toilet_count_500m"
                        ),
                },
                {
                    "label":
                        "Parking · 500 m",

                    "value":
                        count(
                            "parking_count_500m"
                        ),
                },
            ],
        },


        "preference": {
            "title":
                "Preferred division",

            "summary":
                (
                    "Located in "
                    f"{row.get('zone_division') or 'an unspecified division'}."
                ),

            "details":
                (
                    "A preferred-division match receives a higher "
                    "preference score. When fewer than the requested "
                    "number of local candidates qualify, clearly "
                    "identified alternatives outside the division "
                    "may be returned."
                ),

            "evidence": [
                {
                    "label":
                        "Zone division",

                    "value":
                        row.get(
                            "zone_division"
                        ),
                },
                {
                    "label":
                        "Fallback",

                    "value":
                        (
                            "Yes"
                            if row.get(
                                "fallback_used"
                            )
                            else "No"
                        ),
                },
            ],
        },


        "historical": {
            "title":
                "Historical evidence",

            "summary":
                (
                    f"{evidence_count or '0'} text-associated "
                    "vendor records contribute to the "
                    "evidence-density factor."
                ),

            "details":
                (
                    "This measures the volume of historical "
                    "association evidence, not current occupancy, "
                    "available capacity, or commercial success. "
                    "For an existing historical vendor, its recorded "
                    "location group is excluded from its own evidence."
                ),

            "evidence": [
                {
                    "label":
                        "Association records",

                    "value":
                        evidence_count
                        or "0",
                },
                {
                    "label":
                        "Evidence method",

                    "value":
                        row.get(
                            "evidence_method"
                        ),
                },
            ],
        },
    }


    weights = (
        factor_weights

        or RESEARCH_BASELINE_WEIGHTS
    )


    result = []


    for key in (
        FACTOR_ORDER
    ):

        item = items[
            key
        ]


        result.append(
            {
                "key":
                    key,

                "label":
                    item[
                        "title"
                    ],

                "score":
                    row.get(
                        f"{key}_score"
                    ),

                "weight":
                    (
                        float(
                            weights[
                                key
                            ]
                        )
                        * 100.0
                    ),

                "contribution":
                    row.get(
                        f"{key}_contribution"
                    ),

                "summary":
                    item[
                        "summary"
                    ],

                "details":
                    item[
                        "details"
                    ],

                "evidence":
                    item[
                        "evidence"
                    ],
            }
        )


    return result


# ---------------------------------------------------------------------------
# Shared recommendation context
# ---------------------------------------------------------------------------


def resolve_recommendation_context(
    payload,
    request: FastAPIRequest,
):
    """Resolve vendor inheritance and decision-policy context."""

    business = (
        payload.business
    )

    division = (
        payload.division
    )

    engine_vendor_id = (
        payload.vendor_id
    )

    profile = None


    if payload.vendor_id:

        require_vendor_owner(
            request,
            payload.vendor_id,
            allow_admin=True,
        )


        profile = get_vendor_profile(
            payload.vendor_id,
            database_path=DATABASE_PATH,
        )


        if profile is None:

            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND,
                (
                    "Unknown vendor_id: "
                    f"{payload.vendor_id}"
                ),
            )


        if not business:

            business = (
                profile[
                    "business_category"
                ]
            )


        if not division:

            division = (
                profile[
                    "preferred_division"
                ]
                or ""
            )


        # New operational vendors do not have historical evidence rows.
        if (
            profile[
                "vendor_type"
            ]
            == "NEW"
        ):

            engine_vendor_id = ""


    weight_profile = (
        derive_mcda_weights(
            profile
        )
    )


    return {
        "business":
            business,

        "division":
            division,

        "engine_vendor_id":
            engine_vendor_id,

        "profile":
            profile,

        "weight_profile":
            weight_profile,
    }


# ===========================================================================
# Health
# ===========================================================================


@app.get(
    "/api/health"
)
def health():

    return {
        "status":
            "ok",

        "mode":
            "research",
    }


# ===========================================================================
# Authentication
# ===========================================================================


@app.post(
    "/api/auth/vendor/request-otp",
    tags=[
        "Authentication"
    ],
)
def request_vendor_otp(
    payload: VendorOtpRequestBody,
):

    try:

        return create_otp_challenge(
            payload.mobile,
            database_path=DATABASE_PATH,
        )

    except AuthError as exc:

        auth_error(
            exc
        )

    except RuntimeError as exc:

        raise HTTPException(
            503,
            (
                "Authentication service "
                "is not configured"
            ),
        ) from exc


@app.post(
    "/api/auth/vendor/verify-otp",
    tags=[
        "Authentication"
    ],
)
def verify_vendor_otp(
    payload: VendorOtpVerifyBody,
    response: Response,
):

    try:

        token, session = (
            verify_otp_challenge(
                payload.challenge_id,
                payload.otp,
                database_path=DATABASE_PATH,
            )
        )

    except AuthError as exc:

        auth_error(
            exc
        )

    except RuntimeError as exc:

        raise HTTPException(
            503,
            (
                "Authentication service "
                "is not configured"
            ),
        ) from exc


    set_session_cookie(
        response,
        token,
    )


    return session_payload(
        session
    )


@app.post(
    "/api/auth/admin/login",
    tags=[
        "Authentication"
    ],
)
def admin_login(
    payload: AdminLoginBody,
    response: Response,
):

    try:

        token, session = (
            create_admin_session(
                payload.username,
                payload.password,
                database_path=DATABASE_PATH,
            )
        )

    except AuthError as exc:

        auth_error(
            exc
        )


    set_session_cookie(
        response,
        token,
    )


    return session_payload(
        session
    )


@app.get(
    "/api/auth/me",
    tags=[
        "Authentication"
    ],
)
def current_user(
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "VENDOR",
        "ADMIN",
        "NEW_VENDOR_ONBOARDING",
    )


    return session_payload(
        session
    )


@app.post(
    "/api/auth/logout",
    tags=[
        "Authentication"
    ],
)
def logout(
    request: FastAPIRequest,
    response: Response,
):

    revoke_session(
        request.cookies.get(
            SESSION_COOKIE_NAME
        ),
        database_path=DATABASE_PATH,
    )


    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
    )


    return {
        "authenticated":
            False,
    }


# ===========================================================================
# Vendor registration / profile
# ===========================================================================


@app.post(
    "/api/vendors",
    status_code=(
        http_status
        .HTTP_201_CREATED
    ),
    response_model=(
        VendorProfileResponse
    ),
    tags=[
        "Vendors"
    ],
)
def register_operational_vendor(
    payload: VendorRegistrationBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "NEW_VENDOR_ONBOARDING",
    )


    try:

        profile = register_vendor(
            payload.model_dump(),
            database_path=DATABASE_PATH,
        )


        if not AUTH_TEST_BYPASS:

            bind_onboarding_session(
                session[
                    "session_id"
                ],
                profile[
                    "vendor_id"
                ],
                database_path=DATABASE_PATH,
            )


        return profile


    except AuthError as exc:

        auth_error(
            exc
        )


    except (
        OperationalConflictError,
        OperationalNotFoundError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


@app.get(
    "/api/vendors/me/dashboard",
    tags=[
        "Vendors"
    ],
)
def vendor_dashboard(
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "VENDOR",
    )


    vendor_id = session[
        "vendor_id"
    ]


    profile = get_vendor_profile(
        vendor_id,
        database_path=DATABASE_PATH,
    )


    if profile is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            "Vendor profile not found",
        )


    activity = (
        get_vendor_dashboard_activity(
            vendor_id,
            DATABASE_PATH,
        )
    )


    descriptions = (
        official_zone_descriptions()
    )


    active_row = (
        activity[
            "active_allocation"
        ]
    )


    active_allocation = None


    if active_row is not None:

        active_allocation = {
            "allocation_id":
                active_row[
                    "allocation_id"
                ],

            "zone_id":
                active_row[
                    "zone_id"
                ],

            "zone_description":
                descriptions.get(
                    active_row[
                        "zone_id"
                    ]
                ),

            "allocation_type":
                active_row[
                    "allocation_type"
                ],

            "allocated_at":
                active_row[
                    "allocated_at"
                ],

            "status":
                active_row[
                    "status"
                ],

            "live_zone_status":
                active_row[
                    "live_zone_status"
                ],

            "official_capacity":
                active_row[
                    "official_capacity"
                ],

            "current_vendor_count":
                active_row[
                    "current_vendor_count"
                ],

            "available_capacity":
                active_row[
                    "available_capacity"
                ],
        }


    requests = []


    counts = {
        status:
            0
        for status
        in (
            "PENDING",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
        )
    }


    for row in (
        activity[
            "requests"
        ]
    ):

        counts[
            row[
                "status"
            ]
        ] += 1


        previous_zone_id = (
            activity[
                "previous_zone_by_request"
            ].get(
                row[
                    "request_id"
                ]
            )
        )


        if (
            previous_zone_id
            is None

            and row[
                "request_type"
            ]
            == "RELOCATION"

            and row[
                "status"
            ]
            == "PENDING"

            and active_row
            is not None
        ):

            previous_zone_id = (
                active_row[
                    "zone_id"
                ]
            )


        requests.append(
            {
                "request_id":
                    row[
                        "request_id"
                    ],

                "request_type":
                    row[
                        "request_type"
                    ],

                "requested_zone_id":
                    row[
                        "zone_id"
                    ],

                "zone_description":
                    descriptions.get(
                        row[
                            "zone_id"
                        ]
                    ),

                "status":
                    row[
                        "status"
                    ],

                "created_at":
                    row[
                        "created_at"
                    ],

                "updated_at":
                    row[
                        "updated_at"
                    ],

                "reviewed_at":
                    row[
                        "reviewed_at"
                    ],

                "rejection_reason":
                    row[
                        "rejection_reason"
                    ],

                "previous_zone_id":
                    previous_zone_id,

                "previous_zone_description":
                    descriptions.get(
                        previous_zone_id
                    ),
            }
        )


    has_pending = (
        counts[
            "PENDING"
        ]
        > 0
    )


    profile_active = (
        profile[
            "status"
        ]
        == "ACTIVE"
    )


    blocked_reason = None


    if not profile_active:

        blocked_reason = (
            "Vendor profile is inactive"
        )


    elif has_pending:

        blocked_reason = (
            "Pending request already exists"
        )


    return {
        "profile": {
            "vendor_id":
                profile[
                    "vendor_id"
                ],

            "application_vendor_id":
                profile[
                    "application_vendor_id"
                ],

            "vendor_type":
                profile[
                    "vendor_type"
                ],

            "full_name":
                profile[
                    "full_name"
                ],

            "business_name":
                profile[
                    "business_name"
                ],

            "business_category":
                profile[
                    "business_category"
                ],

            "preferred_division":
                profile[
                    "preferred_division"
                ],

            "preferred_locality":
                profile[
                    "preferred_locality"
                ],

            "priority_profile":
                profile[
                    "priority_profile"
                ],

            "prefer_parking":
                profile[
                    "parking_preference"
                ],

            "prefer_transport":
                profile[
                    "transport_preference"
                ],

            "prefer_market":
                profile[
                    "market_preference"
                ],

            "language":
                profile[
                    "preferred_language"
                ],

            "status":
                profile[
                    "status"
                ],

            "created_at":
                profile[
                    "created_at"
                ],

            "updated_at":
                profile[
                    "updated_at"
                ],
        },

        "active_allocation":
            active_allocation,

        "requests":
            requests,

        "request_summary": {
            "total_requests":
                len(
                    requests
                ),

            "pending_count":
                counts[
                    "PENDING"
                ],

            "approved_count":
                counts[
                    "APPROVED"
                ],

            "rejected_count":
                counts[
                    "REJECTED"
                ],

            "cancelled_count":
                counts[
                    "CANCELLED"
                ],
        },

        "action_state": {
            "has_active_allocation":
                active_allocation
                is not None,

            "has_pending_request":
                has_pending,

            "can_submit_request":
                (
                    profile_active
                    and not has_pending
                ),

            "blocked_reason":
                blocked_reason,
        },
    }


@app.get(
    "/api/vendors/{vendor_id}",
    response_model=VendorProfileResponse,
    tags=[
        "Vendors"
    ],
)
def unified_vendor_profile(
    vendor_id: str,
    request: FastAPIRequest,
):

    require_vendor_owner(
        request,
        vendor_id,
    )


    profile = get_vendor_profile(
        vendor_id,
        database_path=DATABASE_PATH,
    )


    if profile is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown vendor_id: {vendor_id}",
        )


    return profile


@app.patch(
    "/api/vendors/{vendor_id}",
    response_model=VendorProfileResponse,
    tags=[
        "Vendors"
    ],
)
def patch_vendor_profile(
    vendor_id: str,
    payload: VendorProfileUpdateBody,
    request: FastAPIRequest,
):

    require_vendor_owner(
        request,
        vendor_id,
    )


    try:

        return update_vendor_profile(
            vendor_id,
            payload.model_dump(
                exclude_unset=True
            ),
            database_path=DATABASE_PATH,
        )


    except (
        OperationalConflictError,
        OperationalNotFoundError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


@app.get(
    "/api/vendors/{vendor_id}/active-allocation",
    response_model=(
        ActiveVendorAllocationResponse
    ),
    tags=[
        "Vendors"
    ],
)
def vendor_active_allocation(
    vendor_id: str,
    request: FastAPIRequest,
):

    require_vendor_owner(
        request,
        vendor_id,
    )


    if (
        get_vendor_profile(
            vendor_id,
            database_path=DATABASE_PATH,
        )
        is None
    ):

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown vendor_id: {vendor_id}",
        )


    row = (
        get_active_allocation_for_vendor(
            vendor_id,
            database_path=DATABASE_PATH,
        )
    )


    return {
        "allocation":
            (
                allocation_response(
                    row
                )

                if row
                is not None

                else None
            )
    }


@app.get(
    "/api/vendors/me/eligible-zones",
    tags=[
        "Vendors"
    ],
)
def vendor_eligible_zones(
    request: FastAPIRequest,
):
    """Return map context without duplicating recommendation scoring."""

    session = request_session(
        request,
        "VENDOR",
    )


    profile = get_vendor_profile(
        session[
            "vendor_id"
        ],
        database_path=DATABASE_PATH,
    )


    zones = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    live = (
        get_live_zone_status_map(
            DATABASE_PATH
        )
    )


    zones = zones.loc[
        zones.zone_type.eq(
            "FREE"
        )
        & zones[
            "geometry_usable_for_reference_model"
        ]
        .astype(str)
        .str.lower()
        .isin(
            [
                "true",
                "1",
                "yes",
            ]
        )
    ].copy()


    activity = (
        get_vendor_dashboard_activity(
            session[
                "vendor_id"
            ],
            DATABASE_PATH,
        )
    )


    pending = next(
        (
            item
            for item
            in activity[
                "requests"
            ]
            if item[
                "status"
            ]
            == "PENDING"
        ),
        None,
    )


    active = activity[
        "active_allocation"
    ]


    current_zone_id = (
        active[
            "zone_id"
        ]
        if active
        else None
    )


    pending_zone_id = (
        pending[
            "zone_id"
        ]
        if pending
        else None
    )


    highlighted_ids = {
        zone_id

        for zone_id
        in (
            current_zone_id,
            pending_zone_id,
        )

        if zone_id
    }


    records = []


    for row in zones.itertuples(
        index=False
    ):

        state = live.get(
            row.zone_id
        )


        if state is None:
            continue


        available = state[
            "available_capacity"
        ]


        eligible = bool(
            state[
                "status"
            ]
            == "OPEN"

            and (
                available
                is None

                or available
                > 0
            )
        )


        if (
            not eligible

            and row.zone_id
            not in highlighted_ids
        ):
            continue


        records.append(
            {
                "zone_id":
                    row.zone_id,

                "zone_division":
                    row.zone_division,

                "zone_type":
                    row.zone_type,

                "official_description":
                    row.official_description,

                "official_capacity":
                    state[
                        "official_capacity"
                    ],

                "current_vendor_count":
                    state[
                        "current_vendor_count"
                    ],

                "available_capacity":
                    available,

                "live_status":
                    state[
                        "status"
                    ],

                "eligible":
                    eligible,

                "preferred_division_match":
                    bool(
                        profile
                        and profile.get(
                            "preferred_division"
                        )
                        and row.zone_division
                        == profile[
                            "preferred_division"
                        ]
                    ),
            }
        )


    return {
        "zones":
            records,

        "count":
            len(
                records
            ),

        "current_zone_id":
            current_zone_id,

        "pending_zone_id":
            pending_zone_id,
    }


# ===========================================================================
# Allocation request workflow
# ===========================================================================


@app.post(
    "/api/allocation-requests",
    status_code=(
        http_status
        .HTTP_201_CREATED
    ),
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def submit_allocation_request(
    payload: AllocationRequestCreate,
    request: FastAPIRequest,
):

    vendor_id = (
        payload.vendor_id.strip()
    )


    zone_id = (
        payload.zone_id.strip()
    )


    if not vendor_id:

        raise HTTPException(
            422,
            "vendor_id must not be empty",
        )


    if not zone_id:

        raise HTTPException(
            422,
            "zone_id must not be empty",
        )


    require_vendor_owner(
        request,
        vendor_id,
        allow_admin=False,
    )


    if (
        get_vendor_profile(
            vendor_id,
            database_path=DATABASE_PATH,
        )
        is None
    ):

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown vendor_id: {vendor_id}",
        )


    try:

        row = create_allocation_request(
            vendor_id=vendor_id,
            zone_id=zone_id,
            request_type=(
                payload.request_type
            ),
            business_category=(
                payload.business_category
            ),
            preferred_division=(
                payload.preferred_division
            ),
            notes=(
                payload.notes
            ),
            database_path=DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return allocation_request_response(
        row
    )


@app.get(
    "/api/allocation-requests",
    response_model=(
        AllocationRequestListResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def allocation_request_list(
    request: FastAPIRequest,
    request_status: (
        Literal[
            "PENDING",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
        ]
        | None
    ) = Query(
        default=None,
        alias="status",
    ),
):

    request_session(
        request,
        "ADMIN",
    )


    rows = list_allocation_requests(
        status=request_status,
        database_path=DATABASE_PATH,
    )


    return {
        "requests": [
            allocation_request_response(
                row
            )
            for row
            in rows
        ],

        "count":
            len(
                rows
            ),

        "status_filter":
            request_status,
    }


@app.get(
    "/api/allocation-requests/{request_id}",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def allocation_request_detail(
    request_id: str,
    request: FastAPIRequest,
):

    row = get_allocation_request(
        request_id,
        database_path=DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            (
                "Unknown allocation request: "
                f"{request_id}"
            ),
        )


    require_request_owner(
        request,
        row,
    )


    return allocation_request_response(
        row
    )


@app.post(
    "/api/allocation-requests/{request_id}/cancel",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def cancel_request(
    request_id: str,
    request: FastAPIRequest,
):

    existing = get_allocation_request(
        request_id,
        database_path=DATABASE_PATH,
    )


    if existing is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            (
                "Unknown allocation request: "
                f"{request_id}"
            ),
        )


    require_request_owner(
        request,
        existing,
    )


    try:

        row = cancel_allocation_request(
            request_id,
            database_path=DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return allocation_request_response(
        row
    )


@app.post(
    "/api/allocation-requests/{request_id}/approve",
    response_model=ApprovalResponse,
    tags=[
        "Allocation Requests"
    ],
)
def approve_request(
    request_id: str,
    payload: ApprovalBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    approved_by = (
        payload.approved_by

        if (
            AUTH_TEST_BYPASS
            and payload.approved_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        result = approve_allocation_request(
            request_id=request_id,
            approved_by=approved_by,
            notes=payload.notes,
            database_path=DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return {
        "request":
            allocation_request_response(
                result[
                    "request"
                ]
            ),

        "allocation":
            allocation_response(
                result[
                    "allocation"
                ]
            ),

        "released_allocation":
            (
                allocation_response(
                    result[
                        "released_allocation"
                    ]
                )

                if result[
                    "released_allocation"
                ]
                is not None

                else None
            ),
    }


@app.post(
    "/api/allocation-requests/{request_id}/reject",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def reject_request(
    request_id: str,
    payload: RejectionBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    reviewed_by = (
        payload.reviewed_by

        if (
            AUTH_TEST_BYPASS
            and payload.reviewed_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        row = reject_allocation_request(
            request_id=request_id,
            reviewed_by=reviewed_by,
            rejection_reason=(
                payload.rejection_reason
            ),
            notes=(
                payload.notes
            ),
            database_path=DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return allocation_request_response(
        row
    )


# ===========================================================================
# Allocations
# ===========================================================================


@app.get(
    "/api/allocations",
    response_model=AllocationListResponse,
    tags=[
        "Allocations"
    ],
)
def allocation_list(
    request: FastAPIRequest,
    allocation_status: (
        Literal[
            "ACTIVE",
            "RELEASED",
        ]
        | None
    ) = Query(
        default=None,
        alias="status",
    ),
):

    request_session(
        request,
        "ADMIN",
    )


    rows = list_allocations(
        status=allocation_status,
        database_path=DATABASE_PATH,
    )


    return {
        "allocations": [
            allocation_response(
                row
            )
            for row
            in rows
        ],

        "count":
            len(
                rows
            ),

        "status_filter":
            allocation_status,
    }


@app.get(
    "/api/allocations/{allocation_id}",
    response_model=AllocationResponse,
    tags=[
        "Allocations"
    ],
)
def allocation_detail(
    allocation_id: str,
    request: FastAPIRequest,
):

    request_session(
        request,
        "ADMIN",
    )


    row = get_allocation(
        allocation_id,
        database_path=DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown allocation: {allocation_id}",
        )


    return allocation_response(
        row
    )


# ===========================================================================
# Goal Programming allocation planner
# ===========================================================================


@app.post(
    "/api/admin/allocation-plan",
    tags=[
        "Admin",
        "Allocation Planning",
    ],
)
def create_allocation_plan(
    payload: AllocationPlanningBody,
    request: FastAPIRequest,
):
    """Create an advisory multi-vendor allocation plan.

    No database mutation occurs here.
    """

    request_session(
        request,
        "ADMIN",
    )


    try:

        result = (
            plan_vendor_allocations(
                payload.vendor_ids,
                database_path=(
                    DATABASE_PATH
                ),
                require_verified=(
                    payload.require_verified
                ),
                candidate_pool_size=(
                    payload.candidate_pool_size
                ),
                reject_pending_requests=(
                    payload.reject_pending_requests
                ),
                max_vendors=(
                    payload.max_vendors
                ),
                time_limit_seconds=(
                    payload.time_limit_seconds
                ),
            )
        )


    except AllocationPlanningValidationError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    except ValueError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    except AllocationOptimizationError as exc:

        raise HTTPException(
            503,
            (
                "Allocation optimizer could "
                f"not produce a plan: {exc}"
            ),
        ) from exc


    return clean(
        result.to_dict()
    )


# ===========================================================================
# Zone live status
# ===========================================================================


@app.get(
    "/api/zones/{zone_id}/live-status",
    response_model=(
        ZoneLiveStatusResponse
    ),
    tags=[
        "Zone Live Status"
    ],
)
def zone_live_status(
    zone_id: str,
):

    row = get_zone_live_status(
        zone_id,
        database_path=DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown zone_id: {zone_id}",
        )


    return {
        field:
            row[
                field
            ]

        for field
        in ZONE_LIVE_STATUS_RESPONSE_FIELDS
    }


@app.patch(
    "/api/zones/{zone_id}/live-status",
    response_model=(
        ZoneLiveStatusResponse
    ),
    tags=[
        "Admin",
        "Zone Live Status",
    ],
)
def patch_zone_live_status(
    zone_id: str,
    payload: AdminZoneStatusBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    verified_by = (
        payload.verified_by

        if (
            AUTH_TEST_BYPASS
            and payload.verified_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        row = update_zone_live_status(
            zone_id,
            payload.status,
            verified_by,
            database_path=DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return {
        field:
            row[
                field
            ]

        for field
        in ZONE_LIVE_STATUS_RESPONSE_FIELDS
    }


# ===========================================================================
# Recommendation options
# ===========================================================================


@app.get(
    "/api/options"
)
def options():

    zones = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        usecols=[
            "zone_division"
        ],
    )


    divisions = sorted(
        value

        for value
        in zones[
            "zone_division"
        ]
        .dropna()
        .unique()

        if value
        != "Citywide"
    )


    policy = (
        load_base_weight_policy()
    )


    return {
        "categories":
            CATEGORIES,

        "divisions":
            divisions,

        "mode":
            "research",

        "weight_source":
            policy[
                "source"
            ],

        "notice":
            (
                "Recommendations use operational "
                "zone status when available. "
                "Historical vendor evidence is not "
                "treated as current occupancy, "
                "vacancy, demand, or business success."
            ),
    }


# ===========================================================================
# Recommendation engine
# ===========================================================================


@app.post(
    "/api/recommendations"
)
def recommendations(
    req: Request,
    request: FastAPIRequest,
):

    context = (
        resolve_recommendation_context(
            req,
            request,
        )
    )


    business = context[
        "business"
    ]


    division = context[
        "division"
    ]


    engine_vendor_id = context[
        "engine_vendor_id"
    ]


    profile = context[
        "profile"
    ]


    weight_profile = context[
        "weight_profile"
    ]


    effective_weights = (
        weight_profile[
            "final_weights"
        ]
    )


    try:

        result = recommend(
            business,
            division,
            engine_vendor_id,
            req.top_n,
            req.exclude_zone,
            req.require_verified,
            use_live_status=True,
            database_path=DATABASE_PATH,
            factor_weights=(
                effective_weights
            ),
        )


    except ValueError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    metadata = {
        "candidate_count_before_live_filter":
            result.attrs.get(
                "candidate_count_before_live_filter",
                0,
            ),

        "candidate_count_after_live_filter":
            result.attrs.get(
                "candidate_count_after_live_filter",
                0,
            ),

        "candidate_count_after_verified_filter":
            result.attrs.get(
                "candidate_count_after_verified_filter",
                0,
            ),

        "live_filter_applied":
            result.attrs.get(
                "live_filter_applied",
                True,
            ),

        "personalization_applied":
            bool(
                req.vendor_id
            ),

        "priority_profile":
            (
                profile[
                    "priority_profile"
                ]

                if profile

                else "BALANCED"
            ),

        "preference_flags": {
            "parking":
                bool(
                    profile
                    and profile[
                        "parking_preference"
                    ]
                ),

            "transport":
                bool(
                    profile
                    and profile[
                        "transport_preference"
                    ]
                ),

            "market":
                bool(
                    profile
                    and profile[
                        "market_preference"
                    ]
                ),
        },

        "weight_source":
            weight_profile[
                "weight_source"
            ],

        "ahp_consistency_ratio":
            weight_profile[
                "ahp_consistency_ratio"
            ],

        "base_factor_weights":
            weight_profile[
                "base_weights"
            ],

        "effective_factor_weights":
            effective_weights,

        "weight_modifiers":
            weight_profile[
                "multipliers"
            ],
    }


    if result.empty:

        return {
            "recommendations":
                [],

            "count":
                0,

            "mode":
                "research",

            "notice":
                (
                    "No operationally available zones "
                    "meet the selected filters. "
                    "No allocation is inferred."
                ),

            **metadata,
        }


    fields = [
        "rank",
        "zone_id",
        "zone_division",
        "official_description",
        "official_capacity",
        "score",
        "score_type",
        "candidate_status",
        "fallback_used",
        "reference_group_id",
        "shared_reference",
        "shared_reference_group_size",
        "reference_warning",
        "geometry_method",
        "source_confidence",
        "environment_cluster",
        "evidence_count",
        "same_business_count",
        "score_coverage",
        "limitations",
        "reason",
        "verified_available_capacity",
        "verified_at",
        "live_verified",
        "evidence_method",
        "distance_to_major_road_m",
        "distance_to_bus_access_m",
        "pedestrian_road_density_250m_per_km2",
        "commercial_poi_count_250m",
        "market_poi_count_500m",
        "food_poi_count_250m",
        "healthcare_count_500m",
        "education_count_500m",
        "toilet_count_500m",
        "parking_count_500m",
        "live_status",
        "current_vendor_count",
        "available_capacity",
    ]


    records = []


    for _, row in (
        result.iterrows()
    ):

        item = {
            key:
                row.get(
                    key
                )

            for key
            in fields
        }


        item[
            "factors"
        ] = explain(
            row,
            effective_weights,
        )


        records.append(
            clean(
                item
            )
        )


    return {
        "recommendations":
            records,

        "count":
            len(
                records
            ),

        "mode":
            "research",

        "notice":
            (
                "Explainable decision-support "
                "scores, not success probabilities "
                "or municipal permits."
            ),

        **metadata,
    }


# ===========================================================================
# Recommendation sensitivity / robustness
# ===========================================================================


@app.post(
    "/api/recommendations/sensitivity",
    tags=[
        "Research Evaluation"
    ],
)
def recommendation_sensitivity(
    payload: SensitivityRequest,
    request: FastAPIRequest,
):
    """Evaluate ranking sensitivity to reasonable MCDA weight changes."""

    context = (
        resolve_recommendation_context(
            payload,
            request,
        )
    )


    config = SensitivityConfig(
        top_n=(
            payload.top_n
        ),
        monte_carlo_samples=(
            payload
            .monte_carlo_samples
        ),
        monte_carlo_delta=(
            payload
            .monte_carlo_delta
        ),
        random_seed=(
            payload.random_seed
        ),
    )


    try:

        report = (
            evaluate_weight_sensitivity(
                business=(
                    context[
                        "business"
                    ]
                ),
                division=(
                    context[
                        "division"
                    ]
                ),
                vendor_id=(
                    context[
                        "engine_vendor_id"
                    ]
                ),
                exclude_zone=(
                    payload.exclude_zone
                ),
                vendor_profile=(
                    context[
                        "profile"
                    ]
                ),
                require_verified=(
                    payload.require_verified
                ),
                use_live_status=True,
                database_path=(
                    DATABASE_PATH
                ),
                config=config,
            )
        )


    except ValueError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    response = {
        key:
            value

        for (
            key,
            value,
        ) in report.items()

        if key not in {
            "scenario_metrics",
            "scenario_top_k",
        }
    }


    response[
        "requested_vendor_id"
    ] = (
        payload.vendor_id
        or None
    )


    if payload.include_scenarios:

        response[
            "scenario_metrics"
        ] = (
            report[
                "scenario_metrics"
            ]
            .to_dict(
                orient="records"
            )
        )


        response[
            "scenario_top_k"
        ] = (
            report[
                "scenario_top_k"
            ]
            .to_dict(
                orient="records"
            )
        )


    return clean(
        response
    )


# ===========================================================================
# Historical non-identifying model lookup
# ===========================================================================


@app.get(
    "/api/vendor/{vendor_id}"
)
def vendor(
    vendor_id: str,
):

    # This remains a model-data lookup,
    # not an identity-verification endpoint.

    vendors = pd.read_csv(
        DATA
        / "vendor_training_registry.csv",
        dtype={
            "vendor_id":
                str,
        },
    )


    found = vendors.loc[
        vendors.vendor_id.eq(
            vendor_id
        )
    ]


    if found.empty:

        raise HTTPException(
            404,
            "Vendor ID not found",
        )


    row = found.iloc[
        0
    ]


    return clean(
        {
            "vendor_id":
                row.vendor_id,

            "business_category":
                row.business_category,

            "division":
                row.vendor_division,

            "historical_proposed_zone_id":
                row.proposed_zone_id,

            "current_zone_verified":
                row.current_zone_verified,

            "notice":
                (
                    "A historical proposed zone is "
                    "not a verified current vending location."
                ),
        }
    )


# ===========================================================================
# Geometry / zone lookup
# ===========================================================================


@app.get(
    "/api/zones/geometry"
)
def geometry():
    """Return analytical reference points only."""

    path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "reference_points.geojson"
    )


    if not path.exists():

        raise HTTPException(
            503,
            (
                "Run geometry_duplicate_audit.py "
                "first."
            ),
        )


    return JSONResponse(
        json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    )


@app.get(
    "/api/zone/{zone_id}"
)
def zone(
    zone_id: str,
):

    zones = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    result = zones.loc[
        zones.zone_id.eq(
            zone_id
        )
    ]


    if result.empty:

        raise HTTPException(
            404,
            "Zone not found",
        )


    return clean(
        result.iloc[
            0
        ].to_dict()
    )


# ===========================================================================
# Admin overview / zones
# ===========================================================================


@app.get(
    "/api/admin/overview",
    tags=[
        "Admin"
    ],
)
def admin_overview(
    request: FastAPIRequest,
):

    request_session(
        request,
        "ADMIN",
    )


    return get_admin_overview(
        database_path=DATABASE_PATH
    )


@app.get(
    "/api/admin/zones",
    tags=[
        "Admin"
    ],
)
def admin_zones(
    request: FastAPIRequest,
    division: str = "",
    zone_type: str = "",
    live_status: str = "",
    q: str = "",
):

    request_session(
        request,
        "ADMIN",
    )


    zones = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    live = pd.DataFrame(
        get_live_zone_status_map(
            DATABASE_PATH
        ).values()
    )


    if live.empty:

        live = pd.DataFrame(
            columns=[
                "zone_id",
                "official_capacity",
                "current_vendor_count",
                "available_capacity",
                "status",
                "verified_at",
                "verified_by",
                "updated_at",
            ]
        )


    live = live.rename(
        columns={
            "status":
                "live_status",
        }
    )


    zones = zones.merge(
        live,
        on="zone_id",
        how="left",
        suffixes=(
            "_canonical",
            "",
        ),
        validate="one_to_one",
    )


    audit_path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "zone_reference_audit.csv"
    )


    if audit_path.exists():

        audit = pd.read_csv(
            audit_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        audit_columns = [
            column

            for column
            in [
                "zone_id",
                "reference_group_id",
                "shared_reference",
                "reference_audit_status",
            ]

            if column
            in audit.columns
        ]


        zones = zones.merge(
            audit[
                audit_columns
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    if division:

        zones = zones.loc[
            zones.division.eq(
                division
            )
        ]


    if zone_type:

        zones = zones.loc[
            zones.zone_type.eq(
                zone_type
            )
        ]


    if live_status:

        zones = zones.loc[
            zones.live_status.eq(
                live_status
            )
        ]


    if q:

        term = q.strip()


        zones = zones.loc[
            zones.zone_id.str.contains(
                term,
                case=False,
                na=False,
                regex=False,
            )
            | zones[
                "official_description"
            ].str.contains(
                term,
                case=False,
                na=False,
                regex=False,
            )
        ]


    fields = [
        column

        for column
        in [
            "zone_id",
            "division",
            "zone_type",
            "official_description",
            "official_capacity",
            "current_vendor_count",
            "available_capacity",
            "live_status",
            "verified_at",
            "verified_by",
            "updated_at",
            "reference_group_id",
            "shared_reference",
            "reference_audit_status",
        ]

        if column
        in zones.columns
    ]


    records = [
        clean(
            row
        )

        for row
        in (
            zones[
                fields
            ]
            .sort_values(
                "zone_id"
            )
            .to_dict(
                "records"
            )
        )
    ]


    return {
        "zones":
            records,

        "count":
            len(
                records
            ),
    }


# ===========================================================================
# Research / model readiness
# ===========================================================================


@app.get(
    "/api/research/status",
    tags=[
        "Research Evaluation"
    ],
)
def research_status():
    """Return non-sensitive implementation and research readiness state."""

    try:

        policy = (
            load_base_weight_policy()
        )

        policy_valid = True

        policy_error = None


    except ValueError as exc:

        policy = {
            "source":
                "INVALID_POLICY",

            "weights":
                RESEARCH_BASELINE_WEIGHTS,

            "consistency_ratio":
                None,

            "policy_path":
                None,
        }

        policy_valid = False

        policy_error = str(
            exc
        )


    expert_dir = (
        ROOT
        / "reports"
        / "expert_review"
    )


    ahp_dir = (
        ROOT
        / "reports"
        / "ahp_calibration"
    )


    model_report_dir = (
        ROOT
        / "reports"
        / "suitability_model"
    )


    model_artifact_dir = (
        ROOT
        / "artifacts"
        / "models"
    )


    queue_path = (
        expert_dir
        / "review_queue.csv"
    )


    labels_path = (
        expert_dir
        / "expert_labels.csv"
    )


    aggregated_path = (
        expert_dir
        / "aggregated_expert_labels.csv"
    )


    model_dataset_path = (
        expert_dir
        / "model_dataset.csv"
    )


    quality_path = (
        expert_dir
        / "expert_label_quality.json"
    )


    feature_manifest_path = (
        expert_dir
        / "model_feature_manifest.json"
    )


    training_report_path = (
        model_report_dir
        / "model_comparison.json"
    )


    training_manifest_path = (
        model_report_dir
        / "training_manifest.json"
    )


    selected_model_path = (
        model_artifact_dir
        / "selected_suitability_model.joblib"
    )


    shap_summary_path = (
        model_report_dir
        / "shap_summary.json"
    )


    quality = _read_json(
        quality_path
    )


    training = _read_json(
        training_report_path
    )


    shap_summary = _read_json(
        shap_summary_path
    )


    queue_count = (
        _csv_row_count(
            queue_path
        )
    )


    judgment_count = (
        _csv_row_count(
            labels_path
        )
    )


    model_dataset_rows = (
        _csv_row_count(
            model_dataset_path
        )
    )


    return clean(
        {
            "mcda": {
                "active":
                    True,

                "factor_count":
                    len(
                        FACTOR_ORDER
                    ),

                "factors":
                    list(
                        FACTOR_ORDER
                    ),

                "weight_source":
                    policy[
                        "source"
                    ],

                "weights":
                    policy[
                        "weights"
                    ],

                "policy_valid":
                    policy_valid,

                "policy_error":
                    policy_error,

                "ahp_consistency_ratio":
                    policy[
                        "consistency_ratio"
                    ],
            },

            "ahp": {
                "template_exists":
                    (
                        ahp_dir
                        / "expert_pairwise_template.csv"
                    ).exists(),

                "review_file_exists":
                    (
                        ahp_dir
                        / "expert_pairwise_reviews.csv"
                    ).exists(),

                "calibrated_policy_exists":
                    DEFAULT_POLICY_PATH.exists(),

                "active_source":
                    policy[
                        "source"
                    ],
            },

            "sensitivity_analysis": {
                "available":
                    True,

                "method":
                    (
                        "One-at-a-time and Monte Carlo "
                        "MCDA weight perturbation"
                    ),
            },

            "allocation_optimizer": {
                "available":
                    True,

                "method":
                    (
                        "Two-stage pre-emptive "
                        "Goal Programming MILP"
                    ),

                "database_writes":
                    False,

                "approval_required":
                    True,
            },

            "expert_labels": {
                "queue_exists":
                    queue_path.exists(),

                "queue_count":
                    queue_count,

                "labels_exist":
                    labels_path.exists(),

                "judgment_count":
                    judgment_count,

                "aggregated_labels_exist":
                    aggregated_path.exists(),

                "model_dataset_exists":
                    model_dataset_path.exists(),

                "model_dataset_rows":
                    model_dataset_rows,

                "quality_report_exists":
                    quality_path.exists(),

                "ready_for_model_count":
                    quality.get(
                        "ready_for_model_count"
                    ),

                "feature_manifest_exists":
                    feature_manifest_path.exists(),
            },

            "supervised_model": {
                "role":
                    "EXPERIMENTAL",

                "trained":
                    selected_model_path.exists(),

                "selected_model":
                    training.get(
                        "selected_model"
                    ),

                "comparison_report_exists":
                    training_report_path.exists(),

                "training_manifest_exists":
                    training_manifest_path.exists(),

                "production_recommendation_path":
                    False,
            },

            "shap": {
                "available":
                    bool(
                        shap_summary
                    ),

                "summary_exists":
                    shap_summary_path.exists(),

                "production_recommendation_path":
                    False,
            },
        }
    )


# ===========================================================================
# Implementation summary
# ===========================================================================


@app.get(
    "/api/implementation/summary"
)
def implementation_summary():
    """Non-sensitive implementation metrics for the project dashboard."""

    zones = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    vendors = pd.read_csv(
        DATA
        / "vendor_training_registry.csv",
        dtype={
            "vendor_id":
                str,
        },
    )


    candidate = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    geom = _read_json(
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "audit_summary.json"
    )


    train = _read_json(
        ROOT
        / "reports"
        / "data_quality"
        / "training_data_metrics.json"
    )


    kmeans_meta = _read_json(
        ROOT
        / "reports"
        / "metrics"
        / "kmeans_run.json"
    )


    eval_path = (
        ROOT
        / "data"
        / "model_outputs"
        / "kmeans"
        / "k_evaluation.csv"
    )


    k_eval = (
        pd.read_csv(
            eval_path
        )
        .replace(
            {
                np.nan:
                    None,
            }
        )
        .to_dict(
            "records"
        )

        if eval_path.exists()

        else []
    )


    policy = (
        load_base_weight_policy()
    )


    expert_quality = _read_json(
        ROOT
        / "reports"
        / "expert_review"
        / "expert_label_quality.json"
    )


    model_comparison = _read_json(
        ROOT
        / "reports"
        / "suitability_model"
        / "model_comparison.json"
    )


    selected_model_path = (
        ROOT
        / "artifacts"
        / "models"
        / "selected_suitability_model.joblib"
    )


    shap_summary_path = (
        ROOT
        / "reports"
        / "suitability_model"
        / "shap_summary.json"
    )


    ahp_ready = (
        policy[
            "source"
        ]
        == "EXPERT_AHP"
    )


    expert_ready = (
        int(
            expert_quality.get(
                "ready_for_model_count",
                0,
            )
            or 0
        )
        > 0
    )


    supervised_ready = (
        selected_model_path.exists()
    )


    shap_ready = (
        shap_summary_path.exists()
    )


    return clean(
        {
            "counts": {
                "official_zones":
                    len(
                        zones
                    ),

                "registered_vendors":
                    len(
                        vendors
                    ),

                "candidate_reference_zones":
                    len(
                        candidate
                    ),

                "historical_pairs":
                    train.get(
                        "historical_proposed_pairs"
                    ),

                "usable_references":
                    geom.get(
                        "usable_reference_count"
                    ),

                "unique_reference_groups":
                    geom.get(
                        "unique_reference_groups"
                    ),

                "shared_reference_groups":
                    geom.get(
                        "shared_reference_groups"
                    ),
            },

            "kmeans": {
                "selected_k":
                    kmeans_meta.get(
                        "selected_k",
                        2,
                    ),

                "training_rows":
                    kmeans_meta.get(
                        "training_rows"
                    ),

                "variant":
                    kmeans_meta.get(
                        "variant"
                    ),

                "evaluation":
                    k_eval,
            },

            "pipeline": [
                {
                    "stage":
                        "01",

                    "name":
                        "Data validation",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Schema, IDs, joins and "
                            "source consistency"
                        ),
                },
                {
                    "stage":
                        "02",

                    "name":
                        "GIS feature engineering",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Fixed-radius environmental "
                            "features"
                        ),
                },
                {
                    "stage":
                        "03",

                    "name":
                        "Vendor-zone evidence",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Historical pair registry "
                            "and candidate snapshot"
                        ),
                },
                {
                    "stage":
                        "04",

                    "name":
                        "Environmental clustering",

                    "status":
                        "complete",

                    "detail":
                        (
                            "K-Means environmental "
                            "profiling"
                        ),
                },
                {
                    "stage":
                        "05",

                    "name":
                        "Explainable recommendation",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Weighted MCDA with "
                            "factor-level explanation"
                        ),
                },
                {
                    "stage":
                        "06",

                    "name":
                        "MCDA robustness evaluation",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Weight sensitivity, Top-K "
                            "stability and rank correlation"
                        ),
                },
                {
                    "stage":
                        "07",

                    "name":
                        "Constrained allocation planning",

                    "status":
                        "complete",

                    "detail":
                        (
                            "Two-stage Goal Programming "
                            "with live capacity constraints"
                        ),
                },
                {
                    "stage":
                        "08",

                    "name":
                        "AHP expert calibration",

                    "status":
                        (
                            "complete"
                            if ahp_ready
                            else "awaiting_expert_input"
                        ),

                    "detail":
                        (
                            "Expert pairwise weighting "
                            "with consistency validation"
                        ),
                },
                {
                    "stage":
                        "09",

                    "name":
                        "Independent expert labels",

                    "status":
                        (
                            "ready"
                            if expert_ready
                            else "in_progress"
                        ),

                    "detail":
                        (
                            "Independent suitability "
                            "review and agreement analysis"
                        ),
                },
                {
                    "stage":
                        "10",

                    "name":
                        "Experimental supervised model",

                    "status":
                        (
                            "complete"
                            if supervised_ready
                            else "awaiting_labels_or_kaggle_training"
                        ),

                    "detail":
                        (
                            "Grouped RF/XGBoost "
                            "evaluation against expert labels"
                        ),
                },
                {
                    "stage":
                        "11",

                    "name":
                        "SHAP validation",

                    "status":
                        (
                            "complete"
                            if shap_ready
                            else "not_started"
                        ),

                    "detail":
                        (
                            "Experimental-model explanation "
                            "only; not MCDA explanation"
                        ),
                },
            ],

            "model": {
                "ranking_model":
                    "Weighted MCDA",

                "weight_source":
                    policy[
                        "source"
                    ],

                "environment_model":
                    (
                        "K-Means environmental profiling"
                    ),

                "allocation_optimizer":
                    (
                        "Two-stage Goal Programming MILP"
                    ),

                "explainability":
                    (
                        "Exact MCDA weighted factor "
                        "contributions"
                    ),

                "experimental_supervised_model":
                    model_comparison.get(
                        "selected_model"
                    ),

                "supervised_model_in_production":
                    False,

                "shap_used_in_mcda":
                    False,

                "shap_artifact_available":
                    shap_ready,
            },
        }
    )


# ===========================================================================
# Official zone catalogue
# ===========================================================================


@app.get(
    "/api/official-zones"
)
def official_zones(
    division: str = "",
    zone_type: str = "",
    limit: int = Query(
        308,
        ge=1,
        le=500,
    ),
):

    zones = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    if division:

        zones = zones.loc[
            zones.division.eq(
                division
            )
        ]


    if zone_type:

        zones = zones.loc[
            zones.zone_type.eq(
                zone_type
            )
        ]


    audit_path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "zone_reference_audit.csv"
    )


    if audit_path.exists():

        audit = pd.read_csv(
            audit_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        columns = [
            column

            for column
            in [
                "zone_id",
                "reference_group_id",
                "shared_reference_group_size",
                "shared_reference",
                "reference_audit_status",
            ]

            if column
            in audit.columns
        ]


        zones = zones.merge(
            audit[
                columns
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    cluster_path = (
        ROOT
        / "data"
        / "model_outputs"
        / "kmeans"
        / "zones_with_clusters.csv"
    )


    if cluster_path.exists():

        clusters = pd.read_csv(
            cluster_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        if (
            "cluster"
            in clusters.columns
        ):

            zones = zones.merge(
                clusters[
                    [
                        "zone_id",
                        "cluster",
                    ]
                ].rename(
                    columns={
                        "cluster":
                            "environment_cluster",
                    }
                ),
                on="zone_id",
                how="left",
                validate="one_to_one",
            )


    fields = [
        column

        for column
        in [
            "zone_id",
            "division",
            "zone_type",
            "official_description",
            "capacity",
            "category",
            "environment_cluster",
            "reference_group_id",
            "shared_reference_group_size",
            "shared_reference",
            "reference_audit_status",
        ]

        if column
        in zones.columns
    ]


    records = [
        clean(
            row
        )

        for row
        in (
            zones[
                fields
            ]
            .head(
                limit
            )
            .to_dict(
                "records"
            )
        )
    ]


    return {
        "zones":
            records,

        "count":
            int(
                min(
                    len(
                        zones
                    ),
                    limit,
                )
            ),

        "total_matching":
            int(
                len(
                    zones
                )
            ),
    }


@app.get(
    "/api/catalog"
)
def catalog(
    zone_type: str = "",
    division: str = "",
    q: str = "",
    limit: int = 308,
):
    """Official records only; geometry/live state remain separate."""

    path = (
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv"
    )


    data = pd.read_csv(
        path,
        dtype={
            "zone_id":
                str,
        },
    )


    if zone_type:

        data = data.loc[
            data.zone_type.eq(
                zone_type
            )
        ]


    if division:

        data = data.loc[
            data.division.eq(
                division
            )
        ]


    if q:

        words = q.strip()


        data = data.loc[
            data.zone_id.str.contains(
                words,
                case=False,
                na=False,
                regex=False,
            )
            | data[
                "official_description"
            ].str.contains(
                words,
                case=False,
                na=False,
                regex=False,
            )
        ]


    columns = [
        "zone_id",
        "division",
        "zone_type",
        "official_description",
        "capacity",
        "category",
    ]


    safe_limit = max(
        1,
        min(
            limit,
            308,
        ),
    )


    return {
        "total":
            len(
                data
            ),

        "zones":
            clean(
                data[
                    columns
                ]
                .head(
                    safe_limit
                )
                .to_dict(
                    "records"
                )
            ),
    }


# ===========================================================================
# Project overview
# ===========================================================================


@app.get(
    "/api/overview"
)
def overview():

    master = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv"
    )


    vendors = pd.read_csv(
        DATA
        / "vendor_training_registry.csv"
    )


    features = pd.read_csv(
        DATA
        / "zone_features.csv"
    )


    groups = (
        master[
            "zone_type"
        ]
        .value_counts()
    )


    audit_path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "audit_summary.json"
    )


    audit_data = (
        _read_json(
            audit_path
        )
    )


    policy = (
        load_base_weight_policy()
    )


    return clean(
        {
            "official_zones":
                len(
                    master
                ),

            "vendor_records":
                len(
                    vendors
                ),

            "reference_ready":
                int(
                    features[
                        "geometry_usable_for_reference_model"
                    ]
                    .astype(str)
                    .str.lower()
                    .isin(
                        [
                            "true",
                            "1",
                            "yes",
                        ]
                    )
                    .sum()
                ),

            "zone_types":
                groups.to_dict(),

            "reference_groups":
                audit_data.get(
                    "unique_reference_groups"
                ),

            "shared_reference_zones":
                audit_data.get(
                    "zones_in_shared_reference_groups"
                ),

            "model": {
                "clustering":
                    "K-Means environmental profiling",

                "ranking":
                    "Weighted MCDA",

                "weight_source":
                    policy[
                        "source"
                    ],

                "allocation":
                    (
                        "Goal Programming advisory optimizer"
                    ),

                "supervised":
                    (
                        "Independent expert-label experiment; "
                        "not used in production ranking"
                    ),
            },
        }
    )


# ===========================================================================
# Expert-review summary
# ===========================================================================


@app.get(
    "/api/review-summary"
)
def review_summary():

    folder = (
        ROOT
        / "reports"
        / "expert_review"
    )


    labels_path = (
        folder
        / "expert_labels.csv"
    )


    queue_path = (
        folder
        / "review_queue.csv"
    )


    quality_path = (
        folder
        / "expert_label_quality.json"
    )


    if not queue_path.exists():

        return {
            "queue_count":
                0,

            "judgment_count":
                0,

            "reviewer_count":
                0,

            "rated_count":
                0,

            "abstained_count":
                0,

            "site_verification_count":
                0,

            "ready_for_model_count":
                0,
        }


    queue = pd.read_csv(
        queue_path
    )


    if not labels_path.exists():

        return {
            "queue_count":
                len(
                    queue
                ),

            "judgment_count":
                0,

            "reviewer_count":
                0,

            "rated_count":
                0,

            "abstained_count":
                0,

            "site_verification_count":
                0,

            "ready_for_model_count":
                0,
        }


    labels = pd.read_csv(
        labels_path,
        dtype=str,
    ).fillna("")


    sufficient = (
        labels[
            "recommendation"
        ].eq(
            "Sufficient evidence to rate"
        )

        if (
            "recommendation"
            in labels.columns
        )

        else labels[
            "relevance"
        ].ne("")
    )


    abstained = (
        labels[
            "recommendation"
        ].eq(
            "Insufficient evidence / abstain"
        )

        if (
            "recommendation"
            in labels.columns
        )

        else ~sufficient
    )


    site_verification = (
        labels[
            "recommendation"
        ].eq(
            "Requires site verification"
        )

        if (
            "recommendation"
            in labels.columns
        )

        else pd.Series(
            False,
            index=labels.index,
        )
    )


    quality = _read_json(
        quality_path
    )


    return {
        "queue_count":
            len(
                queue
            ),

        "judgment_count":
            len(
                labels
            ),

        "reviewer_count":
            int(
                labels[
                    "reviewer_id"
                ].nunique()
            ),

        "rated_count":
            int(
                sufficient.sum()
            ),

        "abstained_count":
            int(
                abstained.sum()
            ),

        "site_verification_count":
            int(
                site_verification.sum()
            ),

        "ready_for_model_count":
            int(
                quality.get(
                    "ready_for_model_count",
                    0,
                )
                or 0
            ),

        "weighted_quadratic_kappa":
            (
                quality
                .get(
                    "agreement_summary",
                    {},
                )
                .get(
                    "weighted_mean_quadratic_kappa"
                )
            ),
    }