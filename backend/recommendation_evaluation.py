"""Recommendation robustness and MCDA sensitivity evaluation.

This module evaluates whether recommendation rankings remain stable when the
MCDA factor weights are reasonably perturbed.

It does NOT:
- generate suitability labels,
- claim predictive accuracy,
- modify production recommendations,
- or infer that a recommendation is objectively correct.

It provides evidence about robustness of the ranking policy.

Main metrics
------------
Top-K retention
    Fraction of baseline Top-K zones still present after perturbation.

Top-K Jaccard
    Set similarity between baseline and perturbed Top-K.

Top-1 stability
    Whether the first-ranked zone remains unchanged.

Rank correlation
    Correlation between full candidate rankings.

Mean / maximum rank shift
    How much candidate positions change.

Weight-distance
    Magnitude of the perturbation from the baseline policy.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

try:
    from .decision_policy import (
        FACTOR_ORDER,
        derive_mcda_weights,
        normalize_weights,
    )
    from .mcda_engine import (
        ROOT,
        rank_candidates,
        score_candidates,
    )
except ImportError:  # Supports direct execution.
    from decision_policy import (
        FACTOR_ORDER,
        derive_mcda_weights,
        normalize_weights,
    )
    from mcda_engine import (
        ROOT,
        rank_candidates,
        score_candidates,
    )


DEFAULT_REPORT_DIR = (
    ROOT
    / "reports"
    / "recommendation_evaluation"
)


@dataclass(frozen=True)
class SensitivityConfig:
    """Configuration for deterministic and Monte-Carlo sensitivity tests."""

    top_n: int = 3

    # Relative one-at-a-time perturbations.
    #
    # Example:
    # 0.10 means a factor weight is multiplied by 0.90 or 1.10,
    # then all weights are renormalized.
    one_at_a_time_deltas: tuple[float, ...] = (
        0.10,
        0.20,
    )

    # Number of reproducible random scenarios.
    monte_carlo_samples: int = 200

    # Each raw weight receives a multiplier sampled uniformly from:
    #
    # [1 - monte_carlo_delta, 1 + monte_carlo_delta]
    #
    # and the complete vector is then normalized.
    monte_carlo_delta: float = 0.20

    random_seed: int = 42


@dataclass(frozen=True)
class ScenarioMetrics:
    """Robustness metrics for one perturbed weight scenario."""

    scenario_id: str
    scenario_type: str
    changed_factor: str | None
    perturbation: float | None

    top1_same: bool
    ordered_top_k_same: bool

    top_k_retention: float
    top_k_jaccard: float

    rank_correlation: float | None

    mean_absolute_rank_shift: float | None
    max_absolute_rank_shift: int | None

    weight_l1_distance: float

    top_zone_id: str | None
    top_zone_score: float | None


# ---------------------------------------------------------------------------
# General validation
# ---------------------------------------------------------------------------


def _validate_config(
    config: SensitivityConfig,
) -> None:
    """Validate sensitivity configuration."""

    if (
        config.top_n < 1
        or config.top_n > 20
    ):
        raise ValueError(
            "top_n must be between 1 and 20"
        )

    if config.monte_carlo_samples < 0:
        raise ValueError(
            "monte_carlo_samples must be nonnegative"
        )

    if not (
        0.0
        <= config.monte_carlo_delta
        < 1.0
    ):
        raise ValueError(
            "monte_carlo_delta must be >= 0 and < 1"
        )

    for delta in (
        config.one_at_a_time_deltas
    ):
        if not (
            0.0 < delta < 1.0
        ):
            raise ValueError(
                "one-at-a-time perturbations "
                "must be > 0 and < 1"
            )


# ---------------------------------------------------------------------------
# Weight scenario generation
# ---------------------------------------------------------------------------


def _multiply_factor(
    base_weights: Mapping[str, float],
    factor: str,
    multiplier: float,
) -> dict[str, float]:
    """Multiply one factor and renormalize the full policy."""

    if factor not in FACTOR_ORDER:
        raise ValueError(
            f"Unknown factor: {factor}"
        )

    if multiplier <= 0:
        raise ValueError(
            "Weight multiplier must be positive"
        )

    adjusted = dict(
        base_weights
    )

    adjusted[factor] *= multiplier

    return normalize_weights(
        adjusted
    )


def generate_weight_scenarios(
    base_weights: Mapping[str, float],
    config: SensitivityConfig | None = None,
) -> list[dict[str, Any]]:
    """Generate deterministic and reproducible sensitivity scenarios."""

    config = (
        config
        or SensitivityConfig()
    )

    _validate_config(
        config
    )

    base = normalize_weights(
        base_weights
    )

    scenarios: list[
        dict[str, Any]
    ] = []


    # -----------------------------------------------------------------------
    # One-factor-at-a-time perturbation
    # -----------------------------------------------------------------------

    for factor in FACTOR_ORDER:

        for delta in (
            config.one_at_a_time_deltas
        ):

            for direction in (
                -1,
                1,
            ):

                signed_delta = (
                    direction
                    * delta
                )

                multiplier = (
                    1.0
                    + signed_delta
                )

                weights = (
                    _multiply_factor(
                        base,
                        factor,
                        multiplier,
                    )
                )

                sign = (
                    "plus"
                    if direction > 0
                    else "minus"
                )

                percentage = int(
                    round(
                        delta
                        * 100
                    )
                )

                scenarios.append(
                    {
                        "scenario_id": (
                            f"OAT_{factor}_"
                            f"{sign}{percentage}"
                        ),
                        "scenario_type":
                            "ONE_AT_A_TIME",
                        "changed_factor":
                            factor,
                        "perturbation":
                            signed_delta,
                        "weights":
                            weights,
                    }
                )


    # -----------------------------------------------------------------------
    # Monte-Carlo perturbation
    # -----------------------------------------------------------------------

    if (
        config.monte_carlo_samples
        > 0
        and config.monte_carlo_delta
        > 0
    ):

        rng = (
            np.random.default_rng(
                config.random_seed
            )
        )

        for index in range(
            config.monte_carlo_samples
        ):

            multipliers = rng.uniform(
                low=(
                    1.0
                    - config.monte_carlo_delta
                ),
                high=(
                    1.0
                    + config.monte_carlo_delta
                ),
                size=len(
                    FACTOR_ORDER
                ),
            )

            raw = {
                factor: (
                    base[factor]
                    * float(
                        multipliers[
                            position
                        ]
                    )
                )
                for position, factor
                in enumerate(
                    FACTOR_ORDER
                )
            }

            weights = normalize_weights(
                raw
            )

            scenarios.append(
                {
                    "scenario_id":
                        f"MC_{index + 1:04d}",
                    "scenario_type":
                        "MONTE_CARLO",
                    "changed_factor":
                        None,
                    "perturbation":
                        None,
                    "weights":
                        weights,
                }
            )

    return scenarios


# ---------------------------------------------------------------------------
# Re-score an unchanged candidate snapshot
# ---------------------------------------------------------------------------


def _rescore_existing_factors(
    scored: pd.DataFrame,
    weights: Mapping[str, float],
) -> pd.DataFrame:
    """Recalculate MCDA scores using already-computed factor values.

    This is important methodologically:

    sensitivity analysis changes ONLY the weights.

    It does not:
    - reload GIS data,
    - re-run geocoding,
    - change live availability,
    - change historical evidence,
    - or alter the candidate universe.

    Therefore observed ranking changes can be attributed to the weight change.
    """

    normalized = normalize_weights(
        weights
    )

    result = scored.copy(
        deep=True
    )

    numerator = pd.Series(
        0.0,
        index=result.index,
        dtype=float,
    )

    denominator = pd.Series(
        0.0,
        index=result.index,
        dtype=float,
    )

    factor_values: dict[
        str,
        pd.Series,
    ] = {}


    for factor in FACTOR_ORDER:

        column = (
            f"{factor}_score"
        )

        if column not in result.columns:
            raise ValueError(
                "Scored candidate table "
                f"is missing {column}"
            )

        values = pd.to_numeric(
            result[column],
            errors="coerce",
        )

        factor_values[
            factor
        ] = values

        valid = values.notna()

        numerator = (
            numerator
            + values.fillna(
                0.0
            )
            * normalized[
                factor
            ]
        )

        denominator = (
            denominator
            + valid.astype(float)
            * normalized[
                factor
            ]
        )


    safe_denominator = (
        denominator.replace(
            0.0,
            np.nan,
        )
    )


    result[
        "score"
    ] = (
        100.0
        * numerator
        / safe_denominator
    )

    result[
        "score_coverage"
    ] = denominator


    for factor in FACTOR_ORDER:

        result[
            f"{factor}_contribution"
        ] = (
            100.0
            * factor_values[
                factor
            ].fillna(
                0.0
            )
            * normalized[
                factor
            ]
            / safe_denominator
        )


    result = result.sort_values(
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


    metadata = dict(
        scored.attrs
    )

    metadata[
        "effective_factor_weights"
    ] = dict(
        normalized
    )

    result.attrs.update(
        metadata
    )

    return result


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------


def _zone_ids(
    frame: pd.DataFrame,
) -> list[str]:
    """Extract deterministic zone IDs."""

    if frame.empty:
        return []

    return (
        frame[
            "zone_id"
        ]
        .astype(str)
        .tolist()
    )


def _rank_positions(
    scored: pd.DataFrame,
) -> dict[str, int]:
    """Create 1-based positions from a fully sorted candidate table."""

    return {
        str(zone_id):
            index + 1
        for index, zone_id
        in enumerate(
            scored[
                "zone_id"
            ].tolist()
        )
    }


def _rank_metrics(
    baseline_scored: pd.DataFrame,
    scenario_scored: pd.DataFrame,
) -> tuple[
    float | None,
    float | None,
    int | None,
]:
    """Calculate full-ranking correlation and displacement metrics."""

    baseline = _rank_positions(
        baseline_scored
    )

    scenario = _rank_positions(
        scenario_scored
    )

    common = sorted(
        set(
            baseline
        )
        & set(
            scenario
        )
    )


    if len(common) < 2:
        return (
            None,
            None,
            None,
        )


    baseline_ranks = np.asarray(
        [
            baseline[
                zone_id
            ]
            for zone_id in common
        ],
        dtype=float,
    )

    scenario_ranks = np.asarray(
        [
            scenario[
                zone_id
            ]
            for zone_id in common
        ],
        dtype=float,
    )


    # Because ranking positions are already ranks, Pearson correlation
    # between these vectors is equivalent to Spearman correlation here.

    if (
        np.std(
            baseline_ranks
        )
        == 0
        or np.std(
            scenario_ranks
        )
        == 0
    ):
        correlation = None

    else:
        correlation = float(
            np.corrcoef(
                baseline_ranks,
                scenario_ranks,
            )[
                0,
                1,
            ]
        )


    shifts = np.abs(
        baseline_ranks
        - scenario_ranks
    )


    mean_shift = float(
        np.mean(
            shifts
        )
    )

    max_shift = int(
        np.max(
            shifts
        )
    )


    return (
        correlation,
        mean_shift,
        max_shift,
    )


def _top_k_metrics(
    baseline_top: Sequence[str],
    scenario_top: Sequence[str],
) -> tuple[
    float,
    float,
]:
    """Return Top-K retention and Jaccard similarity."""

    baseline_set = set(
        baseline_top
    )

    scenario_set = set(
        scenario_top
    )


    if not baseline_set:
        return (
            1.0
            if not scenario_set
            else 0.0,
            1.0
            if not scenario_set
            else 0.0,
        )


    intersection = (
        baseline_set
        & scenario_set
    )

    union = (
        baseline_set
        | scenario_set
    )


    retention = (
        len(
            intersection
        )
        / len(
            baseline_set
        )
    )


    jaccard = (
        len(
            intersection
        )
        / len(
            union
        )
        if union
        else 1.0
    )


    return (
        float(
            retention
        ),
        float(
            jaccard
        ),
    )


def _weight_distance(
    baseline: Mapping[str, float],
    scenario: Mapping[str, float],
) -> float:
    """L1 distance between two normalized weight vectors."""

    return float(
        sum(
            abs(
                baseline[
                    factor
                ]
                - scenario[
                    factor
                ]
            )
            for factor
            in FACTOR_ORDER
        )
    )


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def evaluate_weight_sensitivity(
    business: str,
    division: str = "",
    vendor_id: str = "",
    exclude_zone: str = "",
    *,
    vendor_profile: Mapping[
        str,
        Any,
    ]
    | None = None,
    base_weights: Mapping[
        str,
        float,
    ]
    | None = None,
    require_verified: bool = False,
    use_live_status: bool = False,
    database_path=None,
    config: SensitivityConfig | None = None,
) -> dict[str, Any]:
    """Evaluate ranking robustness for one recommendation request.

    The candidate snapshot and factor scores are calculated once.

    Every sensitivity scenario then reuses that same snapshot, guaranteeing
    that the experiment measures weight sensitivity rather than data changes.
    """

    config = (
        config
        or SensitivityConfig()
    )

    _validate_config(
        config
    )


    # -----------------------------------------------------------------------
    # Determine effective baseline weights
    # -----------------------------------------------------------------------

    if base_weights is None:

        policy = derive_mcda_weights(
            vendor_profile
        )

        baseline_weights = (
            policy[
                "final_weights"
            ]
        )

        weight_source = (
            policy[
                "weight_source"
            ]
        )

        ahp_consistency_ratio = (
            policy[
                "ahp_consistency_ratio"
            ]
        )

    else:

        baseline_weights = (
            normalize_weights(
                base_weights
            )
        )

        weight_source = (
            "CALLER_SUPPLIED"
        )

        ahp_consistency_ratio = None


    # -----------------------------------------------------------------------
    # Calculate one fixed candidate/factor snapshot
    # -----------------------------------------------------------------------

    baseline_scored = (
        score_candidates(
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
                baseline_weights
            ),
        )
    )


    effective_business = str(
        baseline_scored.attrs.get(
            "business",
            business,
        )
        or ""
    )

    effective_division = str(
        baseline_scored.attrs.get(
            "division",
            division,
        )
        or ""
    )


    baseline_top_frame = (
        rank_candidates(
            baseline_scored,
            division=(
                effective_division
            ),
            top_n=(
                config.top_n
            ),
        )
    )


    baseline_top = _zone_ids(
        baseline_top_frame
    )


    scenarios = (
        generate_weight_scenarios(
            baseline_weights,
            config,
        )
    )


    metric_rows: list[
        dict[str, Any]
    ] = []

    top_k_rows: list[
        dict[str, Any]
    ] = []


    # -----------------------------------------------------------------------
    # Evaluate each scenario
    # -----------------------------------------------------------------------

    for scenario in scenarios:

        scenario_weights = (
            scenario[
                "weights"
            ]
        )


        scenario_scored = (
            _rescore_existing_factors(
                baseline_scored,
                scenario_weights,
            )
        )


        scenario_top_frame = (
            rank_candidates(
                scenario_scored,
                division=(
                    effective_division
                ),
                top_n=(
                    config.top_n
                ),
            )
        )


        scenario_top = (
            _zone_ids(
                scenario_top_frame
            )
        )


        (
            retention,
            jaccard,

        ) = _top_k_metrics(

            baseline_top,
            scenario_top,
        )


        (
            correlation,
            mean_shift,
            max_shift,

        ) = _rank_metrics(

            baseline_scored,
            scenario_scored,
        )


        top1_same = bool(

            baseline_top
            and scenario_top
            and baseline_top[0]
            == scenario_top[0]

        ) or (
            not baseline_top
            and not scenario_top
        )


        ordered_top_k_same = (
            baseline_top
            == scenario_top
        )


        if (
            scenario_top_frame.empty
        ):

            top_zone_id = None
            top_zone_score = None

        else:

            first = (
                scenario_top_frame.iloc[
                    0
                ]
            )

            top_zone_id = str(
                first[
                    "zone_id"
                ]
            )

            top_zone_score = float(
                first[
                    "score"
                ]
            )


        metrics = ScenarioMetrics(

            scenario_id=(
                scenario[
                    "scenario_id"
                ]
            ),

            scenario_type=(
                scenario[
                    "scenario_type"
                ]
            ),

            changed_factor=(
                scenario[
                    "changed_factor"
                ]
            ),

            perturbation=(
                scenario[
                    "perturbation"
                ]
            ),

            top1_same=(
                top1_same
            ),

            ordered_top_k_same=(
                ordered_top_k_same
            ),

            top_k_retention=(
                retention
            ),

            top_k_jaccard=(
                jaccard
            ),

            rank_correlation=(
                correlation
            ),

            mean_absolute_rank_shift=(
                mean_shift
            ),

            max_absolute_rank_shift=(
                max_shift
            ),

            weight_l1_distance=(
                _weight_distance(
                    baseline_weights,
                    scenario_weights,
                )
            ),

            top_zone_id=(
                top_zone_id
            ),

            top_zone_score=(
                top_zone_score
            ),
        )


        row = asdict(
            metrics
        )


        for factor in FACTOR_ORDER:

            row[
                f"weight_{factor}"
            ] = (
                scenario_weights[
                    factor
                ]
            )


        metric_rows.append(
            row
        )


        for position, (
            _,
            recommendation,
        ) in enumerate(
            scenario_top_frame.iterrows(),
            start=1,
        ):

            top_k_rows.append(
                {
                    "scenario_id":
                        scenario[
                            "scenario_id"
                        ],

                    "scenario_type":
                        scenario[
                            "scenario_type"
                        ],

                    "rank":
                        position,

                    "zone_id":
                        str(
                            recommendation[
                                "zone_id"
                            ]
                        ),

                    "score":
                        float(
                            recommendation[
                                "score"
                            ]
                        ),

                    "zone_division":
                        recommendation.get(
                            "zone_division"
                        ),

                    "fallback_used":
                        bool(
                            recommendation.get(
                                "fallback_used",
                                False,
                            )
                        ),
                }
            )


    metrics_frame = pd.DataFrame(
        metric_rows
    )


    top_k_frame = pd.DataFrame(
        top_k_rows
    )


    # -----------------------------------------------------------------------
    # Summary statistics
    # -----------------------------------------------------------------------

    if metrics_frame.empty:

        summary_metrics = {

            "scenario_count": 0,

            "top1_stability_rate": None,

            "ordered_top_k_stability_rate":
                None,

            "mean_top_k_retention": None,

            "minimum_top_k_retention": None,

            "mean_top_k_jaccard": None,

            "minimum_top_k_jaccard": None,

            "mean_rank_correlation": None,

            "minimum_rank_correlation": None,

            "mean_absolute_rank_shift": None,

            "maximum_rank_shift": None,
        }


    else:

        rank_correlations = (
            pd.to_numeric(
                metrics_frame[
                    "rank_correlation"
                ],
                errors="coerce",
            )
        )


        mean_shifts = (
            pd.to_numeric(
                metrics_frame[
                    "mean_absolute_rank_shift"
                ],
                errors="coerce",
            )
        )


        max_shifts = (
            pd.to_numeric(
                metrics_frame[
                    "max_absolute_rank_shift"
                ],
                errors="coerce",
            )
        )


        summary_metrics = {

            "scenario_count":
                int(
                    len(
                        metrics_frame
                    )
                ),

            "top1_stability_rate":
                float(
                    metrics_frame[
                        "top1_same"
                    ].mean()
                ),

            "ordered_top_k_stability_rate":
                float(
                    metrics_frame[
                        "ordered_top_k_same"
                    ].mean()
                ),

            "mean_top_k_retention":
                float(
                    metrics_frame[
                        "top_k_retention"
                    ].mean()
                ),

            "minimum_top_k_retention":
                float(
                    metrics_frame[
                        "top_k_retention"
                    ].min()
                ),

            "mean_top_k_jaccard":
                float(
                    metrics_frame[
                        "top_k_jaccard"
                    ].mean()
                ),

            "minimum_top_k_jaccard":
                float(
                    metrics_frame[
                        "top_k_jaccard"
                    ].min()
                ),

            "mean_rank_correlation":
                (
                    float(
                        rank_correlations.mean()
                    )
                    if rank_correlations.notna().any()
                    else None
                ),

            "minimum_rank_correlation":
                (
                    float(
                        rank_correlations.min()
                    )
                    if rank_correlations.notna().any()
                    else None
                ),

            "mean_absolute_rank_shift":
                (
                    float(
                        mean_shifts.mean()
                    )
                    if mean_shifts.notna().any()
                    else None
                ),

            "maximum_rank_shift":
                (
                    int(
                        max_shifts.max()
                    )
                    if max_shifts.notna().any()
                    else None
                ),
        }


    baseline_recommendations = [

        {
            "rank":
                int(
                    row[
                        "rank"
                    ]
                ),

            "zone_id":
                str(
                    row[
                        "zone_id"
                    ]
                ),

            "zone_division":
                row.get(
                    "zone_division"
                ),

            "score":
                float(
                    row[
                        "score"
                    ]
                ),

            "fallback_used":
                bool(
                    row.get(
                        "fallback_used",
                        False,
                    )
                ),
        }

        for _, row
        in baseline_top_frame.iterrows()
    ]


    report = {

        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "evaluation_type":
            "MCDA_WEIGHT_SENSITIVITY",

        "interpretation":
            (
                "Measures ranking robustness to "
                "weight perturbation. It does not "
                "measure predictive accuracy or "
                "real-world business success."
            ),

        "request": {

            "business":
                effective_business,

            "division":
                effective_division,

            "vendor_id":
                vendor_id,

            "exclude_zone":
                exclude_zone,

            "require_verified":
                bool(
                    require_verified
                ),

            "use_live_status":
                bool(
                    use_live_status
                ),

            "top_n":
                config.top_n,
        },

        "candidate_snapshot": {

            "candidate_count":
                int(
                    len(
                        baseline_scored
                    )
                ),

            "candidate_count_before_live_filter":
                baseline_scored.attrs.get(
                    "candidate_count_before_live_filter"
                ),

            "candidate_count_after_live_filter":
                baseline_scored.attrs.get(
                    "candidate_count_after_live_filter"
                ),

            "candidate_count_after_verified_filter":
                baseline_scored.attrs.get(
                    "candidate_count_after_verified_filter"
                ),
        },

        "weight_policy": {

            "source":
                weight_source,

            "ahp_consistency_ratio":
                ahp_consistency_ratio,

            "baseline_weights":
                dict(
                    baseline_weights
                ),
        },

        "sensitivity_configuration":
            asdict(
                config
            ),

        "baseline_recommendations":
            baseline_recommendations,

        "summary":
            summary_metrics,

        # DataFrames remain available to callers but are intentionally
        # excluded from JSON serialization below.
        "scenario_metrics":
            metrics_frame,

        "scenario_top_k":
            top_k_frame,
    }


    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _json_safe_report(
    report: Mapping[
        str,
        Any,
    ],
) -> dict[str, Any]:
    """Return the JSON-serializable portion of an evaluation report."""

    return {

        key: value

        for key, value
        in report.items()

        if key not in {
            "scenario_metrics",
            "scenario_top_k",
        }
    }


def save_evaluation_report(
    report: Mapping[str, Any],
    *,
    report_dir: str | Path = (
        DEFAULT_REPORT_DIR
    ),
    prefix: str = "mcda_sensitivity",
) -> dict[str, Path]:
    """Save JSON summary and detailed CSV evidence atomically."""

    target_dir = Path(
        report_dir
    )

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    summary_path = (
        target_dir
        / f"{prefix}_summary.json"
    )

    scenarios_path = (
        target_dir
        / f"{prefix}_scenarios.csv"
    )

    top_k_path = (
        target_dir
        / f"{prefix}_top_k.csv"
    )


    summary_temp = (
        summary_path.with_suffix(
            summary_path.suffix
            + ".tmp"
        )
    )

    scenarios_temp = (
        scenarios_path.with_suffix(
            scenarios_path.suffix
            + ".tmp"
        )
    )

    top_k_temp = (
        top_k_path.with_suffix(
            top_k_path.suffix
            + ".tmp"
        )
    )


    summary_temp.write_text(

        json.dumps(
            _json_safe_report(
                report
            ),
            indent=2,
            ensure_ascii=False,
        ),

        encoding="utf-8",
    )


    metrics = report.get(
        "scenario_metrics"
    )

    if not isinstance(
        metrics,
        pd.DataFrame,
    ):
        raise ValueError(
            "report is missing scenario_metrics"
        )


    top_k = report.get(
        "scenario_top_k"
    )

    if not isinstance(
        top_k,
        pd.DataFrame,
    ):
        raise ValueError(
            "report is missing scenario_top_k"
        )


    metrics.to_csv(
        scenarios_temp,
        index=False,
        encoding="utf-8-sig",
    )


    top_k.to_csv(
        top_k_temp,
        index=False,
        encoding="utf-8-sig",
    )


    summary_temp.replace(
        summary_path
    )

    scenarios_temp.replace(
        scenarios_path
    )

    top_k_temp.replace(
        top_k_path
    )


    return {

        "summary":
            summary_path,

        "scenarios":
            scenarios_path,

        "top_k":
            top_k_path,
    }


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------


def print_evaluation_summary(
    report: Mapping[str, Any],
) -> None:
    """Print a concise human-readable robustness summary."""

    summary = report[
        "summary"
    ]

    policy = report[
        "weight_policy"
    ]

    request = report[
        "request"
    ]


    print(
        "\nMCDA Weight Sensitivity Evaluation"
    )

    print(
        "=" * 38
    )

    print(
        "Business:",
        request[
            "business"
        ],
    )

    print(
        "Division:",
        request[
            "division"
        ]
        or "Any",
    )

    print(
        "Weight source:",
        policy[
            "source"
        ],
    )

    print(
        "Scenarios:",
        summary[
            "scenario_count"
        ],
    )


    baseline = report[
        "baseline_recommendations"
    ]


    if baseline:

        print(
            "\nBaseline Top "
            f"{len(baseline)}:"
        )

        for row in baseline:

            print(
                f"  {row['rank']}. "
                f"{row['zone_id']} "
                f"({row['score']:.3f})"
            )


    else:

        print(
            "\nBaseline produced no eligible candidates."
        )


    print(
        "\nRobustness indicators:"
    )


    def show_percent(
        label: str,
        value,
    ) -> None:

        if value is None:

            print(
                f"  {label}: N/A"
            )

        else:

            print(
                f"  {label}: "
                f"{100.0 * value:.2f}%"
            )


    show_percent(
        "Top-1 stability",
        summary[
            "top1_stability_rate"
        ],
    )

    show_percent(
        "Exact ordered Top-K stability",
        summary[
            "ordered_top_k_stability_rate"
        ],
    )

    show_percent(
        "Mean Top-K retention",
        summary[
            "mean_top_k_retention"
        ],
    )

    show_percent(
        "Minimum Top-K retention",
        summary[
            "minimum_top_k_retention"
        ],
    )


    correlation = (
        summary[
            "mean_rank_correlation"
        ]
    )


    print(
        "  Mean full-ranking correlation:",
        (
            f"{correlation:.4f}"
            if correlation is not None
            else "N/A"
        ),
    )


    minimum_correlation = (
        summary[
            "minimum_rank_correlation"
        ]
    )


    print(
        "  Minimum full-ranking correlation:",
        (
            f"{minimum_correlation:.4f}"
            if minimum_correlation is not None
            else "N/A"
        ),
    )


    mean_shift = (
        summary[
            "mean_absolute_rank_shift"
        ]
    )


    print(
        "  Mean absolute rank shift:",
        (
            f"{mean_shift:.3f}"
            if mean_shift is not None
            else "N/A"
        ),
    )


    print(
        "  Maximum observed rank shift:",
        (
            summary[
                "maximum_rank_shift"
            ]
            if summary[
                "maximum_rank_shift"
            ]
            is not None
            else "N/A"
        ),
    )


    print(
        "\nInterpretation: these metrics assess "
        "sensitivity to the weight policy; "
        "they are not prediction accuracy."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate MCDA recommendation "
            "robustness under weight perturbation."
        )
    )


    parser.add_argument(
        "--business",
        required=True,
        help=(
            "Canonical business category, "
            "for example food"
        ),
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
        "--monte-carlo-samples",
        type=int,
        default=200,
    )


    parser.add_argument(
        "--monte-carlo-delta",
        type=float,
        default=0.20,
    )


    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )


    parser.add_argument(
        "--require-verified",
        action="store_true",
    )


    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Use the operational live-zone "
            "snapshot when building the fixed "
            "candidate set."
        ),
    )


    parser.add_argument(
        "--no-save",
        action="store_true",
    )


    args = parser.parse_args()


    config = SensitivityConfig(

        top_n=args.top_n,

        monte_carlo_samples=(
            args.monte_carlo_samples
        ),

        monte_carlo_delta=(
            args.monte_carlo_delta
        ),

        random_seed=(
            args.seed
        ),
    )


    report = evaluate_weight_sensitivity(

        business=args.business,

        division=args.division,

        vendor_id=args.vendor_id,

        exclude_zone=args.exclude_zone,

        require_verified=(
            args.require_verified
        ),

        use_live_status=(
            args.live
        ),

        config=config,
    )


    print_evaluation_summary(
        report
    )


    if not args.no_save:

        paths = (
            save_evaluation_report(
                report
            )
        )


        print(
            "\nSaved:"
        )

        for name, path in (
            paths.items()
        ):

            print(
                f"  {name}: {path}"
            )


if __name__ == "__main__":
    main()