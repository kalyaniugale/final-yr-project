"""Recommendations HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.schemas.api import Request
from backend.recommendation_evaluation import SensitivityConfig
from backend.schemas.api import SensitivityRequest
from backend.core.serialization import clean
from backend.recommendation_evaluation import evaluate_weight_sensitivity
from backend.services.explanations import explain
from backend.mcda_engine import recommend
from backend.services.recommendation_context import resolve_recommendation_context
from fastapi import APIRouter
router = APIRouter()

@router.post(
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
            database_path=dependencies.DATABASE_PATH,
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

@router.post(
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
                    dependencies.DATABASE_PATH
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
