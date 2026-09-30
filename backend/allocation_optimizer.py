"""Constrained batch allocation planning using pre-emptive goal programming.

This module sits AFTER the MCDA suitability engine.

MCDA answers:
    Which operationally eligible zones are suitable for each vendor?

This optimiser answers:
    Given several vendors and finite live zone capacities, what assignment plan
    satisfies the highest-priority operational goals without exceeding capacity?

The optimiser is advisory only. It never writes to the operational database,
approves a request, reserves a slot, or creates an allocation.

The existing audited approval workflow remains responsible for committing
allocations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

try:
    from scipy.optimize import (
        Bounds,
        LinearConstraint,
        milp,
    )
    from scipy.sparse import coo_array

except ImportError as exc:
    raise RuntimeError(
        "Allocation optimisation requires scipy>=1.11,<2."
    ) from exc


try:
    from .decision_policy import (
        RESEARCH_BASELINE_WEIGHTS,
        normalize_weights,
    )

    from .mcda_engine import (
        score_candidates,
    )

except ImportError:

    from decision_policy import (
        RESEARCH_BASELINE_WEIGHTS,
        normalize_weights,
    )

    from mcda_engine import (
        score_candidates,
    )


REQUEST_TYPES = {
    "NEW_ALLOCATION",
    "RELOCATION",
}


class AllocationOptimizationError(
    RuntimeError
):
    """Raised when the allocation MILP cannot be solved."""


@dataclass(frozen=True)
class AllocationDemand:
    """One vendor considered by the batch allocation planner.

    vendor_id:
        Operational vendor identifier.

    historical_vendor_id:
        Optional historical registry ID used only for MCDA self-evidence
        exclusion. New vendors should leave this empty.
    """

    vendor_id: str

    business: str

    preferred_division: str = ""

    request_type: str = (
        "NEW_ALLOCATION"
    )

    historical_vendor_id: str = ""

    exclude_zone: str = ""

    factor_weights: (
        Mapping[str, float]
        | None
    ) = None


@dataclass(frozen=True)
class OptimizationConfig:
    """Allocation optimisation policy."""

    # Production allocation should normally require a recent,
    # municipal-verified availability record.
    #
    # False is useful only for research/demo snapshots.
    require_verified: bool = True

    # None means consider every eligible zone.
    #
    # A positive number can later be used for large batches after
    # benchmarking the impact on solution quality.
    candidate_pool_size: (
        int | None
    ) = None

    # Safety limit for one optimisation job.
    max_vendors: int = 500

    # Stage-2 goal weights.
    #
    # Stage 1 already maximises how many vendors can be assigned.
    # These parameters choose the best solution among plans that assign
    # the same maximum number of vendors.
    suitability_weight: float = 1.0

    fallback_penalty: float = 0.10

    coverage_penalty: float = 0.05

    # HiGHS / scipy.optimize.milp controls.
    time_limit_seconds: (
        float | None
    ) = 30.0

    mip_relative_gap: (
        float | None
    ) = 0.0


@dataclass(frozen=True)
class PlannedAssignment:
    """One proposed vendor-zone assignment."""

    vendor_id: str

    zone_id: str

    request_type: str

    business: str

    preferred_division: str

    zone_division: str

    suitability_score: float

    score_coverage: float

    fallback_used: bool

    available_capacity_snapshot: int

    verified_snapshot: bool


@dataclass(frozen=True)
class AllocationPlan:
    """Read-only output from the allocation optimizer."""

    status: str

    assignment_count: int

    unassigned_count: int

    vendor_count: int

    mean_suitability_score: (
        float | None
    )

    total_suitability_score: float

    fallback_assignment_count: int

    assignments: tuple[
        PlannedAssignment,
        ...
    ]

    unassigned_vendor_ids: tuple[
        str,
        ...
    ]

    capacity_snapshot: Mapping[
        str,
        int,
    ]

    stage1_objective_unassigned: int

    stage2_objective_cost: float

    require_verified: bool

    notice: str = (
        "Optimization output is an advisory allocation plan. "
        "It is not a reservation, approval, permit, "
        "or database allocation."
    )

    def to_dict(
        self,
    ) -> dict[
        str,
        Any,
    ]:

        payload = asdict(
            self
        )

        payload[
            "assignments"
        ] = [

            asdict(
                item
            )

            for item
            in self.assignments
        ]

        payload[
            "unassigned_vendor_ids"
        ] = list(
            self.unassigned_vendor_ids
        )

        payload[
            "capacity_snapshot"
        ] = dict(
            self.capacity_snapshot
        )

        return payload


@dataclass(frozen=True)
class _CandidateEdge:
    """One feasible vendor-zone decision variable."""

    vendor_id: str

    zone_id: str

    request_type: str

    business: str

    preferred_division: str

    zone_division: str

    score: float

    score_coverage: float

    fallback_used: bool

    available_capacity: int

    live_verified: bool


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_config(
    config: OptimizationConfig,
) -> None:

    if config.max_vendors < 1:

        raise ValueError(
            "max_vendors must be positive"
        )


    if (
        config.candidate_pool_size
        is not None

        and config.candidate_pool_size
        < 1
    ):

        raise ValueError(
            "candidate_pool_size must "
            "be positive or None"
        )


    for name in (
        "suitability_weight",
        "fallback_penalty",
        "coverage_penalty",
    ):

        value = float(
            getattr(
                config,
                name,
            )
        )

        if (
            not isfinite(
                value
            )

            or value < 0
        ):

            raise ValueError(
                f"{name} must be a finite "
                "nonnegative number"
            )


    if (
        config.time_limit_seconds
        is not None
    ):

        if (
            not isfinite(
                config.time_limit_seconds
            )

            or config.time_limit_seconds
            <= 0
        ):

            raise ValueError(
                "time_limit_seconds must "
                "be positive or None"
            )


    if (
        config.mip_relative_gap
        is not None
    ):

        if (
            not isfinite(
                config.mip_relative_gap
            )

            or config.mip_relative_gap
            < 0
        ):

            raise ValueError(
                "mip_relative_gap must be "
                "nonnegative or None"
            )


def _validate_demands(
    demands: Sequence[
        AllocationDemand
    ],
    config: OptimizationConfig,
) -> None:

    if not demands:

        raise ValueError(
            "At least one allocation "
            "demand is required"
        )


    if (
        len(
            demands
        )
        > config.max_vendors
    ):

        raise ValueError(
            f"Batch contains {len(demands)} "
            f"vendors; maximum is "
            f"{config.max_vendors}"
        )


    seen: set[str] = set()


    for demand in demands:

        vendor_id = (
            demand.vendor_id.strip()
        )


        if not vendor_id:

            raise ValueError(
                "vendor_id must not "
                "be empty"
            )


        if vendor_id in seen:

            raise ValueError(
                "Duplicate vendor_id "
                "in allocation batch: "
                f"{vendor_id}"
            )


        seen.add(
            vendor_id
        )


        if not (
            demand.business.strip()
        ):

            raise ValueError(
                "business must not "
                "be empty for vendor "
                f"{vendor_id}"
            )


        request_type = (
            demand.request_type
            .strip()
            .upper()
        )


        if (
            request_type
            not in REQUEST_TYPES
        ):

            raise ValueError(
                f"request_type for {vendor_id} "
                "must be one of: "
                + ", ".join(
                    sorted(
                        REQUEST_TYPES
                    )
                )
            )


        if (
            demand.factor_weights
            is not None
        ):

            normalize_weights(
                demand.factor_weights
            )


# ---------------------------------------------------------------------------
# Candidate preparation
# ---------------------------------------------------------------------------


def _known_positive_capacity(
    row: pd.Series,
) -> int | None:
    """Return usable allocation capacity or None.

    Recommendation can operate with unknown capacity.

    Allocation optimisation cannot consume an unknown slot.
    """

    raw = row.get(
        "available_capacity"
    )


    if (
        raw is None
        or pd.isna(
            raw
        )
    ):

        raw = row.get(
            "verified_available_capacity"
        )


    if (
        raw is None
        or pd.isna(
            raw
        )
    ):

        return None


    value = float(
        raw
    )


    if (
        not np.isfinite(
            value
        )

        or value <= 0

        or not value.is_integer()
    ):

        return None


    return int(
        value
    )


def _build_edges(
    demands: Sequence[
        AllocationDemand
    ],
    *,
    database_path: (
        str
        | Path
        | None
    ),
    config: OptimizationConfig,
) -> tuple[
    list[
        _CandidateEdge
    ],
    dict[
        str,
        int,
    ],
]:
    """Build feasible vendor-zone decision edges.

    Every vendor is scored against the current operational zone snapshot.

    Zones with unknown capacity are excluded from allocation planning.
    """

    edges: list[
        _CandidateEdge
    ] = []

    capacities: dict[
        str,
        int,
    ] = {}


    for demand in demands:

        weights = (
            normalize_weights(

                demand.factor_weights

                if (
                    demand.factor_weights
                    is not None
                )

                else (
                    RESEARCH_BASELINE_WEIGHTS
                )
            )
        )


        scored = (
            score_candidates(

                business=(
                    demand.business.strip()
                ),

                division=(
                    demand.preferred_division
                    .strip()
                ),

                vendor_id=(
                    demand.historical_vendor_id
                    .strip()
                ),

                exclude_zone=(
                    demand.exclude_zone
                    .strip()
                ),

                require_verified=(
                    config.require_verified
                ),

                use_live_status=True,

                database_path=(
                    database_path
                ),

                factor_weights=(
                    weights
                ),
            )
        )


        if scored.empty:
            continue


        usable_rows: list[
            tuple[
                float,
                str,
                pd.Series,
                int,
            ]
        ] = []


        for _, row in (
            scored.iterrows()
        ):

            capacity = (
                _known_positive_capacity(
                    row
                )
            )


            if capacity is None:
                continue


            score = pd.to_numeric(

                pd.Series(
                    [
                        row.get(
                            "score"
                        )
                    ]
                ),

                errors="coerce",

            ).iloc[
                0
            ]


            if (
                pd.isna(
                    score
                )

                or not np.isfinite(
                    float(
                        score
                    )
                )
            ):

                continue


            zone_id = str(
                row.get(
                    "zone_id"
                )
                or ""
            ).strip()


            if not zone_id:
                continue


            usable_rows.append(
                (
                    float(
                        score
                    ),
                    zone_id,
                    row,
                    capacity,
                )
            )


        usable_rows.sort(
            key=lambda item: (
                -item[
                    0
                ],
                item[
                    1
                ],
            )
        )


        if (
            config.candidate_pool_size
            is not None
        ):

            usable_rows = (
                usable_rows[
                    :config
                    .candidate_pool_size
                ]
            )


        for (
            score,
            zone_id,
            row,
            capacity,

        ) in usable_rows:

            existing_capacity = (
                capacities.get(
                    zone_id
                )
            )


            if (
                existing_capacity
                is not None

                and existing_capacity
                != capacity
            ):

                raise (
                    AllocationOptimizationError(
                        "Inconsistent live capacity "
                        f"snapshot for zone {zone_id}: "
                        f"{existing_capacity} vs "
                        f"{capacity}"
                    )
                )


            capacities[
                zone_id
            ] = capacity


            preferred_division = (
                demand
                .preferred_division
                .strip()
            )


            zone_division = str(
                row.get(
                    "zone_division"
                )
                or ""
            ).strip()


            fallback = bool(
                preferred_division

                and (
                    zone_division
                    != preferred_division
                )
            )


            coverage_raw = row.get(
                "score_coverage"
            )


            coverage = (

                float(
                    coverage_raw
                )

                if pd.notna(
                    coverage_raw
                )

                else 0.0
            )


            coverage = float(
                np.clip(
                    coverage,
                    0.0,
                    1.0,
                )
            )


            edges.append(
                _CandidateEdge(

                    vendor_id=(
                        demand
                        .vendor_id
                        .strip()
                    ),

                    zone_id=(
                        zone_id
                    ),

                    request_type=(
                        demand
                        .request_type
                        .strip()
                        .upper()
                    ),

                    business=(
                        demand
                        .business
                        .strip()
                    ),

                    preferred_division=(
                        preferred_division
                    ),

                    zone_division=(
                        zone_division
                    ),

                    score=float(
                        np.clip(
                            score,
                            0.0,
                            100.0,
                        )
                    ),

                    score_coverage=(
                        coverage
                    ),

                    fallback_used=(
                        fallback
                    ),

                    available_capacity=(
                        capacity
                    ),

                    live_verified=bool(
                        row.get(
                            "live_verified",
                            False,
                        )
                    ),
                )
            )


    return (
        edges,
        capacities,
    )


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


def _milp_options(
    config: OptimizationConfig,
) -> dict[
    str,
    float | bool,
]:

    options: dict[
        str,
        float | bool,
    ] = {
        "disp": False,
    }


    if (
        config.time_limit_seconds
        is not None
    ):

        options[
            "time_limit"
        ] = float(
            config.time_limit_seconds
        )


    if (
        config.mip_relative_gap
        is not None
    ):

        options[
            "mip_rel_gap"
        ] = float(
            config.mip_relative_gap
        )


    return options


def _solve_model(
    demands: Sequence[
        AllocationDemand
    ],
    edges: Sequence[
        _CandidateEdge
    ],
    capacities: Mapping[
        str,
        int,
    ],
    config: OptimizationConfig,
) -> AllocationPlan:
    """Solve two-stage pre-emptive Goal Programming.

    Stage 1:
        Minimise number of unassigned vendors.

    Stage 2:
        Keep that optimum assignment count fixed and minimise:

        - suitability loss,
        - preferred-division fallback,
        - low evidence coverage.

    Hard constraints:

        - each vendor can receive at most one zone,
        - every vendor is either assigned or explicitly unassigned,
        - no zone exceeds current available capacity.
    """

    vendor_ids = [

        demand.vendor_id.strip()

        for demand
        in demands
    ]


    vendor_index = {

        vendor_id:
            position

        for position, vendor_id
        in enumerate(
            vendor_ids
        )
    }


    zones = sorted(
        capacities
    )


    zone_index = {

        zone_id:
            position

        for position, zone_id
        in enumerate(
            zones
        )
    }


    edge_count = len(
        edges
    )

    vendor_count = len(
        vendor_ids
    )


    variable_count = (
        edge_count
        + vendor_count
    )


    unassigned_offset = (
        edge_count
    )


    # All decision variables are binary.
    integrality = np.ones(
        variable_count,
        dtype=np.int32,
    )


    bounds = Bounds(

        lb=np.zeros(
            variable_count,
            dtype=float,
        ),

        ub=np.ones(
            variable_count,
            dtype=float,
        ),
    )


    # Constraint rows:
    #
    # 1) vendor rows:
    #
    #    sum(zone assignments) + unassigned = 1
    #
    # 2) zone rows:
    #
    #    sum(vendors assigned) <= available_capacity

    row_indices: list[
        int
    ] = []

    column_indices: list[
        int
    ] = []

    values: list[
        float
    ] = []


    constraint_count = (

        vendor_count
        + len(
            zones
        )
    )


    lower = np.full(
        constraint_count,
        -np.inf,
        dtype=float,
    )


    upper = np.full(
        constraint_count,
        np.inf,
        dtype=float,
    )


    for (
        edge_position,
        edge,

    ) in enumerate(
        edges
    ):

        vendor_row = (
            vendor_index[
                edge.vendor_id
            ]
        )


        row_indices.append(
            vendor_row
        )

        column_indices.append(
            edge_position
        )

        values.append(
            1.0
        )


        zone_row = (

            vendor_count

            + zone_index[
                edge.zone_id
            ]
        )


        row_indices.append(
            zone_row
        )

        column_indices.append(
            edge_position
        )

        values.append(
            1.0
        )


    # Explicit unassigned variable for every vendor.
    for vendor_position in range(
        vendor_count
    ):

        row_indices.append(
            vendor_position
        )

        column_indices.append(

            unassigned_offset
            + vendor_position

        )

        values.append(
            1.0
        )


        lower[
            vendor_position
        ] = 1.0

        upper[
            vendor_position
        ] = 1.0


    # Zone capacities are hard constraints.
    for (
        zone_id,
        position,

    ) in zone_index.items():

        row = (
            vendor_count
            + position
        )


        upper[
            row
        ] = float(
            capacities[
                zone_id
            ]
        )


    matrix = coo_array(

        (
            values,
            (
                row_indices,
                column_indices,
            ),
        ),

        shape=(
            constraint_count,
            variable_count,
        ),

    ).tocsr()


    base_constraint = (
        LinearConstraint(
            matrix,
            lb=lower,
            ub=upper,
        )
    )


    # =======================================================================
    # Stage 1
    #
    # Highest-priority goal:
    #
    # minimise the number of unassigned vendors.
    # =======================================================================

    stage1_cost = np.zeros(
        variable_count,
        dtype=float,
    )


    stage1_cost[
        unassigned_offset:
    ] = 1.0


    stage1 = milp(

        c=stage1_cost,

        integrality=(
            integrality
        ),

        bounds=(
            bounds
        ),

        constraints=[
            base_constraint,
        ],

        options=(
            _milp_options(
                config
            )
        ),
    )


    if (
        not stage1.success

        or stage1.x is None
    ):

        raise (
            AllocationOptimizationError(

                "Stage-1 allocation "
                "optimisation failed: "
                f"status={stage1.status}, "
                f"message={stage1.message}"
            )
        )


    minimum_unassigned = int(
        round(
            float(
                np.sum(
                    stage1.x[
                        unassigned_offset:
                    ]
                )
            )
        )
    )


    # =======================================================================
    # Stage 2
    #
    # Keep Stage-1 optimum fixed.
    #
    # Among plans assigning the same maximum number of vendors, minimise:
    #
    # - suitability loss,
    # - fallback outside preferred division,
    # - incomplete evidence coverage.
    # =======================================================================

    stage2_cost = np.zeros(
        variable_count,
        dtype=float,
    )


    for (
        position,
        edge,

    ) in enumerate(
        edges
    ):

        suitability_loss = (

            1.0

            - (
                edge.score
                / 100.0
            )
        )


        coverage_loss = (

            1.0

            - edge.score_coverage
        )


        fallback_loss = (

            1.0

            if edge.fallback_used

            else 0.0
        )


        stage2_cost[
            position
        ] = (

            config.suitability_weight
            * suitability_loss

            + config.fallback_penalty
            * fallback_loss

            + config.coverage_penalty
            * coverage_loss
        )


    # Unassigned count is fixed by a new equality constraint,
    # so it does not need an objective penalty here.
    stage2_cost[
        unassigned_offset:
    ] = 0.0


    unassigned_row = np.zeros(
        variable_count,
        dtype=float,
    )


    unassigned_row[
        unassigned_offset:
    ] = 1.0


    fixed_unassigned_constraint = (
        LinearConstraint(

            unassigned_row,

            lb=float(
                minimum_unassigned
            ),

            ub=float(
                minimum_unassigned
            ),
        )
    )


    stage2 = milp(

        c=stage2_cost,

        integrality=(
            integrality
        ),

        bounds=(
            bounds
        ),

        constraints=[
            base_constraint,
            fixed_unassigned_constraint,
        ],

        options=(
            _milp_options(
                config
            )
        ),
    )


    if (
        not stage2.success

        or stage2.x is None
    ):

        raise (
            AllocationOptimizationError(

                "Stage-2 allocation "
                "optimisation failed: "
                f"status={stage2.status}, "
                f"message={stage2.message}"
            )
        )


    selected_edges = [

        edges[
            position
        ]

        for position
        in range(
            edge_count
        )

        if (
            stage2.x[
                position
            ]
            > 0.5
        )
    ]


    selected_edges.sort(
        key=lambda edge:
            edge.vendor_id
    )


    assignments = tuple(

        PlannedAssignment(

            vendor_id=(
                edge.vendor_id
            ),

            zone_id=(
                edge.zone_id
            ),

            request_type=(
                edge.request_type
            ),

            business=(
                edge.business
            ),

            preferred_division=(
                edge.preferred_division
            ),

            zone_division=(
                edge.zone_division
            ),

            suitability_score=(
                edge.score
            ),

            score_coverage=(
                edge.score_coverage
            ),

            fallback_used=(
                edge.fallback_used
            ),

            available_capacity_snapshot=(
                edge.available_capacity
            ),

            verified_snapshot=(
                edge.live_verified
            ),
        )

        for edge
        in selected_edges
    )


    assigned_vendors = {

        assignment.vendor_id

        for assignment
        in assignments
    }


    unassigned = tuple(

        vendor_id

        for vendor_id
        in vendor_ids

        if vendor_id
        not in assigned_vendors
    )


    total_score = float(

        sum(

            assignment
            .suitability_score

            for assignment
            in assignments
        )
    )


    mean_score = (

        total_score
        / len(
            assignments
        )

        if assignments

        else None
    )


    return AllocationPlan(

        status="OPTIMAL",

        assignment_count=(
            len(
                assignments
            )
        ),

        unassigned_count=(
            len(
                unassigned
            )
        ),

        vendor_count=(
            len(
                vendor_ids
            )
        ),

        mean_suitability_score=(
            mean_score
        ),

        total_suitability_score=(
            total_score
        ),

        fallback_assignment_count=(

            sum(

                1

                for assignment
                in assignments

                if (
                    assignment
                    .fallback_used
                )
            )
        ),

        assignments=(
            assignments
        ),

        unassigned_vendor_ids=(
            unassigned
        ),

        capacity_snapshot=(
            dict(
                capacities
            )
        ),

        stage1_objective_unassigned=(
            minimum_unassigned
        ),

        stage2_objective_cost=(
            float(
                stage2.fun
            )
        ),

        require_verified=(
            config.require_verified
        ),
    )


# ---------------------------------------------------------------------------
# Public allocation API
# ---------------------------------------------------------------------------


def optimize_allocations(
    demands: Sequence[
        AllocationDemand
    ],
    *,
    database_path: (
        str
        | Path
        | None
    ) = None,
    config: (
        OptimizationConfig
        | None
    ) = None,
) -> AllocationPlan:
    """Create a read-only batch allocation plan.

    This function:

    1. scores each vendor using the MCDA engine,
    2. uses the current live capacity snapshot,
    3. constructs feasible vendor-zone edges,
    4. solves the Goal Programming MILP,
    5. returns a proposed plan.

    It deliberately performs no database writes.
    """

    config = (
        config
        or OptimizationConfig()
    )


    _validate_config(
        config
    )


    _validate_demands(
        demands,
        config,
    )


    (
        edges,
        capacities,

    ) = _build_edges(

        demands,

        database_path=(
            database_path
        ),

        config=(
            config
        ),
    )


    # Vendors with no eligible candidate remain feasible through
    # their explicit "unassigned" binary variable.
    return _solve_model(

        demands,

        edges,

        capacities,

        config,
    )


# ---------------------------------------------------------------------------
# Deterministic testing interface
# ---------------------------------------------------------------------------


def optimize_precomputed(
    demands: Sequence[
        AllocationDemand
    ],
    candidate_rows: Sequence[
        Mapping[
            str,
            Any,
        ]
    ],
    capacities: Mapping[
        str,
        int,
    ],
    *,
    config: (
        OptimizationConfig
        | None
    ) = None,
) -> AllocationPlan:
    """Solve an allocation plan from precomputed candidate rows.

    This is useful for unit tests and offline experiments where database state
    must not influence the test.

    Required candidate fields:

    - vendor_id
    - zone_id
    - score
    - score_coverage
    - zone_division

    Optional:

    - fallback_used
    - live_verified
    """

    config = (
        config

        or OptimizationConfig(
            require_verified=False
        )
    )


    _validate_config(
        config
    )


    _validate_demands(
        demands,
        config,
    )


    demand_by_vendor = {

        demand.vendor_id.strip():
            demand

        for demand
        in demands
    }


    clean_capacities: dict[
        str,
        int,
    ] = {}


    for (
        zone_id,
        capacity,

    ) in capacities.items():

        value = int(
            capacity
        )


        if value < 0:

            raise ValueError(
                "Negative capacity for zone "
                f"{zone_id}"
            )


        if value > 0:

            clean_capacities[
                str(
                    zone_id
                )
            ] = value


    edges: list[
        _CandidateEdge
    ] = []


    seen_pairs: set[
        tuple[
            str,
            str,
        ]
    ] = set()


    for raw in candidate_rows:

        vendor_id = str(
            raw.get(
                "vendor_id"
            )
            or ""
        ).strip()


        zone_id = str(
            raw.get(
                "zone_id"
            )
            or ""
        ).strip()


        if (
            vendor_id
            not in demand_by_vendor
        ):

            raise ValueError(
                "Candidate row references "
                "unknown vendor "
                f"{vendor_id!r}"
            )


        if (
            zone_id
            not in clean_capacities
        ):

            continue


        pair = (
            vendor_id,
            zone_id,
        )


        if pair in seen_pairs:

            raise ValueError(
                "Duplicate candidate edge: "
                f"{vendor_id} -> {zone_id}"
            )


        seen_pairs.add(
            pair
        )


        demand = (
            demand_by_vendor[
                vendor_id
            ]
        )


        score = float(
            raw.get(
                "score"
            )
        )


        coverage = float(
            raw.get(
                "score_coverage",
                1.0,
            )
        )


        if (
            not np.isfinite(
                score
            )

            or not (
                0.0
                <= score
                <= 100.0
            )
        ):

            raise ValueError(
                "Invalid score for "
                f"{vendor_id} -> "
                f"{zone_id}"
            )


        if (
            not np.isfinite(
                coverage
            )

            or not (
                0.0
                <= coverage
                <= 1.0
            )
        ):

            raise ValueError(
                "Invalid score_coverage "
                f"for {vendor_id} -> "
                f"{zone_id}"
            )


        zone_division = str(
            raw.get(
                "zone_division"
            )
            or ""
        ).strip()


        preferred = (
            demand
            .preferred_division
            .strip()
        )


        fallback = bool(

            raw.get(

                "fallback_used",

                bool(
                    preferred

                    and (
                        zone_division
                        != preferred
                    )
                ),
            )
        )


        edges.append(
            _CandidateEdge(

                vendor_id=(
                    vendor_id
                ),

                zone_id=(
                    zone_id
                ),

                request_type=(
                    demand
                    .request_type
                    .strip()
                    .upper()
                ),

                business=(
                    demand
                    .business
                    .strip()
                ),

                preferred_division=(
                    preferred
                ),

                zone_division=(
                    zone_division
                ),

                score=(
                    score
                ),

                score_coverage=(
                    coverage
                ),

                fallback_used=(
                    fallback
                ),

                available_capacity=(
                    clean_capacities[
                        zone_id
                    ]
                ),

                live_verified=bool(
                    raw.get(
                        "live_verified",
                        False,
                    )
                ),
            )
        )


    return _solve_model(

        demands,

        edges,

        clean_capacities,

        config,
    )