"""Existing API validation contracts, extracted without field changes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, StrictBool

class PilotSlotUpdate(BaseModel):
    status: Literal["AVAILABLE", "RESERVED", "OCCUPIED", "BLOCKED"]
    assigned_vendor_id: str | None = Field(default=None, max_length=100)
    expected_updated_at: str = Field(min_length=1, max_length=100)

class PilotGeometryPreview(BaseModel):
    config: dict = Field(default_factory=dict)
    obstructions: list[dict] | None = Field(default=None, max_length=100)

class PilotGeometrySave(BaseModel):
    layout: dict
    review_confirmed: bool = False

class PilotGeometryEdit(BaseModel):
    layout: dict
    poses: dict = Field(default_factory=dict)

class PilotRouteRequest(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)

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
