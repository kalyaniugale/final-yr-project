"""Expert AHP calibration for MCDA factor weights.

This module converts independent expert pairwise judgements into a reviewed
MCDA weight policy.

Workflow
--------
1. Generate a pairwise-comparison CSV template.
2. Each expert completes all 15 factor comparisons.
3. Validate completeness and Saaty-scale values.
4. Calculate each expert's AHP consistency ratio.
5. Reject or exclude inconsistent expert matrices.
6. Aggregate consistent experts using geometric mean.
7. Save the reviewed policy using decision_policy.save_ahp_policy().

The resulting weights are policy/expert-derived weights. They are not learned
ML coefficients and must not be described as predictive probabilities.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

try:
    from .decision_policy import (
        DEFAULT_POLICY_PATH,
        FACTOR_ORDER,
        AhpResult,
        aggregate_ahp_matrices,
        calculate_ahp_weights,
        save_ahp_policy,
    )

except ImportError:
    from decision_policy import (
        DEFAULT_POLICY_PATH,
        FACTOR_ORDER,
        AhpResult,
        aggregate_ahp_matrices,
        calculate_ahp_weights,
        save_ahp_policy,
    )


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_AHP_DIR = (
    ROOT
    / "reports"
    / "ahp_calibration"
)

DEFAULT_TEMPLATE_PATH = (
    DEFAULT_AHP_DIR
    / "expert_pairwise_template.csv"
)

DEFAULT_REVIEW_PATH = (
    DEFAULT_AHP_DIR
    / "expert_pairwise_reviews.csv"
)

DEFAULT_REPORT_PATH = (
    DEFAULT_AHP_DIR
    / "ahp_calibration_report.json"
)


FACTOR_LABELS = {
    "business":
        "Business Compatibility",

    "commercial":
        "Commercial Surroundings",

    "access":
        "Road and Transport Access",

    "facilities":
        "Nearby Facilities",

    "preference":
        "Preferred Division",

    "historical":
        "Historical Evidence",
}


# Standard Saaty scale values.
#
# Reciprocal values are permitted as fractions/decimals.
SAATY_VALUES = (
    1 / 9,
    1 / 8,
    1 / 7,
    1 / 6,
    1 / 5,
    1 / 4,
    1 / 3,
    1 / 2,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
)


@dataclass(frozen=True)
class ExpertAhpEvaluation:
    """Consistency result for one expert."""

    expert_id: str

    consistency_ratio: float

    consistency_index: float

    lambda_max: float

    is_consistent: bool

    weights: dict[
        str,
        float,
    ]


@dataclass(frozen=True)
class AhpCalibrationResult:
    """Final multi-expert calibration result."""

    included_experts: tuple[str, ...]

    excluded_experts: tuple[str, ...]

    expert_results: tuple[
        ExpertAhpEvaluation,
        ...
    ]

    aggregate_result: AhpResult

    expert_count: int

    consistent_expert_count: int

    consistency_threshold: float

    policy_path: str | None


# ---------------------------------------------------------------------------
# Pair definitions
# ---------------------------------------------------------------------------


def factor_pairs() -> list[
    tuple[
        str,
        str,
    ]
]:
    """Return all unique AHP criterion pairs."""

    pairs: list[
        tuple[
            str,
            str,
        ]
    ] = []

    for i, factor_a in enumerate(
        FACTOR_ORDER
    ):

        for factor_b in (
            FACTOR_ORDER[
                i + 1:
            ]
        ):

            pairs.append(
                (
                    factor_a,
                    factor_b,
                )
            )

    return pairs


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def create_template(
    path: str | Path = (
        DEFAULT_TEMPLATE_PATH
    ),
    *,
    expert_ids: Iterable[str] | None = None,
) -> Path:
    """Create an expert comparison template.

    comparison_value means:

        1   -> equally important
        3   -> factor_a moderately more important
        5   -> factor_a strongly more important
        7   -> factor_a very strongly more important
        9   -> factor_a extremely more important

    Reciprocal values indicate factor_b is preferred:

        1/3 -> factor_b moderately more important
        1/5 -> factor_b strongly more important

    2,4,6,8 are intermediate values.
    """

    target = Path(
        path
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    experts = list(
        expert_ids
        or [
            "EXPERT_01",
        ]
    )


    rows: list[
        dict[
            str,
            Any,
        ]
    ] = []


    for expert_id in experts:

        expert_id = str(
            expert_id
        ).strip()


        if not expert_id:

            raise ValueError(
                "expert_id must not be empty"
            )


        for (
            factor_a,
            factor_b,

        ) in factor_pairs():

            rows.append(
                {
                    "expert_id":
                        expert_id,

                    "factor_a":
                        factor_a,

                    "factor_a_label":
                        FACTOR_LABELS[
                            factor_a
                        ],

                    "factor_b":
                        factor_b,

                    "factor_b_label":
                        FACTOR_LABELS[
                            factor_b
                        ],

                    "comparison_value":
                        "",

                    "reason":
                        "",
                }
            )


    frame = pd.DataFrame(
        rows
    )


    temp = target.with_suffix(
        target.suffix
        + ".tmp"
    )


    frame.to_csv(
        temp,
        index=False,
        encoding="utf-8-sig",
    )


    temp.replace(
        target
    )


    return target


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------


def parse_comparison_value(
    value: Any,
) -> float:
    """Parse a Saaty pairwise-comparison value.

    Accepted examples:

        1
        3
        5
        1/3
        1/5
        0.333333
    """

    if value is None:

        raise ValueError(
            "comparison_value is missing"
        )


    text = str(
        value
    ).strip()


    if not text:

        raise ValueError(
            "comparison_value is missing"
        )


    try:

        if "/" in text:

            parsed = float(
                Fraction(
                    text
                )
            )

        else:

            parsed = float(
                text
            )

    except (
        ValueError,
        ZeroDivisionError,
    ) as exc:

        raise ValueError(
            f"Invalid AHP comparison value: {value!r}"
        ) from exc


    if (
        not np.isfinite(
            parsed
        )
        or parsed <= 0
    ):

        raise ValueError(
            "AHP comparison values "
            "must be positive and finite"
        )


    # Allow small decimal rounding differences.
    if not any(
        np.isclose(
            parsed,
            allowed,
            atol=1e-5,
            rtol=1e-5,
        )
        for allowed
        in SAATY_VALUES
    ):

        raise ValueError(
            f"{value!r} is not a standard "
            "Saaty-scale comparison value"
        )


    return parsed


# ---------------------------------------------------------------------------
# CSV validation
# ---------------------------------------------------------------------------


def load_expert_reviews(
    path: str | Path = (
        DEFAULT_REVIEW_PATH
    ),
) -> pd.DataFrame:
    """Load and structurally validate expert AHP reviews."""

    source = Path(
        path
    )


    if not source.exists():

        raise FileNotFoundError(
            f"AHP review file not found: {source}"
        )


    frame = pd.read_csv(
        source,
        dtype=str,
    ).fillna("")


    required = {
        "expert_id",
        "factor_a",
        "factor_b",
        "comparison_value",
    }


    missing = (
        required
        - set(
            frame.columns
        )
    )


    if missing:

        raise ValueError(
            "AHP review file is missing columns: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )


    frame[
        "expert_id"
    ] = (
        frame[
            "expert_id"
        ]
        .astype(str)
        .str.strip()
    )


    frame[
        "factor_a"
    ] = (
        frame[
            "factor_a"
        ]
        .astype(str)
        .str.strip()
    )


    frame[
        "factor_b"
    ] = (
        frame[
            "factor_b"
        ]
        .astype(str)
        .str.strip()
    )


    if (
        frame[
            "expert_id"
        ]
        .eq("")
        .any()
    ):

        raise ValueError(
            "AHP review contains an empty expert_id"
        )


    expected_pairs = set(
        factor_pairs()
    )


    valid_factors = set(
        FACTOR_ORDER
    )


    for row in (
        frame.itertuples(
            index=False
        )
    ):

        if (
            row.factor_a
            not in valid_factors

            or row.factor_b
            not in valid_factors
        ):

            raise ValueError(
                "Unknown AHP factor in review file"
            )


        if (
            row.factor_a
            == row.factor_b
        ):

            raise ValueError(
                "AHP factor cannot be compared "
                "with itself"
            )


    parsed_values: list[
        float
    ] = []


    for raw in (
        frame[
            "comparison_value"
        ]
    ):

        parsed_values.append(
            parse_comparison_value(
                raw
            )
        )


    frame[
        "_parsed_value"
    ] = parsed_values


    # Normalize reversed pair rows.
    normalized_pairs: list[
        tuple[
            str,
            str,
            float,
        ]
    ] = []


    factor_position = {
        factor:
            index
        for index, factor
        in enumerate(
            FACTOR_ORDER
        )
    }


    for _, row in frame.iterrows():

        factor_a = (
            row["factor_a"]
        )

        factor_b = (
            row["factor_b"]
        )

        value = float(
            row["_parsed_value"]
        )


        if (
            factor_position[
                factor_a
            ]
            < factor_position[
                factor_b
            ]
        ):

            normalized_pairs.append(
                (
                    factor_a,
                    factor_b,
                    value,
                )
            )


        else:

            normalized_pairs.append(
                (
                    factor_b,
                    factor_a,
                    1.0 / value,
                )
            )


    frame[
        "_normalized_a"
    ] = [
        item[0]
        for item
        in normalized_pairs
    ]

    frame[
        "_normalized_b"
    ] = [
        item[1]
        for item
        in normalized_pairs
    ]

    frame[
        "_normalized_value"
    ] = [
        item[2]
        for item
        in normalized_pairs
    ]


    # Validate completeness independently for each expert.
    for (
        expert_id,
        group,

    ) in frame.groupby(
        "expert_id"
    ):

        pairs = list(
            zip(
                group[
                    "_normalized_a"
                ],
                group[
                    "_normalized_b"
                ],
            )
        )


        pair_set = set(
            pairs
        )


        if len(
            pairs
        ) != len(
            pair_set
        ):

            raise ValueError(
                f"Expert {expert_id} has "
                "duplicate pairwise comparisons"
            )


        missing_pairs = (
            expected_pairs
            - pair_set
        )


        extra_pairs = (
            pair_set
            - expected_pairs
        )


        if (
            missing_pairs
            or extra_pairs
        ):

            raise ValueError(
                f"Expert {expert_id} must complete "
                f"all {len(expected_pairs)} factor pairs. "
                f"Missing={sorted(missing_pairs)}, "
                f"extra={sorted(extra_pairs)}"
            )


    return frame


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------


def expert_matrix(
    frame: pd.DataFrame,
    expert_id: str,
) -> np.ndarray:
    """Create a reciprocal 6x6 AHP matrix for one expert."""

    group = frame.loc[
        frame[
            "expert_id"
        ].eq(
            expert_id
        )
    ]


    if group.empty:

        raise ValueError(
            f"Unknown expert_id: {expert_id}"
        )


    n = len(
        FACTOR_ORDER
    )


    matrix = np.ones(
        (
            n,
            n,
        ),
        dtype=float,
    )


    positions = {
        factor:
            index
        for index, factor
        in enumerate(
            FACTOR_ORDER
        )
    }


    for _, row in group.iterrows():

        factor_a = (
            row["_normalized_a"]
        )

        factor_b = (
            row["_normalized_b"]
        )

        value = float(
            row["_normalized_value"]
        )


        i = positions[
            factor_a
        ]

        j = positions[
            factor_b
        ]


        matrix[
            i,
            j
        ] = value

        matrix[
            j,
            i
        ] = (
            1.0
            / value
        )


    return matrix


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def calibrate_ahp(
    review_path: str | Path = (
        DEFAULT_REVIEW_PATH
    ),
    *,
    consistency_threshold: float = 0.10,
    exclude_inconsistent: bool = True,
    save_policy: bool = True,
    policy_path: str | Path = (
        DEFAULT_POLICY_PATH
    ),
) -> AhpCalibrationResult:
    """Validate and aggregate expert AHP judgements."""

    if (
        consistency_threshold
        < 0
    ):

        raise ValueError(
            "consistency_threshold "
            "must be nonnegative"
        )


    frame = load_expert_reviews(
        review_path
    )


    expert_ids = sorted(
        frame[
            "expert_id"
        ].unique()
    )


    expert_results: list[
        ExpertAhpEvaluation
    ] = []


    accepted_matrices: list[
        np.ndarray
    ] = []


    included: list[
        str
    ] = []


    excluded: list[
        str
    ] = []


    for expert_id in (
        expert_ids
    ):

        matrix = expert_matrix(
            frame,
            expert_id,
        )


        result = (
            calculate_ahp_weights(
                matrix,
                consistency_threshold=(
                    consistency_threshold
                ),
            )
        )


        evaluation = (
            ExpertAhpEvaluation(

                expert_id=(
                    expert_id
                ),

                consistency_ratio=(
                    result
                    .consistency_ratio
                ),

                consistency_index=(
                    result
                    .consistency_index
                ),

                lambda_max=(
                    result
                    .lambda_max
                ),

                is_consistent=(
                    result
                    .is_consistent
                ),

                weights=dict(
                    result.weights
                ),
            )
        )


        expert_results.append(
            evaluation
        )


        if (
            result.is_consistent
            or not exclude_inconsistent
        ):

            accepted_matrices.append(
                matrix
            )

            included.append(
                expert_id
            )


        else:

            excluded.append(
                expert_id
            )


    if not accepted_matrices:

        raise ValueError(
            "No consistent expert AHP matrices "
            "are available for aggregation"
        )


    (
        _,
        aggregate_result,

    ) = aggregate_ahp_matrices(

        accepted_matrices,

        consistency_threshold=(
            consistency_threshold
        ),
    )


    saved_path: (
        Path
        | None
    ) = None


    if save_policy:

        saved_path = (
            save_ahp_policy(

                aggregate_result,

                path=(
                    policy_path
                ),

                source=(
                    "EXPERT_AHP"
                ),

                metadata={
                    "generated_at_utc":
                        datetime.now(
                            timezone.utc
                        ).isoformat(),

                    "expert_count":
                        len(
                            expert_ids
                        ),

                    "consistent_expert_count":
                        len(
                            included
                        ),

                    "included_experts":
                        included,

                    "excluded_experts":
                        excluded,

                    "consistency_threshold":
                        consistency_threshold,

                    "aggregation_method":
                        (
                            "ELEMENT_WISE_GEOMETRIC_MEAN"
                        ),

                    "review_source":
                        str(
                            Path(
                                review_path
                            )
                        ),
                },

                require_consistent=True,
            )
        )


    return AhpCalibrationResult(

        included_experts=tuple(
            included
        ),

        excluded_experts=tuple(
            excluded
        ),

        expert_results=tuple(
            expert_results
        ),

        aggregate_result=(
            aggregate_result
        ),

        expert_count=(
            len(
                expert_ids
            )
        ),

        consistent_expert_count=(
            len(
                included
            )
        ),

        consistency_threshold=(
            consistency_threshold
        ),

        policy_path=(
            str(
                saved_path
            )
            if saved_path
            is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def save_calibration_report(
    result: AhpCalibrationResult,
    path: str | Path = (
        DEFAULT_REPORT_PATH
    ),
) -> Path:
    """Save full AHP audit metadata."""

    target = Path(
        path
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    payload = {
        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "factor_order":
            list(
                FACTOR_ORDER
            ),

        "factor_labels":
            FACTOR_LABELS,

        "expert_count":
            result.expert_count,

        "consistent_expert_count":
            result.consistent_expert_count,

        "included_experts":
            list(
                result.included_experts
            ),

        "excluded_experts":
            list(
                result.excluded_experts
            ),

        "consistency_threshold":
            result.consistency_threshold,

        "aggregate": {
            "weights":
                result
                .aggregate_result
                .weights,

            "lambda_max":
                result
                .aggregate_result
                .lambda_max,

            "consistency_index":
                result
                .aggregate_result
                .consistency_index,

            "consistency_ratio":
                result
                .aggregate_result
                .consistency_ratio,

            "is_consistent":
                result
                .aggregate_result
                .is_consistent,
        },

        "experts": [
            asdict(
                item
            )
            for item
            in result.expert_results
        ],

        "policy_path":
            result.policy_path,

        "interpretation": (
            "AHP weights represent structured expert policy "
            "judgements. They are not learned model coefficients "
            "or probabilities of vendor success."
        ),
    }


    temporary = (
        target.with_suffix(
            target.suffix
            + ".tmp"
        )
    )


    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    temporary.replace(
        target
    )


    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(
    result: AhpCalibrationResult,
) -> None:

    print(
        "\nAHP Expert Calibration"
    )

    print(
        "=" * 32
    )


    for expert in (
        result.expert_results
    ):

        print(
            f"{expert.expert_id}: "
            f"CR={expert.consistency_ratio:.4f} "
            f"({'OK' if expert.is_consistent else 'INCONSISTENT'})"
        )


    print(
        "\nIncluded experts:",
        ", ".join(
            result.included_experts
        ),
    )


    if (
        result.excluded_experts
    ):

        print(
            "Excluded experts:",
            ", ".join(
                result.excluded_experts
            ),
        )


    print(
        "\nAggregated weights:"
    )


    for factor in (
        FACTOR_ORDER
    ):

        print(
            f"  {FACTOR_LABELS[factor]}: "
            f"{100 * result.aggregate_result.weights[factor]:.2f}%"
        )


    print(
        "\nAggregate consistency ratio:",
        f"{result.aggregate_result.consistency_ratio:.4f}",
    )


    if result.policy_path:

        print(
            "Policy saved:",
            result.policy_path,
        )


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Generate or calibrate "
            "expert AHP MCDA weights."
        )
    )


    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )


    template_parser = (
        subparsers.add_parser(
            "template",
            help=(
                "Create a blank "
                "expert comparison template"
            ),
        )
    )


    template_parser.add_argument(
        "--output",
        default=str(
            DEFAULT_TEMPLATE_PATH
        ),
    )


    template_parser.add_argument(
        "--experts",
        nargs="+",
        default=[
            "EXPERT_01",
        ],
    )


    calibrate_parser = (
        subparsers.add_parser(
            "calibrate",
            help=(
                "Validate expert reviews "
                "and create AHP policy"
            ),
        )
    )


    calibrate_parser.add_argument(
        "--input",
        default=str(
            DEFAULT_REVIEW_PATH
        ),
    )


    calibrate_parser.add_argument(
        "--policy-output",
        default=str(
            DEFAULT_POLICY_PATH
        ),
    )


    calibrate_parser.add_argument(
        "--report-output",
        default=str(
            DEFAULT_REPORT_PATH
        ),
    )


    calibrate_parser.add_argument(
        "--consistency-threshold",
        type=float,
        default=0.10,
    )


    calibrate_parser.add_argument(
        "--include-inconsistent",
        action="store_true",
        help=(
            "Research-only option. "
            "Normally inconsistent "
            "experts should be reviewed "
            "instead of aggregated."
        ),
    )


    calibrate_parser.add_argument(
        "--no-save-policy",
        action="store_true",
    )


    args = (
        parser.parse_args()
    )


    if (
        args.command
        == "template"
    ):

        path = create_template(

            args.output,

            expert_ids=(
                args.experts
            ),
        )


        print(
            "Template saved:",
            path,
        )

        print(
            "Each expert must complete all "
            f"{len(factor_pairs())} pairwise comparisons."
        )

        print(
            "Use values 1–9 or reciprocals "
            "such as 1/3, 1/5, 1/7."
        )

        return


    result = calibrate_ahp(

        args.input,

        consistency_threshold=(
            args.consistency_threshold
        ),

        exclude_inconsistent=(
            not args.include_inconsistent
        ),

        save_policy=(
            not args.no_save_policy
        ),

        policy_path=(
            args.policy_output
        ),
    )


    _print_result(
        result
    )


    report_path = (
        save_calibration_report(

            result,

            args.report_output,
        )
    )


    print(
        "Calibration report:",
        report_path,
    )


if __name__ == "__main__":
    main()