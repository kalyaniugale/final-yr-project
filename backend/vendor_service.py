"""Unified vendor profiles across operational and historical data.

Historical recommendation data is non-PII and always required.

The optional historical identity CSV may contain privacy-restricted fields
such as vendor names. The application must continue functioning when that
private source is not deployed.

No plaintext phone numbers or authentication credentials are exposed from
this module.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .database import (
        DATABASE_PATH,
        PREFERRED_LANGUAGES,
        PRIORITY_PROFILES,
        OperationalNotFoundError,
        OperationalValidationError,
        create_operational_vendor,
        get_operational_vendor,
        save_operational_vendor_profile,
    )

    from .mcda_engine import (
        CATEGORIES,
        DATA,
    )

except ImportError:

    from database import (
        DATABASE_PATH,
        PREFERRED_LANGUAGES,
        PRIORITY_PROFILES,
        OperationalNotFoundError,
        OperationalValidationError,
        create_operational_vendor,
        get_operational_vendor,
        save_operational_vendor_profile,
    )

    from mcda_engine import (
        CATEGORIES,
        DATA,
    )


# ---------------------------------------------------------------------------
# Source files
# ---------------------------------------------------------------------------

HISTORICAL_VENDOR_PATH = (
    DATA
    / "vendor_training_registry.csv"
)

# Optional privacy-restricted source.
#
# This file is intentionally allowed to be absent in Git/deployment builds.
HISTORICAL_IDENTITY_PATH = (
    DATA.parent
    / "raw"
    / "nmc"
    / "vendors.csv"
)

CANDIDATE_ZONE_PATH = (
    DATA
    / "candidate_zone_snapshot.csv"
)


EDITABLE_PROFILE_FIELDS = {
    "full_name",
    "business_name",
    "business_category",
    "preferred_division",
    "preferred_locality",
    "priority_profile",
    "parking_preference",
    "transport_preference",
    "market_preference",
    "preferred_language",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _optional_text(
    value: Any,
) -> str | None:
    """Normalize optional text without inventing values."""

    if value is None:
        return None

    text = str(value).strip()

    return text or None


# ---------------------------------------------------------------------------
# Historical source loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _historical_identity_map(
    path: str = str(
        HISTORICAL_IDENTITY_PATH
    ),
) -> dict[
    str,
    dict[
        str,
        str | None,
    ],
]:
    """Load the optional historical identity overlay.

    The privacy-restricted source is deliberately optional.

    If it is not deployed, recommendation, allocation and authentication
    workflows must continue using the non-PII vendor registry.

    If the source *is* present but malformed, fail explicitly because silently
    accepting corrupted identity information would be unsafe.
    """

    source_path = Path(
        path
    )


    if not source_path.exists():
        return {}


    if not source_path.is_file():

        raise OperationalValidationError(
            "Historical identity source "
            "exists but is not a file"
        )


    with source_path.open(
        newline="",
        encoding="utf-8-sig",
    ) as source:

        reader = csv.DictReader(
            source
        )


        fieldnames = set(
            reader.fieldnames
            or []
        )


        if (
            "vendor_id"
            not in fieldnames
        ):

            raise OperationalValidationError(
                "Historical identity source "
                "is missing vendor_id"
            )


        identities: dict[
            str,
            dict[
                str,
                str | None,
            ],
        ] = {}


        for row in reader:

            vendor_id = (
                row.get(
                    "vendor_id"
                )
                or ""
            ).strip()


            if not vendor_id:
                continue


            identities[
                vendor_id
            ] = {

                "full_name":
                    _optional_text(
                        row.get(
                            "vendor_name_english"
                        )
                    ),

                # Historical source contains business type,
                # but does not provide a distinct business/stall name.
                "business_name":
                    None,
            }


        return identities


@lru_cache(maxsize=4)
def _historical_vendor_map(
    path: str = str(
        HISTORICAL_VENDOR_PATH
    ),
) -> dict[
    str,
    dict[
        str,
        str | None,
    ],
]:
    """Load the non-PII historical recommendation registry."""

    source_path = Path(
        path
    )


    if not source_path.exists():

        raise OperationalValidationError(
            "Historical vendor registry "
            f"is unavailable: {source_path}"
        )


    with source_path.open(
        newline="",
        encoding="utf-8-sig",
    ) as source:

        reader = csv.DictReader(
            source
        )


        fieldnames = set(
            reader.fieldnames
            or []
        )


        required = {
            "vendor_id",
            "business_category",
            "vendor_division",
        }


        missing = (
            required
            - fieldnames
        )


        if missing:

            raise OperationalValidationError(
                "Historical vendor registry "
                "is missing columns: "
                + ", ".join(
                    sorted(
                        missing
                    )
                )
            )


        vendors: dict[
            str,
            dict[
                str,
                str | None,
            ],
        ] = {}


        for row in reader:

            vendor_id = (
                row.get(
                    "vendor_id"
                )
                or ""
            ).strip()


            if not vendor_id:
                continue


            category = (
                row.get(
                    "business_category"
                )
                or ""
            ).strip()


            division = _optional_text(
                row.get(
                    "vendor_division"
                )
            )


            vendors[
                vendor_id
            ] = {

                "business_category":
                    category,

                "preferred_division":
                    division,
            }


        return vendors


@lru_cache(maxsize=4)
def valid_divisions(
    path: str = str(
        CANDIDATE_ZONE_PATH
    ),
) -> frozenset[str]:
    """Return currently supported municipal divisions."""

    source_path = Path(
        path
    )


    if not source_path.exists():

        raise OperationalValidationError(
            "Candidate-zone snapshot "
            f"is unavailable: {source_path}"
        )


    with source_path.open(
        newline="",
        encoding="utf-8-sig",
    ) as source:

        reader = csv.DictReader(
            source
        )


        fieldnames = set(
            reader.fieldnames
            or []
        )


        if (
            "zone_division"
            not in fieldnames
        ):

            raise OperationalValidationError(
                "Candidate-zone snapshot "
                "is missing zone_division"
            )


        return frozenset(

            division

            for row in reader

            if (
                division := _optional_text(
                    row.get(
                        "zone_division"
                    )
                )
            )

            and division
            != "Citywide"
        )


# ---------------------------------------------------------------------------
# Profile normalization
# ---------------------------------------------------------------------------


def _normalize_operational(
    row,
) -> dict[
    str,
    Any,
]:
    """Convert an operational SQLite row into the public profile contract."""

    return {

        "vendor_id":
            row[
                "vendor_id"
            ],

        "application_vendor_id":
            row[
                "application_vendor_id"
            ],

        "vendor_type":
            row[
                "vendor_type"
            ],

        "full_name":
            row[
                "full_name"
            ],

        "business_name":
            row[
                "business_name"
            ],

        "business_category":
            row[
                "business_category"
            ],

        "preferred_division":
            row[
                "preferred_division"
            ],

        "preferred_locality":
            row[
                "preferred_locality"
            ],

        "priority_profile":
            row[
                "priority_profile"
            ],

        "parking_preference":
            bool(
                row[
                    "parking_preference"
                ]
            ),

        "transport_preference":
            bool(
                row[
                    "transport_preference"
                ]
            ),

        "market_preference":
            bool(
                row[
                    "market_preference"
                ]
            ),

        "preferred_language":
            row[
                "preferred_language"
            ],

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
    }


def _historical_profile(
    vendor_id: str,
    historical_path: str | Path,
    identity_path: str | Path = (
        HISTORICAL_IDENTITY_PATH
    ),
) -> dict[
    str,
    Any,
] | None:
    """Build a historical vendor profile.

    Non-PII business/division information comes from the model registry.

    Name information is overlaid only when the optional private identity source
    is available.
    """

    source = (
        _historical_vendor_map(

            str(
                Path(
                    historical_path
                ).resolve()
            )

        ).get(
            vendor_id
        )
    )


    if source is None:
        return None


    identity = (
        _historical_identity_map(

            str(
                Path(
                    identity_path
                ).resolve()
            )

        ).get(
            vendor_id,
            {},
        )
    )


    return {

        "vendor_id":
            vendor_id,

        "application_vendor_id":
            None,

        "vendor_type":
            "EXISTING_IMPORTED",

        "full_name":
            identity.get(
                "full_name"
            ),

        "business_name":
            identity.get(
                "business_name"
            ),

        "business_category":
            source[
                "business_category"
            ],

        "preferred_division":
            source[
                "preferred_division"
            ],

        "preferred_locality":
            None,

        "priority_profile":
            "BALANCED",

        "parking_preference":
            False,

        "transport_preference":
            False,

        "market_preference":
            False,

        "preferred_language":
            "en",

        "status":
            "ACTIVE",

        "created_at":
            None,

        "updated_at":
            None,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_vendor_profile(
    values: dict[
        str,
        Any,
    ],
    *,
    partial: bool = False,
) -> None:
    """Validate mutable operational profile fields."""

    for field, maximum in (
        (
            "full_name",
            120,
        ),
        (
            "business_name",
            120,
        ),
    ):

        if (
            field in values
            and values[
                field
            ]
            is not None
        ):

            value = (

                values[
                    field
                ].strip()

                if isinstance(
                    values[
                        field
                    ],
                    str,
                )

                else ""
            )


            if not value:

                raise OperationalValidationError(
                    f"{field} must not be empty"
                )


            if (
                len(
                    value
                )
                > maximum
            ):

                raise OperationalValidationError(
                    f"{field} must be at most "
                    f"{maximum} characters"
                )


            values[
                field
            ] = value


    if (
        not partial
        or "business_category"
        in values
    ):

        category = (
            values.get(
                "business_category"
            )
        )


        if (
            category
            not in CATEGORIES
        ):

            raise OperationalValidationError(
                "business_category must be one of: "
                + ", ".join(
                    CATEGORIES
                )
            )


    if (
        "preferred_division"
        in values

        and values[
            "preferred_division"
        ]
        is not None
    ):

        if (
            values[
                "preferred_division"
            ]
            not in valid_divisions()
        ):

            raise OperationalValidationError(
                "Unknown preferred_division"
            )


    if (

        "priority_profile"
        in values

        and values[
            "priority_profile"
        ]
        not in PRIORITY_PROFILES
    ):

        raise OperationalValidationError(
            "priority_profile must be one of: "
            + ", ".join(
                PRIORITY_PROFILES
            )
        )


    if (

        "preferred_language"
        in values

        and values[
            "preferred_language"
        ]
        not in PREFERRED_LANGUAGES
    ):

        raise OperationalValidationError(
            "preferred_language must be one of: "
            + ", ".join(
                PREFERRED_LANGUAGES
            )
        )


    for field in (
        "parking_preference",
        "transport_preference",
        "market_preference",
    ):

        if (

            field in values

            and not isinstance(
                values[
                    field
                ],
                bool,
            )
        ):

            raise OperationalValidationError(
                f"{field} must be a boolean"
            )


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


def get_vendor_profile(
    vendor_id: str,
    database_path: str | Path = (
        DATABASE_PATH
    ),
    historical_path: str | Path = (
        HISTORICAL_VENDOR_PATH
    ),
    identity_path: str | Path = (
        HISTORICAL_IDENTITY_PATH
    ),
) -> dict[
    str,
    Any,
] | None:
    """Resolve operational vendor first, then historical source."""

    operational = (
        get_operational_vendor(
            vendor_id,
            database_path,
        )
    )


    if (
        operational
        is not None
    ):

        return (
            _normalize_operational(
                operational
            )
        )


    return _historical_profile(

        vendor_id,

        historical_path,

        identity_path,
    )


def register_vendor(
    values: dict[
        str,
        Any,
    ],
    database_path: str | Path = (
        DATABASE_PATH
    ),
) -> dict[
    str,
    Any,
]:
    """Register a new operational vendor."""

    validate_vendor_profile(
        values
    )


    return _normalize_operational(

        create_operational_vendor(
            values,
            database_path,
        )
    )


def update_vendor_profile(
    vendor_id: str,
    updates: dict[
        str,
        Any,
    ],
    database_path: str | Path = (
        DATABASE_PATH
    ),
    historical_path: str | Path = (
        HISTORICAL_VENDOR_PATH
    ),
    identity_path: str | Path = (
        HISTORICAL_IDENTITY_PATH
    ),
) -> dict[
    str,
    Any,
]:
    """Create/update the operational overlay for a vendor profile."""

    if not updates:

        raise OperationalValidationError(
            "At least one preference field "
            "must be supplied"
        )


    unknown = (
        set(
            updates
        )
        - EDITABLE_PROFILE_FIELDS
    )


    if unknown:

        raise OperationalValidationError(
            "Fields cannot be updated: "
            + ", ".join(
                sorted(
                    unknown
                )
            )
        )


    validate_vendor_profile(
        updates,
        partial=True,
    )


    current = get_vendor_profile(

        vendor_id,

        database_path,

        historical_path,

        identity_path,
    )


    if current is None:

        raise OperationalNotFoundError(
            f"Unknown vendor_id: {vendor_id}"
        )


    merged = {
        **current,
        **updates,
    }


    row = (
        save_operational_vendor_profile(

            vendor_id,

            current[
                "vendor_type"
            ],

            merged,

            database_path,
        )
    )


    return _normalize_operational(
        row
    )


# ---------------------------------------------------------------------------
# Test / maintenance support
# ---------------------------------------------------------------------------


def clear_vendor_service_caches() -> None:
    """Clear immutable-source caches.

    Useful after explicitly mounting/replacing research source files during
    development or controlled test setup.
    """

    _historical_identity_map.cache_clear()

    _historical_vendor_map.cache_clear()

    valid_divisions.cache_clear()