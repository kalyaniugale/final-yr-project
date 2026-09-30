"""Production service layer for advisory batch allocation planning.

This module converts real vendor profiles and operational state into
AllocationDemand objects for the Goal Programming optimizer.

Responsibilities
----------------
- resolve vendor profiles,
- apply vendor-specific MCDA weight policies,
- detect current active allocations,
- infer NEW_ALLOCATION vs RELOCATION,
- exclude the vendor's current zone during relocation,
- prevent conflicting plans for vendors with pending requests,
- call the read-only allocation optimizer,
- enrich the optimizer result with safe vendor context.

This module does NOT:
- create allocation requests,
- approve allocations,
- reserve capacity,
- update zone occupancy,
- or write recommendation decisions to the database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    from .allocation_optimizer import (
        AllocationDemand,
        AllocationPlan,
        OptimizationConfig,
        optimize_allocations,
    )

    from .database import (
        DATABASE_PATH,
        get_active_allocation_for_vendor,
        list_allocation_requests,
    )

    from .decision_policy import (
        derive_mcda_weights,
    )

    from .vendor_service import (
        get_vendor_profile,
    )

except ImportError:

    from allocation_optimizer import (
        AllocationDemand,
        AllocationPlan,
        OptimizationConfig,
        optimize_allocations,
    )

    from database import (
        DATABASE_PATH,
        get_active_allocation_for_vendor,
        list_allocation_requests,
    )

    from decision_policy import (
        derive_mcda_weights,
    )

    from vendor_service import (
        get_vendor_profile,
    )


class AllocationPlanningValidationError(
    ValueError
):
    """Raised when a vendor cannot safely enter an allocation plan."""


@dataclass(frozen=True)
class VendorPlanningContext:
    """Non-sensitive vendor context used to explain the generated plan."""

    vendor_id: str

    application_vendor_id: str | None

    vendor_type: str

    full_name: str | None

    business_name: str | None

    business_category: str

    preferred_division: str

    priority_profile: str

    request_type: str

    current_zone_id: str | None

    historical_evidence_vendor_id: str | None

    weight_source: str

    effective_factor_weights: dict[
        str,
        float,
    ]


@dataclass(frozen=True)
class BatchPlanningResult:
    """Service-layer allocation planning response."""

    plan: AllocationPlan

    vendor_context: tuple[
        VendorPlanningContext,
        ...
    ]

    skipped_vendor_ids: tuple[
        str,
        ...
    ]

    warnings: tuple[
        str,
        ...
    ]

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "plan":
                self.plan.to_dict(),

            "vendor_context": [
                asdict(
                    item
                )
                for item
                in self.vendor_context
            ],

            "skipped_vendor_ids":
                list(
                    self.skipped_vendor_ids
                ),

            "warnings":
                list(
                    self.warnings
                ),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_vendor_ids(
    vendor_ids: Sequence[str],
) -> list[str]:
    """Normalize and validate vendor IDs while preserving request order."""

    if not vendor_ids:

        raise (
            AllocationPlanningValidationError(
                "At least one vendor_id is required"
            )
        )


    cleaned: list[str] = []

    seen: set[str] = set()


    for raw in vendor_ids:

        vendor_id = str(
            raw
            or ""
        ).strip()


        if not vendor_id:

            raise (
                AllocationPlanningValidationError(
                    "vendor_id must not be empty"
                )
            )


        if vendor_id in seen:

            raise (
                AllocationPlanningValidationError(
                    "Duplicate vendor_id in planning batch: "
                    f"{vendor_id}"
                )
            )


        seen.add(
            vendor_id
        )

        cleaned.append(
            vendor_id
        )


    return cleaned


def _pending_vendor_ids(
    database_path: str | Path,
) -> set[str]:
    """Return vendors that already have an unresolved allocation request."""

    rows = list_allocation_requests(
        status="PENDING",
        database_path=database_path,
    )


    return {
        str(
            row[
                "vendor_id"
            ]
        )
        for row
        in rows
    }


# ---------------------------------------------------------------------------
# Demand construction
# ---------------------------------------------------------------------------


def build_allocation_demands(
    vendor_ids: Sequence[str],
    *,
    database_path: str | Path = (
        DATABASE_PATH
    ),
    reject_pending_requests: bool = True,
) -> tuple[
    list[
        AllocationDemand
    ],
    list[
        VendorPlanningContext
    ],
    list[str],
    list[str],
]:
    """Resolve real vendor state into optimization demands.

    Returns:

        demands,
        contexts,
        skipped_vendor_ids,
        warnings

    By default, a vendor with an existing PENDING allocation request is
    rejected from the new planning batch. This prevents the planner from
    suggesting a second decision while an earlier request is unresolved.
    """

    cleaned_ids = (
        _clean_vendor_ids(
            vendor_ids
        )
    )


    pending = (
        _pending_vendor_ids(
            database_path
        )
        if reject_pending_requests
        else set()
    )


    demands: list[
        AllocationDemand
    ] = []

    contexts: list[
        VendorPlanningContext
    ] = []

    skipped: list[str] = []

    warnings: list[str] = []


    for vendor_id in cleaned_ids:

        profile = get_vendor_profile(
            vendor_id,
            database_path=database_path,
        )


        if profile is None:

            raise (
                AllocationPlanningValidationError(
                    f"Unknown vendor_id: {vendor_id}"
                )
            )


        if (
            str(
                profile.get(
                    "status"
                )
                or ""
            ).upper()
            != "ACTIVE"
        ):

            raise (
                AllocationPlanningValidationError(
                    f"Vendor {vendor_id} is not ACTIVE"
                )
            )


        if vendor_id in pending:

            skipped.append(
                vendor_id
            )

            warnings.append(
                f"Vendor {vendor_id} was skipped because "
                "a PENDING allocation request already exists."
            )

            continue


        business = str(
            profile.get(
                "business_category"
            )
            or ""
        ).strip()


        if not business:

            raise (
                AllocationPlanningValidationError(
                    f"Vendor {vendor_id} has no business category"
                )
            )


        preferred_division = str(
            profile.get(
                "preferred_division"
            )
            or ""
        ).strip()


        active = (
            get_active_allocation_for_vendor(
                vendor_id,
                database_path=database_path,
            )
        )


        if active is None:

            request_type = (
                "NEW_ALLOCATION"
            )

            current_zone_id = None

            exclude_zone = ""


        else:

            request_type = (
                "RELOCATION"
            )

            current_zone_id = str(
                active[
                    "zone_id"
                ]
            )

            # A relocation recommendation should not simply recommend
            # the zone where the vendor is already allocated.
            exclude_zone = (
                current_zone_id
            )


        vendor_type = str(
            profile.get(
                "vendor_type"
            )
            or ""
        )


        # Only imported historical vendors have historical evidence rows
        # whose own location-group evidence needs to be excluded.
        historical_vendor_id = (

            vendor_id

            if (
                vendor_type
                == "EXISTING_IMPORTED"
            )

            else ""
        )


        weight_policy = (
            derive_mcda_weights(
                profile
            )
        )


        effective_weights = (
            weight_policy[
                "final_weights"
            ]
        )


        demand = AllocationDemand(

            vendor_id=vendor_id,

            business=business,

            preferred_division=(
                preferred_division
            ),

            request_type=(
                request_type
            ),

            historical_vendor_id=(
                historical_vendor_id
            ),

            exclude_zone=(
                exclude_zone
            ),

            factor_weights=(
                effective_weights
            ),
        )


        context = (
            VendorPlanningContext(

                vendor_id=vendor_id,

                application_vendor_id=(
                    profile.get(
                        "application_vendor_id"
                    )
                ),

                vendor_type=(
                    vendor_type
                ),

                full_name=(
                    profile.get(
                        "full_name"
                    )
                ),

                business_name=(
                    profile.get(
                        "business_name"
                    )
                ),

                business_category=(
                    business
                ),

                preferred_division=(
                    preferred_division
                ),

                priority_profile=str(
                    profile.get(
                        "priority_profile"
                    )
                    or "BALANCED"
                ),

                request_type=(
                    request_type
                ),

                current_zone_id=(
                    current_zone_id
                ),

                historical_evidence_vendor_id=(

                    historical_vendor_id

                    or None
                ),

                weight_source=str(
                    weight_policy.get(
                        "weight_source"
                    )
                    or "UNKNOWN"
                ),

                effective_factor_weights={
                    key: float(
                        value
                    )
                    for key, value
                    in effective_weights.items()
                },
            )
        )


        demands.append(
            demand
        )

        contexts.append(
            context
        )


    return (
        demands,
        contexts,
        skipped,
        warnings,
    )


# ---------------------------------------------------------------------------
# Production planning entry point
# ---------------------------------------------------------------------------


def plan_vendor_allocations(
    vendor_ids: Sequence[str],
    *,
    database_path: str | Path = (
        DATABASE_PATH
    ),
    require_verified: bool = True,
    candidate_pool_size: (
        int
        | None
    ) = None,
    reject_pending_requests: bool = True,
    max_vendors: int = 500,
    time_limit_seconds: (
        float
        | None
    ) = 30.0,
) -> BatchPlanningResult:
    """Generate a read-only production-style allocation plan.

    Workflow:

        Vendor profiles
            ↓
        Current operational state
            ↓
        Vendor-specific MCDA policy
            ↓
        MCDA candidate scoring
            ↓
        Goal Programming allocation
            ↓
        Advisory allocation plan

    No database allocation is committed.
    """

    (
        demands,
        contexts,
        skipped,
        warnings,

    ) = build_allocation_demands(

        vendor_ids,

        database_path=(
            database_path
        ),

        reject_pending_requests=(
            reject_pending_requests
        ),
    )


    if not demands:

        raise (
            AllocationPlanningValidationError(
                "No vendors remain eligible for planning"
            )
        )


    config = OptimizationConfig(

        require_verified=(
            require_verified
        ),

        candidate_pool_size=(
            candidate_pool_size
        ),

        max_vendors=(
            max_vendors
        ),

        time_limit_seconds=(
            time_limit_seconds
        ),
    )


    plan = optimize_allocations(

        demands,

        database_path=(
            database_path
        ),

        config=(
            config
        ),
    )


    if plan.unassigned_count:

        warnings.append(
            f"{plan.unassigned_count} vendor(s) could not be "
            "assigned under the current verified capacity "
            "and eligibility constraints."
        )


    if plan.fallback_assignment_count:

        warnings.append(
            f"{plan.fallback_assignment_count} assignment(s) "
            "fall outside the vendor's preferred division."
        )


    if not require_verified:

        warnings.append(
            "Verified live availability was not required for this run; "
            "this mode is suitable for research/demo planning only."
        )


    return BatchPlanningResult(

        plan=(
            plan
        ),

        vendor_context=tuple(
            contexts
        ),

        skipped_vendor_ids=tuple(
            skipped
        ),

        warnings=tuple(
            warnings
        ),
    )