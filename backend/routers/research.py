"""Research HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.mcda_engine import DATA
from backend.decision_policy import DEFAULT_POLICY_PATH
from backend.decision_policy import FACTOR_ORDER
from backend.decision_policy import RESEARCH_BASELINE_WEIGHTS
from backend.mcda_engine import ROOT
from backend.core.serialization import _csv_row_count
from backend.core.serialization import _read_json
from backend.core.serialization import clean
from backend.decision_policy import load_base_weight_policy
import numpy as np
import pandas as pd
from fastapi import APIRouter
router = APIRouter()

@router.get(
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

@router.get(
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

@router.get(
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

@router.get(
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
