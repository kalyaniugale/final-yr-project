"""Transparent GIS + MCDA recommendation engine.

The engine ranks operationally eligible vending-zone references. It is a
decision-support model, not a trained success predictor and not an allocation
authority.

Public entry points
-------------------
load(...)
    Load candidate-zone and historical-vendor evidence.

score_candidates(...)
    Score every eligible candidate. This is intentionally reusable by the
    evaluation and allocation-optimisation layers.

rank_candidates(...)
    Apply deterministic local-first Top-N ranking to an already scored table.

recommend(...)
    Backward-compatible convenience API used by FastAPI and the CLI.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

try:
    from .database import DATABASE_PATH, get_live_zone_status_map
    from .decision_policy import (
        FACTOR_ORDER,
        RESEARCH_BASELINE_WEIGHTS,
        derive_mcda_weights,
        normalize_weights,
    )
except ImportError:  # Supports direct script execution.
    from database import DATABASE_PATH, get_live_zone_status_map
    from decision_policy import (
        FACTOR_ORDER,
        RESEARCH_BASELINE_WEIGHTS,
        derive_mcda_weights,
        normalize_weights,
    )


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw" / "nmc"
OUT = ROOT / "data" / "outputs"


CATEGORIES = [
    "vegetable_fruit",
    "food",
    "clothing",
    "flower",
    "general_goods",
    "other",
]


# Backward-compatible public constant used by the API and current tests.
#
# Later, reviewed AHP weights can replace these baseline values through
# decision_policy without rewriting this recommendation engine.
WEIGHTS = dict(RESEARCH_BASELINE_WEIGHTS)


LIVE_STATUS_ALLOWED = {
    "OPEN",
    "FULL",
    "CLOSED",
    "SUSPENDED",
    "NO_VENDING",
    "RESTRICTED",
}


BLOCKED_LIVE_STATUSES = {
    "FULL",
    "CLOSED",
    "SUSPENDED",
    "NO_VENDING",
    "RESTRICTED",
}


LIVE_VERIFICATION_MAX_AGE = pd.Timedelta(days=7)


# ---------------------------------------------------------------------------
# Transparent scoring parameters
# ---------------------------------------------------------------------------
#
# These are deterministic policy/scaling parameters.
# They are NOT trained coefficients.
#
# The later sensitivity-analysis module will test how strongly recommendation
# rankings depend on these choices.
# ---------------------------------------------------------------------------

COMMERCIAL_SCALES = {
    "commercial_poi_count_250m": 12.0,
    "market_poi_count_500m": 4.0,
    "food_poi_count_250m": 8.0,
}


ACCESS_SCALES = {
    "distance_to_major_road_m": 400.0,
    "distance_to_bus_access_m": 1000.0,
    "pedestrian_road_density_250m_per_km2": 5000.0,
}


FACILITY_SCALES = {
    "healthcare_count_500m": 15.0,
    "education_count_500m": 6.0,
    "toilet_count_500m": 3.0,
    "parking_count_500m": 4.0,
}


HISTORICAL_SHRINKAGE_STRENGTH = 20.0
HISTORICAL_EVIDENCE_SCALE = 50.0


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def clip(values):
    """Clip numeric values into the MCDA [0, 1] range."""
    return np.clip(
        values,
        0.0,
        1.0,
    )


def saturation(values, scale: float):
    """Diminishing-return transform for count/density features."""

    if scale <= 0:
        raise ValueError(
            "saturation scale must be positive"
        )

    return clip(
        np.log1p(
            np.maximum(
                values,
                0,
            )
        )
        / np.log1p(scale)
    )


def proximity(values, scale: float):
    """Convert distance to a score where shorter distance is better."""

    if scale <= 0:
        raise ValueError(
            "proximity scale must be positive"
        )

    return clip(
        np.exp(
            -np.maximum(
                values,
                0,
            )
            / scale
        )
    )


def num(values):
    """Safely convert pandas values to numeric form."""

    return pd.to_numeric(
        values,
        errors="coerce",
    )


def _feature(
    frame: pd.DataFrame,
    name: str,
) -> pd.Series:
    """Return numeric feature values.

    Missing source columns remain unknown rather than silently becoming zero.
    """

    if name in frame.columns:
        return num(
            frame[name]
        )

    return pd.Series(
        np.nan,
        index=frame.index,
        dtype=float,
    )


def _mean_available(
    parts: list[pd.Series],
) -> pd.Series:
    """Average available components while preserving all-missing rows."""

    return pd.concat(
        parts,
        axis=1,
    ).mean(
        axis=1,
        skipna=True,
    )


def _empty_scored(
    metadata: Mapping[str, object],
) -> pd.DataFrame:
    """Create an empty result while preserving recommendation metadata."""

    result = pd.DataFrame()

    result.attrs.update(
        metadata
    )

    return result


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def _required_live_columns(
    frame: pd.DataFrame,
    columns: set[str],
) -> list[str]:
    """Return live-status columns in deterministic order."""

    preferred = [
        "zone_id",
        "verified_available_capacity",
        "status",
        "verified_at",
        "verified_by",
    ]

    return [
        name
        for name in preferred
        if name in columns
        and name in frame.columns
    ]


def load(
    use_live_status: bool = False,
    database_path=None,
):
    """Load candidate-zone and historical-vendor evidence.

    Operational mode uses SQLite as the live status source.

    Static CSV live-status data remains supported for research compatibility.
    """

    zones = pd.read_csv(
        DATA / "candidate_zone_snapshot.csv",
        dtype={
            "zone_id": str,
        },
    )

    vendors = pd.read_csv(
        DATA / "vendor_training_registry.csv",
        dtype={
            "vendor_id": str,
        },
    )


    # IDs are critical join keys and must be unique.
    for frame, key in (
        (
            zones,
            "zone_id",
        ),
        (
            vendors,
            "vendor_id",
        ),
    ):

        if (
            frame[key].isna().any()
            or frame[key].duplicated().any()
        ):
            raise ValueError(
                f"Invalid or duplicate {key} values"
            )


    # -----------------------------------------------------------------------
    # Operational live data
    # -----------------------------------------------------------------------

    if use_live_status:

        live_map = get_live_zone_status_map(
            database_path
            or DATABASE_PATH
        )

        live = pd.DataFrame(
            live_map.values()
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
                "official_capacity":
                    "live_official_capacity",

                "status":
                    "live_status",

                "verified_at":
                    "live_verified_at",

                "verified_by":
                    "live_verified_by",

                "updated_at":
                    "live_updated_at",
            }
        )


        zones = zones.merge(
            live,
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


        # Preserve the existing API/output contract.
        zones[
            "official_capacity"
        ] = zones[
            "live_official_capacity"
        ]

        zones[
            "verified_available_capacity"
        ] = zones[
            "available_capacity"
        ]

        zones[
            "status"
        ] = zones[
            "live_status"
        ]

        zones[
            "verified_at"
        ] = zones[
            "live_verified_at"
        ]

        zones[
            "verified_by"
        ] = zones[
            "live_verified_by"
        ]


    # -----------------------------------------------------------------------
    # Optional research-mode CSV snapshot
    # -----------------------------------------------------------------------

    elif (
        RAW / "zone_live_status.csv"
    ).exists():

        path = (
            RAW
            / "zone_live_status.csv"
        )

        live = pd.read_csv(
            path,
            dtype={
                "zone_id": str,
            },
        ).fillna("")


        required = {
            "zone_id",
            "verified_available_capacity",
            "status",
            "verified_at",
            "verified_by",
        }


        if not required.issubset(
            live.columns
        ):
            raise ValueError(
                "Invalid live status schema"
            )


        if (
            live.zone_id.duplicated().any()
            or not live.zone_id.isin(
                zones.zone_id
            ).all()
        ):
            raise ValueError(
                "Invalid live status zone IDs"
            )


        statuses = (
            live.status
            .astype(str)
            .str.upper()
        )


        if not statuses.isin(
            LIVE_STATUS_ALLOWED
        ).all():

            raise ValueError(
                "Unknown live status; expected "
                "OPEN, FULL, CLOSED, SUSPENDED, "
                "NO_VENDING or RESTRICTED"
            )


        values = num(
            live[
                "verified_available_capacity"
            ]
        )


        if (
            values.lt(0).any()
            or values.isna().any()
        ):
            raise ValueError(
                "Live status records require "
                "nonnegative verified available capacity"
            )


        zones = zones.merge(
            live[
                _required_live_columns(
                    live,
                    required,
                )
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    else:

        for column in (
            "verified_available_capacity",
            "status",
            "verified_at",
            "verified_by",
        ):

            zones[
                column
            ] = pd.NA


    # -----------------------------------------------------------------------
    # Reference geometry quality audit
    # -----------------------------------------------------------------------

    audit = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "zone_reference_audit.csv"
    )


    if audit.exists():

        reference = pd.read_csv(
            audit,
            dtype={
                "zone_id": str,
            },
        )


        if reference.zone_id.duplicated().any():

            raise ValueError(
                "Duplicate zone IDs "
                "in reference audit"
            )


        columns = [
            "zone_id",
            "reference_group_id",
            "shared_reference_group_size",
            "shared_reference",
            "reference_warning",
        ]


        zones = zones.merge(
            reference[
                columns
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    else:

        zones[
            "reference_group_id"
        ] = pd.NA

        zones[
            "shared_reference_group_size"
        ] = pd.NA

        zones[
            "shared_reference"
        ] = False

        zones[
            "reference_warning"
        ] = (
            "Reference audit unavailable; "
            "exact site-level boundary not verified."
        )


    return (
        zones,
        vendors,
    )


# ---------------------------------------------------------------------------
# Vendor/request validation
# ---------------------------------------------------------------------------


def _resolve_vendor_context(
    vendors: pd.DataFrame,
    *,
    business: str,
    division: str,
    vendor_id: str,
):
    """Resolve inherited business/division for an existing vendor."""

    vendor_record = None


    if vendor_id:

        found = vendors.loc[
            vendors.vendor_id.eq(
                vendor_id
            )
        ]


        if len(found) != 1:

            raise ValueError(
                "Unknown vendor ID"
            )


        vendor_record = (
            found.iloc[0]
        )


        if business == "":

            business = str(
                vendor_record.business_category
            )


        if not division:

            division = str(
                vendor_record.vendor_division
            )


    return (
        business,
        division,
        vendor_record,
    )


def _validate_request(
    zones: pd.DataFrame,
    *,
    business: str,
    division: str,
):
    """Validate category and division against the current datasets."""

    if business not in CATEGORIES:

        raise ValueError(
            "Select a known business category"
        )


    valid_divisions = set(
        zones.loc[
            zones.zone_division.ne(
                "Citywide"
            ),
            "zone_division",
        ].dropna()
    )


    if (
        division
        and division not in valid_divisions
    ):

        raise ValueError(
            "Unknown division"
        )


# ---------------------------------------------------------------------------
# Candidate eligibility
# ---------------------------------------------------------------------------


def _eligible_reference_candidates(
    zones: pd.DataFrame,
) -> pd.DataFrame:
    """Return FREE zones with usable analytical reference geometry."""

    usable = (
        zones[
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
    )


    return zones.loc[
        zones.zone_type.eq(
            "FREE"
        )
        & usable
    ].copy()


def _apply_live_filter(
    zones: pd.DataFrame,
    *,
    use_live_status: bool,
    require_verified: bool,
) -> tuple[
    pd.DataFrame,
    dict[str, object],
]:
    """Apply operational eligibility filters.

    Missing operational rows are never interpreted as OPEN.

    An explicitly OPEN zone whose capacity is unknown may remain visible as a
    recommendation candidate, but is not considered verified availability.
    The allocation optimiser will later require known usable capacity.
    """

    zones = zones.copy()


    candidate_count_before_live_filter = len(
        zones
    )


    zones[
        "live_available"
    ] = num(
        zones[
            "verified_available_capacity"
        ]
    )


    if zones.live_available.lt(0).any():

        raise ValueError(
            "Negative verified available capacity"
        )


    zones[
        "live_status"
    ] = (
        zones[
            "status"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
    )


    zones[
        "capacity_known"
    ] = zones.live_available.notna()


    zones[
        "operationally_open"
    ] = zones.live_status.eq(
        "OPEN"
    )


    timestamps = pd.to_datetime(
        zones[
            "verified_at"
        ],
        errors="coerce",
        utc=True,
    )


    age = (
        pd.Timestamp.now(
            tz="UTC"
        )
        - timestamps
    )


    recent = (
        age.ge(
            pd.Timedelta(0)
        )
        & age.le(
            LIVE_VERIFICATION_MAX_AGE
        )
    )


    zones[
        "live_verified"
    ] = (
        zones.live_status.eq(
            "OPEN"
        )
        & zones.live_available.gt(
            0
        )
        & recent
        & zones[
            "verified_by"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )


    if use_live_status:

        # Missing operational rows are excluded because absence is not OPEN.
        #
        # An OPEN row whose capacity is unknown may still appear as a
        # recommendation, but it is not verified capacity and must never be
        # interpreted as an allocatable slot.

        zones = zones.loc[
            zones.live_status.eq(
                "OPEN"
            )
            & (
                zones.live_available.isna()
                | zones.live_available.gt(
                    0
                )
            )
        ]


    else:

        zones = zones.loc[
            ~zones.live_status.isin(
                BLOCKED_LIVE_STATUSES
            )
            & ~(
                zones.live_available.notna()
                & zones.live_available.le(
                    0
                )
            )
        ]


    candidate_count_after_live_filter = len(
        zones
    )


    if require_verified:

        zones = zones.loc[
            zones.live_verified
        ]


    metadata = {

        "candidate_count_before_live_filter":
            candidate_count_before_live_filter,

        "candidate_count_after_live_filter":
            candidate_count_after_live_filter,

        "candidate_count_after_verified_filter":
            len(zones),

        "live_filter_applied":
            bool(use_live_status),

        "require_verified":
            bool(require_verified),
    }


    return (
        zones.copy(),
        metadata,
    )


# ---------------------------------------------------------------------------
# Environmental MCDA factors
# ---------------------------------------------------------------------------


def _environment_factor_scores(
    zones: pd.DataFrame,
) -> dict[str, pd.Series]:
    """Create commercial, accessibility and facility factor scores."""


    commercial = _mean_available(
        [

            saturation(
                _feature(
                    zones,
                    "commercial_poi_count_250m",
                ),
                COMMERCIAL_SCALES[
                    "commercial_poi_count_250m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "market_poi_count_500m",
                ),
                COMMERCIAL_SCALES[
                    "market_poi_count_500m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "food_poi_count_250m",
                ),
                COMMERCIAL_SCALES[
                    "food_poi_count_250m"
                ],
            ),
        ]
    )


    access = _mean_available(
        [

            proximity(
                _feature(
                    zones,
                    "distance_to_major_road_m",
                ),
                ACCESS_SCALES[
                    "distance_to_major_road_m"
                ],
            ),

            proximity(
                _feature(
                    zones,
                    "distance_to_bus_access_m",
                ),
                ACCESS_SCALES[
                    "distance_to_bus_access_m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "pedestrian_road_density_250m_per_km2",
                ),
                ACCESS_SCALES[
                    "pedestrian_road_density_250m_per_km2"
                ],
            ),
        ]
    )


    facilities = _mean_available(
        [

            saturation(
                _feature(
                    zones,
                    "healthcare_count_500m",
                ),
                FACILITY_SCALES[
                    "healthcare_count_500m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "education_count_500m",
                ),
                FACILITY_SCALES[
                    "education_count_500m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "toilet_count_500m",
                ),
                FACILITY_SCALES[
                    "toilet_count_500m"
                ],
            ),

            saturation(
                _feature(
                    zones,
                    "parking_count_500m",
                ),
                FACILITY_SCALES[
                    "parking_count_500m"
                ],
            ),
        ]
    )


    return {

        "commercial":
            commercial,

        "access":
            access,

        "facilities":
            facilities,
    }


# ---------------------------------------------------------------------------
# Historical evidence factors
# ---------------------------------------------------------------------------


def _historical_factor_scores(
    zones: pd.DataFrame,
    vendors: pd.DataFrame,
    *,
    business: str,
    vendor_id: str,
    vendor_record,
) -> dict[str, pd.Series]:
    """Calculate historical compatibility and evidence-density scores.

    For an existing historical vendor, the vendor's entire recorded location
    group is removed from its own evidence to avoid self-reinforcement.
    """

    evidence = vendors.loc[
        vendors.match_status.eq(
            "text_association"
        )
        & vendors.proposed_zone_id.notna()
        & vendors.proposed_zone_id.ne("")
    ].copy()


    # Leave-group-out evidence for existing historical vendor.
    if (
        vendor_id
        and vendor_record is not None
    ):

        group = (
            vendor_record.location_group_id
        )


        if (
            pd.notna(group)
            and str(group).strip()
        ):

            evidence = evidence.loc[
                evidence.location_group_id.ne(
                    group
                )
            ]


        else:

            evidence = evidence.loc[
                evidence.vendor_id.ne(
                    vendor_id
                )
            ]


    category_counts = (
        evidence.business_category
        .value_counts()
    )


    total = int(
        category_counts.sum()
    )


    prior = (
        float(
            category_counts.get(
                business,
                0,
            )
            / total
        )
        if total
        else 0.0
    )


    grouped = evidence.groupby(
        "proposed_zone_id"
    )


    n_by = grouped.size()


    same_by = (
        evidence.loc[
            evidence.business_category.eq(
                business
            )
        ]
        .groupby(
            "proposed_zone_id"
        )
        .size()
    )


    zones[
        "historical_zone_count"
    ] = (
        zones.zone_id.map(
            n_by
        )
        .fillna(0)
    )


    zones[
        "historical_same_business_count"
    ] = (
        zones.zone_id.map(
            same_by
        )
        .fillna(0)
    )


    zones[
        "citywide_business_share"
    ] = prior


    # Shrink small-sample location proportions toward the city-wide prior.
    zones[
        "smoothed_business_share"
    ] = (

        zones[
            "historical_same_business_count"
        ]

        + HISTORICAL_SHRINKAGE_STRENGTH
        * prior

    ) / (

        zones[
            "historical_zone_count"
        ]

        + HISTORICAL_SHRINKAGE_STRENGTH

    )


    zones[
        "historical_lift"
    ] = (

        zones[
            "smoothed_business_share"
        ]
        / prior

        if prior > 0

        else np.nan
    )


    evidence_count = num(
        zones[
            "historical_zone_count"
        ]
    ).fillna(0)


    same_business = num(
        zones[
            "historical_same_business_count"
        ]
    ).fillna(0)


    prior_series = num(
        zones[
            "citywide_business_share"
        ]
    )


    lift = num(
        zones[
            "historical_lift"
        ]
    )


    # Historical lift represents category association only.
    #
    # It must not be interpreted as:
    # - demand,
    # - profit,
    # - footfall,
    # - present occupancy,
    # - or predicted business success.

    business_score = clip(

        np.log1p(
            lift.clip(
                lower=0
            )
        )

        / np.log(3)

    )


    # Weak historical evidence is pulled toward a neutral score.
    reliability = (

        evidence_count

        / (
            evidence_count
            + HISTORICAL_SHRINKAGE_STRENGTH
        )
    )


    business_score = (

        0.5

        + (
            business_score
            - 0.5
        )
        * reliability
    )


    business_score = (
        business_score.where(
            prior_series.gt(0),
            np.nan,
        )
    )


    history_score = saturation(
        evidence_count,
        HISTORICAL_EVIDENCE_SCALE,
    )


    zones[
        "evidence_count"
    ] = evidence_count


    zones[
        "same_business_count"
    ] = same_business


    zones[
        "evidence_method"
    ] = (

        "TEXT_ASSOCIATIONS_LEAVE_LOCATION_GROUP_OUT"

        if vendor_id

        else "TEXT_ASSOCIATIONS_FULL_REFERENCE"
    )


    return {

        "business":
            business_score,

        "historical":
            history_score,
    }


# ---------------------------------------------------------------------------
# Vendor preference factor
# ---------------------------------------------------------------------------


def _preference_score(
    zones: pd.DataFrame,
    division: str,
) -> pd.Series:
    """Score preferred-division matching.

    A missing division preference receives the existing neutral score of 0.5
    for every candidate. Because every zone receives the same value, this does
    not change ranking and maintains backward-compatible score semantics.
    """

    if not division:

        return pd.Series(
            0.5,
            index=zones.index,
            dtype=float,
        )


    return (
        zones.zone_division.eq(
            division
        )
        .astype(float)
    )


# ---------------------------------------------------------------------------
# MCDA aggregation
# ---------------------------------------------------------------------------


def _calculate_mcda(
    zones: pd.DataFrame,
    components: Mapping[
        str,
        pd.Series,
    ],
    weights: Mapping[
        str,
        float,
    ],
) -> pd.DataFrame:
    """Combine factor scores using missing-data-aware weighted MCDA."""

    zones = zones.copy()


    numerator = pd.Series(
        0.0,
        index=zones.index,
    )


    denominator = pd.Series(
        0.0,
        index=zones.index,
    )


    for name in FACTOR_ORDER:

        series = (
            components[name]
        )


        zones[
            f"{name}_score"
        ] = series


        valid = (
            series.notna()
        )


        numerator = numerator.add(

            series.fillna(
                0.0
            )

            * weights[name]

        )


        denominator = denominator.add(

            valid.astype(float)

            * weights[name]

        )


    # Missing factors are omitted through denominator renormalisation.
    zones[
        "score"
    ] = (

        100.0

        * numerator

        / denominator.replace(
            0.0,
            np.nan,
        )
    )


    # Coverage is the sum of available criterion weights.
    zones[
        "score_coverage"
    ] = denominator


    # Contributions are normalized using the same available-weight
    # denominator so their sum equals the final score.

    for name in FACTOR_ORDER:

        series = (
            components[name]
        )


        zones[
            f"{name}_contribution"
        ] = (

            100.0

            * series.fillna(
                0.0
            )

            * weights[name]

            / denominator.replace(
                0.0,
                np.nan,
            )
        )


    return zones


# ---------------------------------------------------------------------------
# Full candidate scoring
# ---------------------------------------------------------------------------


def score_candidates(
    business: str,
    division: str = "",
    vendor_id: str = "",
    exclude_zone: str = "",
    require_verified: bool = False,
    use_live_status: bool = False,
    database_path=None,
    factor_weights: Mapping[
        str,
        float,
    ]
    | None = None,
) -> pd.DataFrame:
    """Score every eligible zone for one vendor/request context.

    Unlike ``recommend()``, this function does not truncate the candidates.

    It will be reused by:

    - sensitivity analysis,
    - expert validation,
    - Goal Programming,
    - allocation optimisation,
    - and later model comparison.
    """

    zones, vendors = load(
        use_live_status=(
            use_live_status
        ),
        database_path=(
            database_path
        ),
    )


    weights = normalize_weights(

        WEIGHTS

        if factor_weights is None

        else factor_weights
    )


    (
        business,
        division,
        vendor_record,

    ) = _resolve_vendor_context(

        vendors,

        business=business,

        division=division,

        vendor_id=vendor_id,
    )


    _validate_request(

        zones,

        business=business,

        division=division,
    )


    # Only legally/model-eligible FREE analytical references.
    zones = (
        _eligible_reference_candidates(
            zones
        )
    )


    if exclude_zone:

        if exclude_zone not in set(
            zones.zone_id
        ):

            raise ValueError(
                "Excluded zone is not a valid "
                "FREE reference candidate"
            )


        zones = zones.loc[
            zones.zone_id.ne(
                exclude_zone
            )
        ].copy()


    zones, metadata = (
        _apply_live_filter(

            zones,

            use_live_status=(
                use_live_status
            ),

            require_verified=(
                require_verified
            ),
        )
    )


    metadata.update(
        {

            "effective_factor_weights":
                dict(weights),

            "business":
                business,

            "division":
                division,

            "vendor_id":
                vendor_id,

            "exclude_zone":
                exclude_zone,
        }
    )


    if zones.empty:

        return _empty_scored(
            metadata
        )


    zones = zones.reset_index(
        drop=True
    )


    zones[
        "candidate_status"
    ] = np.where(

        zones.live_verified,

        "VERIFIED_SNAPSHOT",

        "EXPLORATORY_UNVERIFIED",
    )


    zones[
        "fallback_used"
    ] = False


    # -----------------------------------------------------------------------
    # Calculate factor groups
    # -----------------------------------------------------------------------

    environment = (
        _environment_factor_scores(
            zones
        )
    )


    historical = (
        _historical_factor_scores(

            zones,
            vendors,

            business=business,

            vendor_id=vendor_id,

            vendor_record=vendor_record,
        )
    )


    components = {

        "business":
            historical[
                "business"
            ],

        "commercial":
            environment[
                "commercial"
            ],

        "access":
            environment[
                "access"
            ],

        "facilities":
            environment[
                "facilities"
            ],

        "preference":
            _preference_score(
                zones,
                division,
            ),

        "historical":
            historical[
                "historical"
            ],
    }


    zones = _calculate_mcda(

        zones,

        components,

        weights,
    )


    # -----------------------------------------------------------------------
    # Output semantics / safeguards
    # -----------------------------------------------------------------------

    zones[
        "score_type"
    ] = (
        "ILLUSTRATIVE_MCDA_NOT_SUCCESS_PROBABILITY"
    )


    zones[
        "limitations"
    ] = (

        "OSM coverage incomplete; "

        "historical association is not success; "

        "reference geometry unverified; "

        "live status snapshot is not a permit"
    )


    zones[
        "reference_warning"
    ] = zones[
        "reference_warning"
    ].fillna(

        "Analytical reference only; "
        "site-level verification required."
    )


    zones[
        "shared_reference"
    ] = (

        zones[
            "shared_reference"
        ]
        .fillna(False)
        .astype(bool)
    )


    zones[
        "rank"
    ] = 0


    # Deterministic ordering.
    zones = zones.sort_values(

        [
            "score",
            "zone_id",
        ],

        ascending=[
            False,
            True,
        ],

        na_position="last",

    ).reset_index(
        drop=True
    )


    zones.attrs.update(
        metadata
    )


    return zones


# ---------------------------------------------------------------------------
# Top-N ranking
# ---------------------------------------------------------------------------


def rank_candidates(
    scored: pd.DataFrame,
    *,
    division: str = "",
    top_n: int = 3,
) -> pd.DataFrame:
    """Apply deterministic local-first Top-N recommendation policy."""

    if (
        top_n < 1
        or top_n > 20
    ):

        raise ValueError(
            "top_n must be 1–20"
        )


    metadata = dict(
        scored.attrs
    )


    if scored.empty:

        result = scored.copy()

        result.attrs.update(
            metadata
        )

        return result


    # Prefer requested division first.
    #
    # If fewer than Top-N local zones survive, explicitly fill with the best
    # candidates from other divisions and mark them as fallback results.

    if division:

        local = scored.loc[

            scored.zone_division.eq(
                division
            )

        ].head(
            top_n
        ).copy()


        remaining_count = (
            top_n
            - len(local)
        )


        alternatives = scored.loc[

            ~scored.zone_id.isin(
                local.zone_id
            )

        ].head(
            remaining_count
        ).copy()


        alternatives[
            "fallback_used"
        ] = True


        result = pd.concat(

            [
                local,
                alternatives,
            ],

            ignore_index=True,
        )


    else:

        result = (
            scored.head(
                top_n
            )
            .copy()
            .reset_index(
                drop=True
            )
        )


    result[
        "rank"
    ] = np.arange(
        1,
        len(result) + 1,
    )


    def build_reason(
        row,
    ) -> str:

        parts = [

            (
                f"{name}: "
                f"{row[f'{name}_score']:.2f}"
            )

            for name in FACTOR_ORDER

            if pd.notna(
                row.get(
                    f"{name}_score"
                )
            )
        ]


        if bool(
            row.get(
                "fallback_used",
                False,
            )
        ):

            parts.append(
                "outside preferred division"
            )


        return "; ".join(
            parts
        )


    result[
        "reason"
    ] = result.apply(
        build_reason,
        axis=1,
    )


    result.attrs.update(
        metadata
    )


    return result


# ---------------------------------------------------------------------------
# Public recommendation function
# ---------------------------------------------------------------------------


def recommend(
    business,
    division="",
    vendor_id="",
    top_n=3,
    exclude_zone="",
    require_verified=False,
    use_live_status=False,
    database_path=None,
    factor_weights=None,
):
    """Return ranked Top-N recommendations.

    This signature remains backward compatible with the current API, tests and
    CLI while internally using the reusable full-candidate scoring pipeline.
    """

    if (
        top_n < 1
        or top_n > 20
    ):

        raise ValueError(
            "top_n must be 1–20"
        )


    scored = score_candidates(

        business=business,

        division=division,

        vendor_id=vendor_id,

        exclude_zone=exclude_zone,

        require_verified=(
            require_verified
        ),

        use_live_status=(
            use_live_status
        ),

        database_path=(
            database_path
        ),

        factor_weights=(
            factor_weights
        ),
    )


    # An existing historical vendor may have inherited its division inside
    # score_candidates(), so ranking must use the resolved division.

    effective_division = str(

        scored.attrs.get(
            "division",
            division,
        )

        or ""
    )


    return rank_candidates(

        scored,

        division=(
            effective_division
        ),

        top_n=(
            top_n
        ),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(
        "--business",
        default="",
    )


    parser.add_argument(
        "--division",
        default="",
    )


    parser.add_argument(
        "--vendor-id",
        default="",
    )


    parser.add_argument(
        "--exclude-zone",
        default="",
    )


    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
    )


    parser.add_argument(
        "--require-verified",
        action="store_true",
    )


    parser.add_argument(
        "--use-live-status",
        action="store_true",
        help=(
            "Filter candidates using "
            "the operational SQLite database"
        ),
    )


    args = parser.parse_args()


    result = recommend(

        args.business,

        args.division,

        args.vendor_id,

        args.top_n,

        args.exclude_zone,

        args.require_verified,

        args.use_live_status,
    )


    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )


    output_path = (
        OUT
        / "recommendations.csv"
    )


    if result.empty:

        pd.DataFrame(
            columns=[
                "rank",
                "zone_id",
                "zone_division",
                "score",
                "candidate_status",
                "fallback_used",
                "reason",
            ]
        ).to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
        )


    else:

        result.to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
        )


    if result.empty:

        print(
            "No candidates meet the requested filters. "
            "No allocation can be inferred."
        )


    else:

        columns = [
            "rank",
            "zone_id",
            "zone_division",
            "score",
            "candidate_status",
            "fallback_used",
            "reason",
        ]


        print(
            result[
                columns
            ].to_string(
                index=False
            )
        )


    print(
        "\nSaved:",
        output_path,
    )


    print(
        "Scores are illustrative decision-support values, "
        "not probabilities or permits."
    )


    print(
        "Only a municipal-authorized, recent status snapshot "
        "can establish verified availability."
    )


    if args.use_live_status:

        print(

            "Live filter:",

            result.attrs.get(
                "candidate_count_before_live_filter"
            ),

            "->",

            result.attrs.get(
                "candidate_count_after_live_filter"
            ),

            "candidates",
        )


if __name__ == "__main__":
    main()