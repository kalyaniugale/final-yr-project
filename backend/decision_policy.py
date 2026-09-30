"""Decision policy and AHP utilities for the MCDA recommendation engine.

The recommendation system is a transparent decision-support system, not a
trained predictor. This module keeps MCDA policy weights explicit and provides
Analytic Hierarchy Process (AHP) utilities so reviewed expert judgements can
replace the research baseline without changing recommendation logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_POLICY_PATH = (
    ROOT / "data" / "policy" / "mcda_weights.json"
)


FACTOR_ORDER = (
    "business",
    "commercial",
    "access",
    "facilities",
    "preference",
    "historical",
)


# ---------------------------------------------------------------------------
# Research baseline
# ---------------------------------------------------------------------------
#
# These are the weights currently used by the project.
#
# They are explicitly treated as research/policy assumptions, NOT learned
# model coefficients and NOT expert-validated AHP weights.
#
# Once expert pairwise comparisons are collected, an AHP-derived policy can
# be saved to DEFAULT_POLICY_PATH and loaded automatically.
# ---------------------------------------------------------------------------

RESEARCH_BASELINE_WEIGHTS = {
    "business": 0.25,
    "commercial": 0.20,
    "access": 0.20,
    "facilities": 0.15,
    "preference": 0.10,
    "historical": 0.10,
}


PRIORITY_TO_FACTOR = {
    "BALANCED": None,
    "COMMERCIAL": "commercial",
    "ACCESSIBILITY": "access",
    "FACILITIES": "facilities",
}


# Saaty's Random Index values.
_RANDOM_INDEX = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.48,
    13: 1.56,
    14: 1.57,
    15: 1.59,
}


@dataclass(frozen=True)
class AhpResult:
    """Result of an AHP pairwise-comparison calculation."""

    weights: dict[str, float]

    lambda_max: float

    consistency_index: float

    consistency_ratio: float

    is_consistent: bool


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------


def normalize_weights(
    weights: Mapping[str, float],
) -> dict[str, float]:
    """Validate and normalize a complete MCDA weight mapping."""

    expected = set(FACTOR_ORDER)
    received = set(weights)

    if received != expected:
        missing = sorted(expected - received)
        extra = sorted(received - expected)

        raise ValueError(
            "MCDA weights must contain exactly the configured factors "
            f"(missing={missing}, extra={extra})"
        )

    validated: dict[str, float] = {}

    for factor in FACTOR_ORDER:
        try:
            value = float(weights[factor])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Weight for {factor!r} must be numeric"
            ) from exc

        if not np.isfinite(value):
            raise ValueError(
                f"Weight for {factor!r} must be finite"
            )

        if value < 0:
            raise ValueError(
                f"Weight for {factor!r} must be nonnegative"
            )

        validated[factor] = value

    total = sum(validated.values())

    if total <= 0:
        raise ValueError(
            "At least one MCDA factor must have a positive weight"
        )

    normalized = {
        factor: validated[factor] / total
        for factor in FACTOR_ORDER
    }

    # Remove tiny floating-point residue so the final sum is exactly 1.
    normalized[FACTOR_ORDER[-1]] += (
        1.0 - sum(normalized.values())
    )

    return normalized


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def load_base_weight_policy(
    path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Load calibrated weights when available.

    If no reviewed weight policy exists, the system safely falls back to the
    documented research baseline.

    This prevents a missing calibration file from silently breaking the
    recommendation service.
    """

    policy_path = Path(path)

    if not policy_path.exists():
        return {
            "weights": normalize_weights(
                RESEARCH_BASELINE_WEIGHTS
            ),
            "source": "RESEARCH_BASELINE",
            "consistency_ratio": None,
            "policy_path": None,
        }

    try:
        payload = json.loads(
            policy_path.read_text(
                encoding="utf-8"
            )
        )

    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Unable to read MCDA policy file: {policy_path}"
        ) from exc

    weights = normalize_weights(
        payload.get(
            "weights",
            {},
        )
    )

    source = str(
        payload.get(
            "source",
            "EXTERNAL_POLICY",
        )
    ).strip()

    consistency_ratio = payload.get(
        "consistency_ratio"
    )

    if consistency_ratio is not None:
        try:
            consistency_ratio = float(
                consistency_ratio
            )

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "consistency_ratio must be numeric"
            ) from exc

        if (
            not np.isfinite(consistency_ratio)
            or consistency_ratio < 0
        ):
            raise ValueError(
                "consistency_ratio must be nonnegative"
            )

    return {
        "weights": weights,
        "source": source,
        "consistency_ratio": consistency_ratio,
        "policy_path": str(policy_path),
    }


# ---------------------------------------------------------------------------
# Vendor personalization
# ---------------------------------------------------------------------------


def derive_mcda_weights(
    vendor_profile: Mapping[str, Any] | None = None,
    *,
    base_weights: Mapping[str, float] | None = None,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Derive effective recommendation weights.

    Base weights come either from:

    1. a caller-supplied reviewed policy,
    2. an AHP policy file, or
    3. the documented research baseline.

    Vendor preferences apply only mild multipliers.

    They never:
    - bypass eligibility rules,
    - remove criteria,
    - create new data,
    - or directly allocate a zone.
    """

    profile = dict(
        vendor_profile or {}
    )

    if base_weights is not None:
        policy = {
            "weights": normalize_weights(
                base_weights
            ),
            "source": "CALLER_SUPPLIED",
            "consistency_ratio": None,
            "policy_path": None,
        }

    else:
        policy = load_base_weight_policy(
            policy_path
        )

    base = policy["weights"]

    priority = str(
        profile.get(
            "priority_profile",
            "BALANCED",
        )
        or "BALANCED"
    ).upper()

    if priority not in PRIORITY_TO_FACTOR:
        raise ValueError(
            "Unknown priority profile"
        )

    multipliers = {
        factor: 1.0
        for factor in FACTOR_ORDER
    }

    priority_factor = PRIORITY_TO_FACTOR[
        priority
    ]

    if priority_factor:
        multipliers[
            priority_factor
        ] *= 1.25

    if bool(
        profile.get(
            "market_preference",
            False,
        )
    ):
        multipliers[
            "commercial"
        ] *= 1.10

    if bool(
        profile.get(
            "transport_preference",
            False,
        )
    ):
        multipliers[
            "access"
        ] *= 1.10

    if bool(
        profile.get(
            "parking_preference",
            False,
        )
    ):
        multipliers[
            "facilities"
        ] *= 1.10

    adjusted = {
        factor: (
            base[factor]
            * multipliers[factor]
        )
        for factor in FACTOR_ORDER
    }

    final_weights = normalize_weights(
        adjusted
    )

    return {
        "base_weights": dict(base),
        "multipliers": multipliers,
        "final_weights": final_weights,
        "weight_source": policy["source"],
        "ahp_consistency_ratio": policy[
            "consistency_ratio"
        ],
        "policy_path": policy[
            "policy_path"
        ],
    }


# ---------------------------------------------------------------------------
# AHP implementation
# ---------------------------------------------------------------------------


def _validate_pairwise_matrix(
    matrix: Sequence[
        Sequence[float]
    ],
    *,
    tolerance: float = 1e-6,
) -> np.ndarray:
    """Validate the project's six-factor AHP matrix."""

    values = np.asarray(
        matrix,
        dtype=float,
    )

    expected_shape = (
        len(FACTOR_ORDER),
        len(FACTOR_ORDER),
    )

    if values.shape != expected_shape:
        raise ValueError(
            "AHP matrix must have shape "
            f"{expected_shape}, got {values.shape}"
        )

    if not np.isfinite(
        values
    ).all():
        raise ValueError(
            "AHP values must be finite"
        )

    if (
        values <= 0
    ).any():
        raise ValueError(
            "AHP values must be strictly positive"
        )

    if not np.allclose(
        np.diag(values),
        1.0,
        atol=tolerance,
        rtol=0,
    ):
        raise ValueError(
            "AHP matrix diagonal must contain 1s"
        )

    reciprocal_check = (
        values
        * values.T
    )

    if not np.allclose(
        reciprocal_check,
        1.0,
        atol=tolerance,
        rtol=0,
    ):
        raise ValueError(
            "AHP matrix must be reciprocal: "
            "a[i,j] = 1 / a[j,i]"
        )

    return values


def calculate_ahp_weights(
    matrix: Sequence[
        Sequence[float]
    ],
    *,
    consistency_threshold: float = 0.10,
) -> AhpResult:
    """Calculate AHP weights using the principal eigenvector method.

    A consistency ratio <= 0.10 is treated as acceptable by default.
    """

    if consistency_threshold < 0:
        raise ValueError(
            "consistency_threshold must be nonnegative"
        )

    values = _validate_pairwise_matrix(
        matrix
    )

    eigenvalues, eigenvectors = np.linalg.eig(
        values
    )

    principal_index = int(
        np.argmax(
            eigenvalues.real
        )
    )

    lambda_max = float(
        eigenvalues[
            principal_index
        ].real
    )

    priority_vector = np.abs(
        eigenvectors[
            :,
            principal_index,
        ].real
    )

    if priority_vector.sum() <= 0:
        raise ValueError(
            "Unable to derive AHP priority vector"
        )

    priority_vector = (
        priority_vector
        / priority_vector.sum()
    )

    raw_weights = {
        factor: float(
            priority_vector[index]
        )
        for index, factor
        in enumerate(
            FACTOR_ORDER
        )
    }

    weights = normalize_weights(
        raw_weights
    )

    n = len(
        FACTOR_ORDER
    )

    if n <= 2:
        consistency_index = 0.0

    else:
        consistency_index = max(
            0.0,
            (
                lambda_max - n
            )
            / (
                n - 1
            ),
        )

    random_index = _RANDOM_INDEX[
        n
    ]

    if random_index == 0:
        consistency_ratio = 0.0

    else:
        consistency_ratio = (
            consistency_index
            / random_index
        )

    return AhpResult(
        weights=weights,
        lambda_max=lambda_max,
        consistency_index=float(
            consistency_index
        ),
        consistency_ratio=float(
            consistency_ratio
        ),
        is_consistent=bool(
            consistency_ratio
            <= consistency_threshold
        ),
    )


def aggregate_ahp_matrices(
    matrices: Sequence[
        Sequence[
            Sequence[float]
        ]
    ],
    *,
    consistency_threshold: float = 0.10,
) -> tuple[np.ndarray, AhpResult]:
    """Combine multiple experts using element-wise geometric mean."""

    if not matrices:
        raise ValueError(
            "At least one expert AHP matrix is required"
        )

    validated = [
        _validate_pairwise_matrix(
            matrix
        )
        for matrix in matrices
    ]

    stacked = np.stack(
        validated,
        axis=0,
    )

    aggregate = np.exp(
        np.mean(
            np.log(stacked),
            axis=0,
        )
    )

    np.fill_diagonal(
        aggregate,
        1.0,
    )

    # Numerical cleanup to preserve exact reciprocal structure.
    for i in range(
        len(FACTOR_ORDER)
    ):
        for j in range(
            i + 1,
            len(FACTOR_ORDER),
        ):
            value = float(
                np.sqrt(
                    aggregate[i, j]
                    / aggregate[j, i]
                )
            )

            aggregate[i, j] = value
            aggregate[j, i] = (
                1.0 / value
            )

    result = calculate_ahp_weights(
        aggregate,
        consistency_threshold=(
            consistency_threshold
        ),
    )

    return aggregate, result


# ---------------------------------------------------------------------------
# Saving reviewed AHP policies
# ---------------------------------------------------------------------------


def save_ahp_policy(
    result: AhpResult,
    *,
    path: str | Path = DEFAULT_POLICY_PATH,
    source: str = "EXPERT_AHP",
    metadata: Mapping[
        str,
        Any,
    ]
    | None = None,
    require_consistent: bool = True,
) -> Path:
    """Atomically save a reviewed AHP policy.

    Inconsistent expert judgements are rejected by default rather than being
    silently activated in production.
    """

    if (
        require_consistent
        and not result.is_consistent
    ):
        raise ValueError(
            "AHP judgements are inconsistent. "
            "Consistency ratio must be <= 0.10 "
            "before activating this policy."
        )

    target = Path(
        path
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "source": source,
        "weights": result.weights,
        "consistency_ratio": (
            result.consistency_ratio
        ),
        "consistency_index": (
            result.consistency_index
        ),
        "lambda_max": (
            result.lambda_max
        ),
        "factors": list(
            FACTOR_ORDER
        ),
        "metadata": dict(
            metadata or {}
        ),
    }

    temporary = target.with_suffix(
        target.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temporary.replace(
        target
    )

    return target