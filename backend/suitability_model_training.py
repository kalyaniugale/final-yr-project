"""Experimental supervised suitability-model training.

This module trains models only on independently aggregated expert labels
prepared by backend.expert_label_aggregation.

The supervised model is experimental validation research.

It does NOT replace:
- municipal eligibility rules,
- live-capacity filtering,
- MCDA recommendation ranking,
- Goal Programming allocation,
- officer approval,
- or permit/allocation transactions.

Primary modelling target
------------------------
target_relevance

Median independent expert suitability judgment on the ordinal 0–4 scale.

Evaluation design
-----------------
Rows belonging to the same vendor_profile_id are kept in the same fold by
default. This avoids optimistic row-level leakage where the same vendor profile
appears in both training and validation data across different zones.

Models
------
1. Grouped train-fold mean baseline
2. RandomForestRegressor
3. XGBRegressor, when XGBoost is installed

No hyperparameter search is performed here. Fixed conservative parameters are
used so model comparison remains understandable and reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import joblib
import numpy as np
import pandas as pd
import sklearn
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from .expert_label_aggregation import (
        FEATURE_MANIFEST_PATH,
        MODEL_DATASET_PATH,
        RATING_MAX,
        RATING_MIN,
        quadratic_weighted_kappa,
    )

except ImportError:
    from expert_label_aggregation import (
        FEATURE_MANIFEST_PATH,
        MODEL_DATASET_PATH,
        RATING_MAX,
        RATING_MIN,
        quadratic_weighted_kappa,
    )


ROOT = Path(__file__).resolve().parents[1]


REPORT_DIR = (
    ROOT
    / "reports"
    / "suitability_model"
)


ARTIFACT_DIR = (
    ROOT
    / "artifacts"
    / "models"
)


COMPARISON_REPORT_PATH = (
    REPORT_DIR
    / "model_comparison.json"
)


OOF_PREDICTIONS_PATH = (
    REPORT_DIR
    / "oof_predictions.csv"
)


TRAINING_MANIFEST_PATH = (
    REPORT_DIR
    / "training_manifest.json"
)


RANDOM_FOREST_MODEL_PATH = (
    ARTIFACT_DIR
    / "random_forest_suitability.joblib"
)


XGBOOST_MODEL_PATH = (
    ARTIFACT_DIR
    / "xgboost_suitability.joblib"
)


SELECTED_MODEL_PATH = (
    ARTIFACT_DIR
    / "selected_suitability_model.joblib"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrainingConfig:
    """Reproducible model-training configuration."""

    group_column: str = (
        "vendor_profile_id"
    )

    cv_folds: int = 5

    random_seed: int = 42

    include_xgboost: bool = True

    random_forest_estimators: int = 300

    xgboost_estimators: int = 300

    n_jobs: int = 2

    prediction_min: float = float(
        RATING_MIN
    )

    prediction_max: float = float(
        RATING_MAX
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _sha256(
    path: str | Path,
) -> str:

    source = Path(
        path
    )

    digest = hashlib.sha256()

    with source.open(
        "rb"
    ) as handle:

        for chunk in iter(
            lambda:
                handle.read(
                    1024 * 1024
                ),
            b"",
        ):

            digest.update(
                chunk
            )

    return digest.hexdigest()


def _read_json(
    path: str | Path,
) -> dict[str, Any]:

    source = Path(
        path
    )

    if not source.exists():

        raise FileNotFoundError(
            f"Required manifest not found: {source}"
        )


    try:

        return json.loads(
            source.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:

        raise ValueError(
            f"Invalid JSON manifest: {source}"
        ) from exc


def _write_json_atomic(
    path: Path,
    payload: Mapping[
        str,
        Any,
    ],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    temporary = (
        path.with_suffix(
            path.suffix
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
        path
    )


def _write_csv_atomic(
    path: Path,
    frame: pd.DataFrame,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    temporary = (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    )


    frame.to_csv(
        temporary,
        index=False,
        encoding="utf-8-sig",
    )


    temporary.replace(
        path
    )


def _dump_joblib_atomic(
    path: Path,
    payload: Any,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    temporary = (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    )


    joblib.dump(
        payload,
        temporary,
    )


    temporary.replace(
        path
    )


# ---------------------------------------------------------------------------
# One-hot compatibility
# ---------------------------------------------------------------------------


def _one_hot_encoder():
    """Support both modern and older scikit-learn APIs."""

    try:

        return OneHotEncoder(
            handle_unknown="ignore",
            sparse_output=False,
        )

    except TypeError:

        return OneHotEncoder(
            handle_unknown="ignore",
            sparse=False,
        )


# ---------------------------------------------------------------------------
# Dataset contract
# ---------------------------------------------------------------------------


def load_training_data(
    dataset_path: str | Path = (
        MODEL_DATASET_PATH
    ),
    manifest_path: str | Path = (
        FEATURE_MANIFEST_PATH
    ),
) -> tuple[
    pd.DataFrame,
    dict[str, Any],
]:
    """Load the leakage-controlled expert-labelled dataset."""

    source = Path(
        dataset_path
    )


    if not source.exists():

        raise FileNotFoundError(
            "Expert model dataset not found: "
            f"{source}. Run expert_label_aggregation first."
        )


    dataset = pd.read_csv(
        source,
        dtype={
            "pair_id": str,
            "vendor_profile_id": str,
            "zone_id": str,
            "evidence_version": str,
        },
    )


    manifest = _read_json(
        manifest_path
    )


    return (
        dataset,
        manifest,
    )


def validate_training_contract(
    dataset: pd.DataFrame,
    manifest: Mapping[
        str,
        Any,
    ],
    config: TrainingConfig,
) -> dict[str, Any]:
    """Validate dataset, target, feature and grouping contract."""

    target = str(
        manifest.get(
            "target",
            ""
        )
    ).strip()


    if not target:

        raise ValueError(
            "Feature manifest does not define target"
        )


    feature_columns = [
        str(
            field
        )
        for field
        in manifest.get(
            "feature_columns",
            []
        )
    ]


    categorical = [
        str(
            field
        )
        for field
        in manifest.get(
            "categorical_features",
            []
        )
    ]


    numeric = [
        str(
            field
        )
        for field
        in manifest.get(
            "numeric_features",
            []
        )
    ]


    if not feature_columns:

        raise ValueError(
            "No model features are defined "
            "in the feature manifest"
        )


    required = {
        target,
        config.group_column,
        *feature_columns,
    }


    missing = (
        required
        - set(
            dataset.columns
        )
    )


    if missing:

        raise ValueError(
            "Training dataset is missing columns: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )


    typed_features = (
        set(
            categorical
        )
        | set(
            numeric
        )
    )


    unexpected = (
        set(
            feature_columns
        )
        - typed_features
    )


    if unexpected:

        raise ValueError(
            "Feature manifest contains features "
            "without categorical/numeric type: "
            + ", ".join(
                sorted(
                    unexpected
                )
            )
        )


    duplicate_types = (
        set(
            categorical
        )
        & set(
            numeric
        )
    )


    if duplicate_types:

        raise ValueError(
            "Features cannot be both categorical "
            "and numeric: "
            + ", ".join(
                sorted(
                    duplicate_types
                )
            )
        )


    if dataset.empty:

        raise ValueError(
            "Training dataset contains no rows"
        )


    target_values = pd.to_numeric(
        dataset[
            target
        ],
        errors="coerce",
    )


    if target_values.isna().any():

        raise ValueError(
            "Training target contains missing "
            "or nonnumeric values"
        )


    if (
        target_values.lt(
            RATING_MIN
        ).any()

        or target_values.gt(
            RATING_MAX
        ).any()
    ):

        raise ValueError(
            "Training target lies outside "
            f"{RATING_MIN}–{RATING_MAX}"
        )


    groups = (
        dataset[
            config.group_column
        ]
        .fillna("")
        .astype(str)
        .str.strip()
    )


    if groups.eq("").any():

        raise ValueError(
            f"Grouping column {config.group_column!r} "
            "contains empty values"
        )


    unique_groups = int(
        groups.nunique()
    )


    if unique_groups < 2:

        raise ValueError(
            "Grouped validation requires at least "
            "two unique groups"
        )


    if config.cv_folds < 2:

        raise ValueError(
            "cv_folds must be at least 2"
        )


    effective_folds = min(
        config.cv_folds,
        unique_groups,
    )


    if config.random_forest_estimators < 1:

        raise ValueError(
            "random_forest_estimators must "
            "be positive"
        )


    if config.xgboost_estimators < 1:

        raise ValueError(
            "xgboost_estimators must "
            "be positive"
        )


    if config.n_jobs < 1:

        raise ValueError(
            "n_jobs must be positive"
        )


    if (
        config.prediction_min
        >= config.prediction_max
    ):

        raise ValueError(
            "prediction_min must be less than "
            "prediction_max"
        )


    return {
        "target":
            target,

        "feature_columns":
            feature_columns,

        "categorical_features": [
            field
            for field
            in categorical
            if field
            in feature_columns
        ],

        "numeric_features": [
            field
            for field
            in numeric
            if field
            in feature_columns
        ],

        "group_column":
            config.group_column,

        "unique_group_count":
            unique_groups,

        "effective_cv_folds":
            effective_folds,
    }


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------


def build_preprocessor(
    *,
    categorical_features: list[str],
    numeric_features: list[str],
) -> ColumnTransformer:
    """Create deterministic tree-model preprocessing."""

    transformers: list[
        tuple[
            str,
            Pipeline,
            list[str],
        ]
    ] = []


    if numeric_features:

        numeric_pipeline = Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median"
                    ),
                ),
            ]
        )


        transformers.append(
            (
                "numeric",
                numeric_pipeline,
                numeric_features,
            )
        )


    if categorical_features:

        categorical_pipeline = Pipeline(
            steps=[
                (
                    "imputer",
                    SimpleImputer(
                        strategy="most_frequent"
                    ),
                ),
                (
                    "onehot",
                    _one_hot_encoder(),
                ),
            ]
        )


        transformers.append(
            (
                "categorical",
                categorical_pipeline,
                categorical_features,
            )
        )


    if not transformers:

        raise ValueError(
            "No usable numeric or categorical "
            "features were configured"
        )


    return ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        verbose_feature_names_out=True,
    )


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------


def _random_forest_factory(
    config: TrainingConfig,
) -> Callable[[], Any]:

    def create():

        return RandomForestRegressor(
            n_estimators=(
                config
                .random_forest_estimators
            ),
            min_samples_leaf=2,
            random_state=(
                config.random_seed
            ),
            n_jobs=(
                config.n_jobs
            ),
        )

    return create


def _xgboost_factory(
    config: TrainingConfig,
) -> tuple[
    Callable[[], Any],
    str,
]:
    """Import XGBoost lazily so non-XGBoost workflows still run."""

    try:

        import xgboost as xgb

    except ImportError as exc:

        raise RuntimeError(
            "XGBoost is not installed. "
            "Install it with: pip install xgboost "
            "or run with --skip-xgboost."
        ) from exc


    version = str(
        xgb.__version__
    )


    def create():

        return xgb.XGBRegressor(
            objective="reg:squarederror",
            n_estimators=(
                config
                .xgboost_estimators
            ),
            max_depth=4,
            learning_rate=0.05,
            subsample=0.90,
            colsample_bytree=0.90,
            reg_lambda=1.0,
            random_state=(
                config.random_seed
            ),
            n_jobs=(
                config.n_jobs
            ),
            tree_method="hist",
        )


    return (
        create,
        version,
    )


def _build_pipeline(
    estimator: Any,
    *,
    categorical_features: list[str],
    numeric_features: list[str],
) -> Pipeline:

    return Pipeline(
        steps=[
            (
                "preprocessor",
                build_preprocessor(
                    categorical_features=(
                        categorical_features
                    ),
                    numeric_features=(
                        numeric_features
                    ),
                ),
            ),
            (
                "model",
                estimator,
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _safe_spearman(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float | None:

    if len(
        actual
    ) < 2:

        return None


    if (
        np.std(
            actual
        )
        == 0

        or np.std(
            predicted
        )
        == 0
    ):

        return None


    correlation = spearmanr(
        actual,
        predicted,
    ).statistic


    if (
        correlation is None
        or not np.isfinite(
            correlation
        )
    ):

        return None


    return float(
        correlation
    )


def regression_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    *,
    prediction_min: float = float(
        RATING_MIN
    ),
    prediction_max: float = float(
        RATING_MAX
    ),
) -> dict[str, Any]:
    """Evaluate continuous and ordinal behavior."""

    y_true = np.asarray(
        actual,
        dtype=float,
    )


    y_pred = np.asarray(
        predicted,
        dtype=float,
    )


    if (
        y_true.shape
        != y_pred.shape
    ):

        raise ValueError(
            "Actual and predicted arrays "
            "must have the same shape"
        )


    if len(
        y_true
    ) == 0:

        raise ValueError(
            "Cannot evaluate zero predictions"
        )


    y_pred = np.clip(
        y_pred,
        prediction_min,
        prediction_max,
    )


    mae = float(
        mean_absolute_error(
            y_true,
            y_pred,
        )
    )


    rmse = float(
        np.sqrt(
            mean_squared_error(
                y_true,
                y_pred,
            )
        )
    )


    if (
        len(
            y_true
        ) >= 2

        and np.var(
            y_true
        ) > 0
    ):

        r2 = float(
            r2_score(
                y_true,
                y_pred,
            )
        )


    else:

        r2 = None


    spearman = _safe_spearman(
        y_true,
        y_pred,
    )


    within_one = float(
        np.mean(
            np.abs(
                y_true
                - y_pred
            )
            <= 1.0
        )
    )


    rounded_true = np.clip(
        np.rint(
            y_true
        ),
        RATING_MIN,
        RATING_MAX,
    ).astype(
        int
    )


    rounded_pred = np.clip(
        np.rint(
            y_pred
        ),
        RATING_MIN,
        RATING_MAX,
    ).astype(
        int
    )


    rounded_exact = float(
        np.mean(
            rounded_true
            == rounded_pred
        )
    )


    qwk = quadratic_weighted_kappa(
        rounded_true,
        rounded_pred,
    )


    return {
        "mae":
            mae,

        "rmse":
            rmse,

        "r2":
            r2,

        "spearman_rank_correlation":
            spearman,

        "within_one_point_rate":
            within_one,

        "rounded_exact_accuracy":
            rounded_exact,

        "rounded_quadratic_weighted_kappa":
            qwk,
    }


# ---------------------------------------------------------------------------
# Grouped validation
# ---------------------------------------------------------------------------


def evaluate_model_grouped(
    dataset: pd.DataFrame,
    *,
    contract: Mapping[
        str,
        Any,
    ],
    estimator_factory: Callable[
        [],
        Any,
    ],
    model_name: str,
    config: TrainingConfig,
) -> tuple[
    dict[str, Any],
    np.ndarray,
    list[
        dict[str, Any]
    ],
]:
    """Produce leakage-safe grouped out-of-fold predictions."""

    features = list(
        contract[
            "feature_columns"
        ]
    )


    target = str(
        contract[
            "target"
        ]
    )


    group_column = str(
        contract[
            "group_column"
        ]
    )


    X = dataset[
        features
    ].copy()


    y = pd.to_numeric(
        dataset[
            target
        ],
        errors="raise",
    ).to_numpy(
        dtype=float
    )


    groups = (
        dataset[
            group_column
        ]
        .astype(str)
        .to_numpy()
    )


    folds = GroupKFold(
        n_splits=int(
            contract[
                "effective_cv_folds"
            ]
        )
    )


    predictions = np.full(
        len(
            dataset
        ),
        np.nan,
        dtype=float,
    )


    fold_rows: list[
        dict[str, Any]
    ] = []


    for fold_number, (
        train_index,
        test_index,

    ) in enumerate(
        folds.split(
            X,
            y,
            groups,
        ),
        start=1,
    ):

        pipeline = _build_pipeline(
            estimator_factory(),
            categorical_features=list(
                contract[
                    "categorical_features"
                ]
            ),
            numeric_features=list(
                contract[
                    "numeric_features"
                ]
            ),
        )


        pipeline.fit(
            X.iloc[
                train_index
            ],
            y[
                train_index
            ],
        )


        fold_prediction = (
            pipeline.predict(
                X.iloc[
                    test_index
                ]
            )
        )


        fold_prediction = np.clip(
            fold_prediction,
            config.prediction_min,
            config.prediction_max,
        )


        predictions[
            test_index
        ] = fold_prediction


        fold_metrics = (
            regression_metrics(
                y[
                    test_index
                ],
                fold_prediction,
                prediction_min=(
                    config.prediction_min
                ),
                prediction_max=(
                    config.prediction_max
                ),
            )
        )


        fold_rows.append(
            {
                "fold":
                    fold_number,

                "train_rows":
                    int(
                        len(
                            train_index
                        )
                    ),

                "validation_rows":
                    int(
                        len(
                            test_index
                        )
                    ),

                "train_groups":
                    int(
                        len(
                            np.unique(
                                groups[
                                    train_index
                                ]
                            )
                        )
                    ),

                "validation_groups":
                    int(
                        len(
                            np.unique(
                                groups[
                                    test_index
                                ]
                            )
                        )
                    ),

                **fold_metrics,
            }
        )


    if np.isnan(
        predictions
    ).any():

        raise RuntimeError(
            f"{model_name} did not produce "
            "a prediction for every row"
        )


    overall = regression_metrics(
        y,
        predictions,
        prediction_min=(
            config.prediction_min
        ),
        prediction_max=(
            config.prediction_max
        ),
    )


    return (
        overall,
        predictions,
        fold_rows,
    )


def grouped_mean_baseline(
    dataset: pd.DataFrame,
    *,
    contract: Mapping[
        str,
        Any,
    ],
    config: TrainingConfig,
) -> tuple[
    dict[str, Any],
    np.ndarray,
]:
    """Grouped out-of-fold mean baseline.

    Each validation fold receives only the mean target from that fold's
    training partition. This avoids leaking validation labels.
    """

    target = str(
        contract[
            "target"
        ]
    )


    group_column = str(
        contract[
            "group_column"
        ]
    )


    y = pd.to_numeric(
        dataset[
            target
        ],
        errors="raise",
    ).to_numpy(
        dtype=float
    )


    groups = (
        dataset[
            group_column
        ]
        .astype(str)
        .to_numpy()
    )


    dummy_x = np.zeros(
        (
            len(
                dataset
            ),
            1,
        )
    )


    folds = GroupKFold(
        n_splits=int(
            contract[
                "effective_cv_folds"
            ]
        )
    )


    predictions = np.full(
        len(
            dataset
        ),
        np.nan,
        dtype=float,
    )


    for (
        train_index,
        test_index,

    ) in folds.split(
        dummy_x,
        y,
        groups,
    ):

        train_mean = float(
            np.mean(
                y[
                    train_index
                ]
            )
        )


        predictions[
            test_index
        ] = train_mean


    metrics = regression_metrics(
        y,
        predictions,
        prediction_min=(
            config.prediction_min
        ),
        prediction_max=(
            config.prediction_max
        ),
    )


    return (
        metrics,
        predictions,
    )


# ---------------------------------------------------------------------------
# Final model fitting
# ---------------------------------------------------------------------------


def fit_final_pipeline(
    dataset: pd.DataFrame,
    *,
    contract: Mapping[
        str,
        Any,
    ],
    estimator_factory: Callable[
        [],
        Any,
    ],
) -> Pipeline:

    features = list(
        contract[
            "feature_columns"
        ]
    )


    target = str(
        contract[
            "target"
        ]
    )


    pipeline = _build_pipeline(
        estimator_factory(),
        categorical_features=list(
            contract[
                "categorical_features"
            ]
        ),
        numeric_features=list(
            contract[
                "numeric_features"
            ]
        ),
    )


    pipeline.fit(
        dataset[
            features
        ],
        pd.to_numeric(
            dataset[
                target
            ],
            errors="raise",
        ).to_numpy(
            dtype=float
        ),
    )


    return pipeline


def transformed_feature_names(
    pipeline: Pipeline,
) -> list[str]:

    preprocessor = (
        pipeline.named_steps[
            "preprocessor"
        ]
    )


    return [
        str(
            value
        )
        for value
        in preprocessor
        .get_feature_names_out()
        .tolist()
    ]


# ---------------------------------------------------------------------------
# Model bundle
# ---------------------------------------------------------------------------


def build_model_bundle(
    pipeline: Pipeline,
    *,
    model_name: str,
    contract: Mapping[
        str,
        Any,
    ],
    config: TrainingConfig,
    dataset_sha256: str | None,
    feature_manifest_sha256: str | None,
    row_count: int,
    metrics: Mapping[
        str,
        Any,
    ],
) -> dict[str, Any]:

    return {
        "model_name":
            model_name,

        "model_role":
            "EXPERIMENTAL_EXPERT_SUITABILITY_MODEL",

        "trained_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "pipeline":
            pipeline,

        "target":
            contract[
                "target"
            ],

        "target_scale": {
            "minimum":
                RATING_MIN,

            "maximum":
                RATING_MAX,
        },

        "group_validation_column":
            contract[
                "group_column"
            ],

        "feature_columns":
            list(
                contract[
                    "feature_columns"
                ]
            ),

        "categorical_features":
            list(
                contract[
                    "categorical_features"
                ]
            ),

        "numeric_features":
            list(
                contract[
                    "numeric_features"
                ]
            ),

        "transformed_feature_names":
            transformed_feature_names(
                pipeline
            ),

        "training_row_count":
            int(
                row_count
            ),

        "training_dataset_sha256":
            dataset_sha256,

        "feature_manifest_sha256":
            feature_manifest_sha256,

        "grouped_oof_metrics":
            dict(
                metrics
            ),

        "training_config":
            asdict(
                config
            ),

        "notice": (
            "Experimental model trained on independent "
            "expert suitability judgments. It does not "
            "replace MCDA, municipal rules, live capacity "
            "checks, Goal Programming, or officer approval."
        ),
    }


# ---------------------------------------------------------------------------
# Training orchestration
# ---------------------------------------------------------------------------


def train_models(
    dataset: pd.DataFrame,
    manifest: Mapping[
        str,
        Any,
    ],
    *,
    config: TrainingConfig | None = None,
    dataset_sha256: str | None = None,
    feature_manifest_sha256: str | None = None,
    save_artifacts: bool = False,
) -> dict[str, Any]:
    """Evaluate models and fit final full-data pipelines."""

    config = (
        config
        or TrainingConfig()
    )


    contract = (
        validate_training_contract(
            dataset,
            manifest,
            config,
        )
    )


    target = str(
        contract[
            "target"
        ]
    )


    y = pd.to_numeric(
        dataset[
            target
        ],
        errors="raise",
    ).to_numpy(
        dtype=float
    )


    # -----------------------------------------------------------------------
    # Leakage-safe grouped mean baseline
    # -----------------------------------------------------------------------

    (
        baseline_metrics,
        baseline_predictions,

    ) = grouped_mean_baseline(
        dataset,
        contract=contract,
        config=config,
    )


    model_factories: dict[
        str,
        Callable[
            [],
            Any,
        ],
    ] = {
        "random_forest":
            _random_forest_factory(
                config
            ),
    }


    library_versions: dict[
        str,
        str | None,
    ] = {
        "python":
            platform.python_version(),

        "numpy":
            np.__version__,

        "pandas":
            pd.__version__,

        "scikit_learn":
            sklearn.__version__,

        "xgboost":
            None,
    }


    if config.include_xgboost:

        (
            xgb_factory,
            xgb_version,

        ) = _xgboost_factory(
            config
        )


        model_factories[
            "xgboost"
        ] = xgb_factory


        library_versions[
            "xgboost"
        ] = xgb_version


    model_results: dict[
        str,
        dict[
            str,
            Any,
        ],
    ] = {}


    prediction_columns: dict[
        str,
        np.ndarray,
    ] = {
        "baseline_group_mean":
            baseline_predictions,
    }


    final_pipelines: dict[
        str,
        Pipeline,
    ] = {}


    for (
        model_name,
        estimator_factory,

    ) in model_factories.items():

        (
            metrics,
            predictions,
            folds,

        ) = evaluate_model_grouped(
            dataset,
            contract=contract,
            estimator_factory=(
                estimator_factory
            ),
            model_name=(
                model_name
            ),
            config=config,
        )


        pipeline = fit_final_pipeline(
            dataset,
            contract=contract,
            estimator_factory=(
                estimator_factory
            ),
        )


        final_pipelines[
            model_name
        ] = pipeline


        prediction_columns[
            model_name
        ] = predictions


        model_results[
            model_name
        ] = {
            "metrics":
                metrics,

            "folds":
                folds,

            "beats_grouped_mean_baseline_mae":
                bool(
                    metrics[
                        "mae"
                    ]
                    < baseline_metrics[
                        "mae"
                    ]
                ),
        }


    # -----------------------------------------------------------------------
    # Select experimental model only by pre-declared validation metric.
    # -----------------------------------------------------------------------
    #
    # Lower grouped out-of-fold MAE is primary.
    # RMSE is used only as deterministic tie-breaker.
    # -----------------------------------------------------------------------

    selected_model = min(
        model_results,
        key=lambda name: (
            model_results[
                name
            ][
                "metrics"
            ][
                "mae"
            ],
            model_results[
                name
            ][
                "metrics"
            ][
                "rmse"
            ],
            name,
        ),
    )


    selected_metrics = (
        model_results[
            selected_model
        ][
            "metrics"
        ]
    )


    # -----------------------------------------------------------------------
    # OOF audit table
    # -----------------------------------------------------------------------

    metadata_columns = [
        column
        for column
        in (
            "pair_id",
            "vendor_profile_id",
            "zone_id",
            "evidence_version",
        )
        if column
        in dataset.columns
    ]


    oof = dataset[
        metadata_columns
    ].copy()


    oof[
        "actual_target"
    ] = y


    for (
        name,
        values,

    ) in prediction_columns.items():

        oof[
            f"prediction_{name}"
        ] = values


    oof[
        "selected_model"
    ] = selected_model


    # -----------------------------------------------------------------------
    # Model bundles
    # -----------------------------------------------------------------------

    bundles = {
        model_name:
            build_model_bundle(
                pipeline,
                model_name=(
                    model_name
                ),
                contract=contract,
                config=config,
                dataset_sha256=(
                    dataset_sha256
                ),
                feature_manifest_sha256=(
                    feature_manifest_sha256
                ),
                row_count=len(
                    dataset
                ),
                metrics=(
                    model_results[
                        model_name
                    ][
                        "metrics"
                    ]
                ),
            )

        for (
            model_name,
            pipeline,
        ) in final_pipelines.items()
    }


    report = {
        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "experiment_type":
            "SUPERVISED_EXPERT_SUITABILITY_REGRESSION",

        "status":
            "EXPERIMENTAL",

        "dataset": {
            "rows":
                int(
                    len(
                        dataset
                    )
                ),

            "target":
                target,

            "target_min":
                float(
                    np.min(
                        y
                    )
                ),

            "target_max":
                float(
                    np.max(
                        y
                    )
                ),

            "target_mean":
                float(
                    np.mean(
                        y
                    )
                ),

            "group_column":
                contract[
                    "group_column"
                ],

            "unique_groups":
                contract[
                    "unique_group_count"
                ],

            "cv_folds":
                contract[
                    "effective_cv_folds"
                ],

            "dataset_sha256":
                dataset_sha256,

            "feature_manifest_sha256":
                feature_manifest_sha256,
        },

        "features": {
            "feature_columns":
                list(
                    contract[
                        "feature_columns"
                    ]
                ),

            "categorical_features":
                list(
                    contract[
                        "categorical_features"
                    ]
                ),

            "numeric_features":
                list(
                    contract[
                        "numeric_features"
                    ]
                ),
        },

        "baseline": {
            "name":
                "grouped_train_fold_mean",

            "metrics":
                baseline_metrics,
        },

        "models":
            model_results,

        "selected_model":
            selected_model,

        "selection_rule":
            (
                "Lowest grouped out-of-fold MAE; "
                "RMSE then model name used only "
                "as deterministic tie-breakers."
            ),

        "selected_model_metrics":
            selected_metrics,

        "selected_model_beats_baseline_mae":
            bool(
                selected_metrics[
                    "mae"
                ]
                < baseline_metrics[
                    "mae"
                ]
            ),

        "library_versions":
            library_versions,

        "limitations": [
            (
                "Targets are independent expert judgments "
                "rather than observed vendor business outcomes."
            ),
            (
                "Grouped cross-validation estimates generalization "
                "to unseen vendor profiles, not necessarily unseen zones."
            ),
            (
                "Small expert-labelled datasets can produce unstable "
                "performance estimates."
            ),
            (
                "Model selection does not establish municipal legality "
                "or operational allocation feasibility."
            ),
            (
                "The supervised model remains experimental and does not "
                "replace MCDA or Goal Programming."
            ),
        ],
    }


    output = {
        "contract":
            contract,

        "report":
            report,

        "oof_predictions":
            oof,

        "bundles":
            bundles,

        "selected_model":
            selected_model,
    }


    if save_artifacts:

        save_training_artifacts(
            output
        )


    return output


# ---------------------------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------------------------


def save_training_artifacts(
    training: Mapping[
        str,
        Any,
    ],
) -> dict[str, Path]:
    """Persist evaluation evidence and fitted model bundles."""

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    ARTIFACT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    report = training[
        "report"
    ]


    oof = training[
        "oof_predictions"
    ]


    bundles = training[
        "bundles"
    ]


    selected_model = str(
        training[
            "selected_model"
        ]
    )


    if not isinstance(
        oof,
        pd.DataFrame,
    ):

        raise ValueError(
            "Training output is missing "
            "OOF predictions"
        )


    _write_json_atomic(
        COMPARISON_REPORT_PATH,
        report,
    )


    _write_csv_atomic(
        OOF_PREDICTIONS_PATH,
        oof,
    )


    model_paths: dict[
        str,
        Path,
    ] = {}


    if (
        "random_forest"
        in bundles
    ):

        _dump_joblib_atomic(
            RANDOM_FOREST_MODEL_PATH,
            bundles[
                "random_forest"
            ],
        )


        model_paths[
            "random_forest"
        ] = (
            RANDOM_FOREST_MODEL_PATH
        )


    if (
        "xgboost"
        in bundles
    ):

        _dump_joblib_atomic(
            XGBOOST_MODEL_PATH,
            bundles[
                "xgboost"
            ],
        )


        model_paths[
            "xgboost"
        ] = (
            XGBOOST_MODEL_PATH
        )


    selected_source = (
        model_paths.get(
            selected_model
        )
    )


    if selected_source is None:

        raise ValueError(
            "Selected model artifact "
            "was not created"
        )


    selected_temp = (
        SELECTED_MODEL_PATH
        .with_suffix(
            SELECTED_MODEL_PATH.suffix
            + ".tmp"
        )
    )


    shutil.copyfile(
        selected_source,
        selected_temp,
    )


    selected_temp.replace(
        SELECTED_MODEL_PATH
    )


    training_manifest = {
        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "selected_model":
            selected_model,

        "selected_model_path":
            str(
                SELECTED_MODEL_PATH
            ),

        "model_artifacts": {
            name:
                str(
                    path
                )
            for (
                name,
                path,
            ) in model_paths.items()
        },

        "comparison_report_path":
            str(
                COMPARISON_REPORT_PATH
            ),

        "oof_predictions_path":
            str(
                OOF_PREDICTIONS_PATH
            ),

        "dataset":
            report[
                "dataset"
            ],

        "training_config":
            bundles[
                selected_model
            ][
                "training_config"
            ],

        "notice": (
            "Experimental expert-suitability model. "
            "Not an allocation authority or permit model."
        ),
    }


    _write_json_atomic(
        TRAINING_MANIFEST_PATH,
        training_manifest,
    )


    return {
        "comparison_report":
            COMPARISON_REPORT_PATH,

        "oof_predictions":
            OOF_PREDICTIONS_PATH,

        "training_manifest":
            TRAINING_MANIFEST_PATH,

        "selected_model":
            SELECTED_MODEL_PATH,

        **{
            f"{name}_model":
                path
            for (
                name,
                path,
            ) in model_paths.items()
        },
    }


# ---------------------------------------------------------------------------
# File-based production entry point
# ---------------------------------------------------------------------------


def train_from_files(
    *,
    dataset_path: str | Path = (
        MODEL_DATASET_PATH
    ),
    manifest_path: str | Path = (
        FEATURE_MANIFEST_PATH
    ),
    config: TrainingConfig | None = None,
    save_artifacts: bool = True,
) -> dict[str, Any]:
    """Train using expert-label artifacts from disk."""

    dataset, manifest = (
        load_training_data(
            dataset_path,
            manifest_path,
        )
    )


    return train_models(
        dataset,
        manifest,
        config=config,
        dataset_sha256=(
            _sha256(
                dataset_path
            )
        ),
        feature_manifest_sha256=(
            _sha256(
                manifest_path
            )
        ),
        save_artifacts=(
            save_artifacts
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic self-test
# ---------------------------------------------------------------------------


def self_test(
    *,
    include_xgboost: bool = False,
) -> None:
    """Run a synthetic grouped training test.

    XGBoost is disabled by default so the training module can be validated
    before the optional dependency is installed.
    """

    rng = np.random.default_rng(
        42
    )


    rows: list[
        dict[str, Any]
    ] = []


    businesses = [
        "food",
        "vegetable_fruit",
    ]


    divisions = [
        "Nashik West",
        "Nashik East",
    ]


    zones = [
        "Z1",
        "Z2",
        "Z3",
        "Z4",
        "Z5",
    ]


    for vendor_index in range(
        10
    ):

        vendor = (
            f"VP{vendor_index + 1:02d}"
        )


        business = businesses[
            vendor_index
            % len(
                businesses
            )
        ]


        preferred = divisions[
            vendor_index
            % len(
                divisions
            )
        ]


        for zone_index, zone_id in enumerate(
            zones
        ):

            zone_division = divisions[
                zone_index
                % len(
                    divisions
                )
            ]


            commercial = float(
                rng.integers(
                    0,
                    13,
                )
            )


            road_distance = float(
                rng.integers(
                    40,
                    700,
                )
            )


            parking = float(
                rng.integers(
                    0,
                    5,
                )
            )


            preference_bonus = (
                0.7
                if (
                    preferred
                    == zone_division
                )
                else 0.0
            )


            business_bonus = (
                0.4
                if business
                == "food"
                else 0.2
            )


            target = (
                0.6
                + 0.16
                * commercial
                - 0.0015
                * road_distance
                + 0.20
                * parking
                + preference_bonus
                + business_bonus
                + rng.normal(
                    0.0,
                    0.25,
                )
            )


            target = float(
                np.clip(
                    target,
                    RATING_MIN,
                    RATING_MAX,
                )
            )


            rows.append(
                {
                    "pair_id":
                        f"{vendor}_{zone_id}",

                    "vendor_profile_id":
                        vendor,

                    "zone_id":
                        zone_id,

                    "evidence_version":
                        "SELF_TEST_V1",

                    "business_category":
                        business,

                    "preferred_division":
                        preferred,

                    "zone_division":
                        zone_division,

                    "environment_cluster":
                        str(
                            zone_index
                            % 3
                        ),

                    "geometry_status":
                        "REFERENCE_ONLY",

                    "geometry_method":
                        "POINT",

                    "official_capacity":
                        float(
                            10
                            + zone_index
                        ),

                    "commercial_poi_count_250m":
                        commercial,

                    "distance_to_major_road_m":
                        road_distance,

                    "parking_count_500m":
                        parking,

                    "target_relevance":
                        target,
                }
            )


    dataset = pd.DataFrame(
        rows
    )


    manifest = {
        "target":
            "target_relevance",

        "feature_columns": [
            "business_category",
            "preferred_division",
            "zone_division",
            "environment_cluster",
            "geometry_status",
            "geometry_method",
            "official_capacity",
            "commercial_poi_count_250m",
            "distance_to_major_road_m",
            "parking_count_500m",
        ],

        "categorical_features": [
            "business_category",
            "preferred_division",
            "zone_division",
            "environment_cluster",
            "geometry_status",
            "geometry_method",
        ],

        "numeric_features": [
            "official_capacity",
            "commercial_poi_count_250m",
            "distance_to_major_road_m",
            "parking_count_500m",
        ],
    }


    config = TrainingConfig(
        cv_folds=5,
        include_xgboost=(
            include_xgboost
        ),
        random_forest_estimators=100,
        xgboost_estimators=100,
        n_jobs=1,
    )


    result = train_models(
        dataset,
        manifest,
        config=config,
        save_artifacts=False,
    )


    report = result[
        "report"
    ]


    if (
        "random_forest"
        not in report[
            "models"
        ]
    ):

        raise AssertionError(
            "Random Forest result missing"
        )


    if len(
        result[
            "oof_predictions"
        ]
    ) != len(
        dataset
    ):

        raise AssertionError(
            "OOF prediction row count mismatch"
        )


    print(
        "Suitability model training "
        "self-test passed."
    )


    print(
        "Rows:",
        report[
            "dataset"
        ][
            "rows"
        ],
    )


    print(
        "Groups:",
        report[
            "dataset"
        ][
            "unique_groups"
        ],
    )


    print(
        "Grouped folds:",
        report[
            "dataset"
        ][
            "cv_folds"
        ],
    )


    print(
        "Baseline MAE:",
        f"{report['baseline']['metrics']['mae']:.4f}",
    )


    for (
        model_name,
        model_result,

    ) in report[
        "models"
    ].items():

        metrics = (
            model_result[
                "metrics"
            ]
        )


        print(
            f"{model_name} MAE:",
            f"{metrics['mae']:.4f}",
        )


        print(
            f"{model_name} RMSE:",
            f"{metrics['rmse']:.4f}",
        )


        spearman = (
            metrics[
                "spearman_rank_correlation"
            ]
        )


        print(
            f"{model_name} Spearman:",
            (
                f"{spearman:.4f}"
                if spearman
                is not None
                else "N/A"
            ),
        )


    print(
        "Selected:",
        report[
            "selected_model"
        ],
    )


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------


def print_training_summary(
    training: Mapping[
        str,
        Any,
    ],
) -> None:

    report = (
        training[
            "report"
        ]
    )


    print(
        "\nExperimental Suitability Model"
    )

    print(
        "=" * 35
    )


    print(
        "Rows:",
        report[
            "dataset"
        ][
            "rows"
        ],
    )


    print(
        "Groups:",
        report[
            "dataset"
        ][
            "unique_groups"
        ],
    )


    print(
        "Grouped CV folds:",
        report[
            "dataset"
        ][
            "cv_folds"
        ],
    )


    print(
        "\nGrouped mean baseline:"
    )


    baseline = (
        report[
            "baseline"
        ][
            "metrics"
        ]
    )


    print(
        f"  MAE:  {baseline['mae']:.4f}"
    )

    print(
        f"  RMSE: {baseline['rmse']:.4f}"
    )


    for (
        model_name,
        result,

    ) in report[
        "models"
    ].items():

        metrics = (
            result[
                "metrics"
            ]
        )


        print(
            f"\n{model_name}:"
        )


        print(
            f"  MAE:  {metrics['mae']:.4f}"
        )

        print(
            f"  RMSE: {metrics['rmse']:.4f}"
        )


        print(
            "  R²:",
            (
                f"{metrics['r2']:.4f}"
                if metrics[
                    "r2"
                ]
                is not None
                else "N/A"
            ),
        )


        print(
            "  Spearman:",
            (
                f"{metrics['spearman_rank_correlation']:.4f}"
                if metrics[
                    "spearman_rank_correlation"
                ]
                is not None
                else "N/A"
            ),
        )


        print(
            "  Within ±1:",
            f"{100 * metrics['within_one_point_rate']:.2f}%",
        )


        print(
            "  Rounded QWK:",
            (
                f"{metrics['rounded_quadratic_weighted_kappa']:.4f}"
                if metrics[
                    "rounded_quadratic_weighted_kappa"
                ]
                is not None
                else "N/A"
            ),
        )


        print(
            "  Beats baseline MAE:",
            result[
                "beats_grouped_mean_baseline_mae"
            ],
        )


    print(
        "\nSelected experimental model:",
        report[
            "selected_model"
        ],
    )


    print(
        "Selected model beats baseline:",
        report[
            "selected_model_beats_baseline_mae"
        ],
    )


    print(
        "\nThese results evaluate agreement "
        "with held-out expert judgments, "
        "not vendor business success."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Train and evaluate experimental "
            "expert-suitability models."
        )
    )


    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )


    self_test_parser = (
        subparsers.add_parser(
            "self-test",
            help=(
                "Run deterministic grouped "
                "training on synthetic data."
            ),
        )
    )


    self_test_parser.add_argument(
        "--with-xgboost",
        action="store_true",
    )


    train_parser = (
        subparsers.add_parser(
            "train",
            help=(
                "Train from aggregated "
                "expert-labelled data."
            ),
        )
    )


    train_parser.add_argument(
        "--dataset",
        default=str(
            MODEL_DATASET_PATH
        ),
    )


    train_parser.add_argument(
        "--manifest",
        default=str(
            FEATURE_MANIFEST_PATH
        ),
    )


    train_parser.add_argument(
        "--group-column",
        default="vendor_profile_id",
        choices=[
            "vendor_profile_id",
            "zone_id",
        ],
    )


    train_parser.add_argument(
        "--cv-folds",
        type=int,
        default=5,
    )


    train_parser.add_argument(
        "--skip-xgboost",
        action="store_true",
    )


    train_parser.add_argument(
        "--random-forest-estimators",
        type=int,
        default=300,
    )


    train_parser.add_argument(
        "--xgboost-estimators",
        type=int,
        default=300,
    )


    train_parser.add_argument(
        "--n-jobs",
        type=int,
        default=2,
    )


    train_parser.add_argument(
        "--no-save",
        action="store_true",
    )


    args = (
        parser.parse_args()
    )


    if (
        args.command
        == "self-test"
    ):

        self_test(
            include_xgboost=(
                args.with_xgboost
            )
        )

        return


    config = TrainingConfig(
        group_column=(
            args.group_column
        ),
        cv_folds=(
            args.cv_folds
        ),
        include_xgboost=(
            not args.skip_xgboost
        ),
        random_forest_estimators=(
            args.random_forest_estimators
        ),
        xgboost_estimators=(
            args.xgboost_estimators
        ),
        n_jobs=(
            args.n_jobs
        ),
    )


    training = train_from_files(
        dataset_path=(
            args.dataset
        ),
        manifest_path=(
            args.manifest
        ),
        config=config,
        save_artifacts=(
            not args.no_save
        ),
    )


    print_training_summary(
        training
    )


    if not args.no_save:

        print(
            "\nSaved:"
        )

        print(
            "  comparison:",
            COMPARISON_REPORT_PATH,
        )

        print(
            "  OOF predictions:",
            OOF_PREDICTIONS_PATH,
        )

        print(
            "  selected model:",
            SELECTED_MODEL_PATH,
        )


if __name__ == "__main__":
    main()