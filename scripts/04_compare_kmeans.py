"""Compare K=2 and K=4 without changing the existing K-Means baseline.

Run: python scripts/04_compare_kmeans.py
The saved baseline preprocessing is reused exactly. Outputs go to a new folder.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score, calinski_harabasz_score,
    davies_bouldin_score, silhouette_score, silhouette_samples
)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/zone_features.csv"
BASELINE = ROOT / "models/kmeans/zone_kmeans.joblib"
OUT = ROOT / "data/model_outputs/kmeans/comparison"
MODEL_OUT = ROOT / "models/kmeans/comparison"
REPORT = ROOT / "reports/metrics"
SEEDS = [11, 23, 37, 53, 71]
K_VALUES = [2, 4]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_ids(df):
    if df.zone_id.isna().any() or df.zone_id.duplicated().any():
        raise ValueError("Zone IDs must be unique and nonempty.")


def transform_with_baseline(df, artifact):
    """Apply the fitted baseline preprocessing; never refit it on this comparison."""
    features = artifact["features"]
    x = df[features].apply(pd.to_numeric, errors="coerce")
    if np.isinf(x.to_numpy(dtype=float)).any() or (x < 0).any().any():
        raise ValueError("Invalid environmental feature values.")
    params = artifact["preprocessing"]
    logged = np.log1p(x)
    clipped = logged.clip(lower=params["lower"], upper=params["upper"], axis=1)
    filled = clipped.fillna(params["median"])
    scaled = params["scaler"].transform(filled) * params["weights"]
    return scaled[:, np.asarray(artifact["active_indices"], dtype=int)]


def evaluate(X, labels, model):
    sizes = np.bincount(labels, minlength=model.n_clusters)
    return {
        "silhouette": float(silhouette_score(X, labels)),
        "davies_bouldin": float(davies_bouldin_score(X, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(X, labels)),
        "inertia": float(model.inertia_),
        "min_cluster_size": int(sizes.min()),
        "max_cluster_size": int(sizes.max()),
    }


def fit_trials(X, k):
    trials = []
    for seed in SEEDS:
        model = KMeans(n_clusters=k, n_init=20, random_state=seed)
        labels = model.fit_predict(X)
        row = {"k": k, "seed": seed, **evaluate(X, labels, model)}
        trials.append({"model": model, "labels": labels, "row": row})
    return trials


def profile_table(df, labels, features):
    p = df[features].copy()
    p.insert(0, "cluster", labels)
    groups = p.groupby("cluster", sort=True)
    result = groups[features].median()
    result.insert(0, "zone_count", groups.size())
    return result.reset_index()


def main():
    for folder in (OUT, MODEL_OUT, REPORT):
        folder.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT, dtype={"zone_id": str})
    check_ids(df)
    artifact = joblib.load(BASELINE)  # Load only your own trusted local model file.
    expected = artifact.get("input_sha256")
    actual = sha256(INPUT)
    if expected != actual:
        raise ValueError(
            "The feature CSV differs from the saved baseline training input. "
            "Restore the matching input or explicitly retrain the baseline first."
        )

    train_ids = artifact["training_zone_ids"]
    if len(train_ids) != len(set(train_ids)):
        raise ValueError("Duplicate IDs in the baseline training population.")
    population = df.set_index("zone_id").loc[train_ids].reset_index()
    flag = population.geometry_usable_for_reference_model.astype(str).str.lower()
    if not flag.isin(["true", "1", "yes"]).all():
        raise ValueError("Baseline training population contains unusable references.")

    features = artifact["features"]
    X = transform_with_baseline(population, artifact)
    if not np.isfinite(X).all():
        raise ValueError("Preprocessing produced non-finite values.")
    if len(X) <= max(K_VALUES):
        raise ValueError("Insufficient training records.")
    print(f"Comparing K=2 and K=4 on {len(X)} identical training zones.")
    print("Reusing the saved baseline preprocessing and feature order.")

    trial_rows, summary_rows, selected = [], [], {}
    for k in K_VALUES:
        trials = fit_trials(X, k)
        trial_rows.extend(t["row"] for t in trials)
        aris = [
            adjusted_rand_score(a["labels"], b["labels"])
            for i, a in enumerate(trials) for b in trials[i + 1:]
        ]
        # Choose a representative run by minimum inertia, with seed as a tie-break.
        chosen = min(trials, key=lambda t: (t["model"].inertia_, t["row"]["seed"]))
        selected[k] = chosen
        sizes = np.bincount(chosen["labels"], minlength=k)
        summary_rows.append({
            "k": k,
            "silhouette_mean": float(np.mean([t["row"]["silhouette"] for t in trials])),
            "silhouette_std": float(np.std([t["row"]["silhouette"] for t in trials])),
            "stability_ari_mean": float(np.mean(aris)),
            "stability_ari_min": float(np.min(aris)),
            "selected_seed": int(chosen["row"]["seed"]),
            **{key: value for key, value in chosen["row"].items()
               if key not in ("k", "seed")},
        })
        print(f"K={k}: silhouette={summary_rows[-1]['silhouette_mean']:.4f}, "
              f"ARI={np.mean(aris):.4f}, sizes={sizes.tolist()}")

    pd.DataFrame(trial_rows).to_csv(OUT / "seed_metrics.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(OUT / "comparison_metrics.csv", index=False)

    assignments = population[["zone_id", "division"]].copy()
    for k in K_VALUES:
        chosen = selected[k]
        labels = chosen["labels"]
        model = chosen["model"]
        assignments[f"cluster_k{k}"] = labels
        assignments[f"distance_k{k}"] = np.min(model.transform(X), axis=1)
        assignments[f"silhouette_k{k}"] = silhouette_samples(X, labels)
        profile_table(population, labels, features).to_csv(
            OUT / f"profiles_k{k}.csv", index=False)
        pd.crosstab(
            population["division"], labels, rownames=["division"], colnames=["cluster"]
        ).to_csv(OUT / f"division_distribution_k{k}.csv")
        joblib.dump({
            "model": model,
            "preprocessing": artifact["preprocessing"],
            "active_indices": artifact["active_indices"],
            "features": features,
            "groups": artifact["groups"],
            "selected_k": k,
            "training_zone_ids": train_ids,
            "input_sha256": actual,
            "version": "comparison-1.0.0",
        }, MODEL_OUT / f"zone_kmeans_k{k}.joblib")

    assignments.to_csv(OUT / "assignments_k2_k4.csv", index=False)
    pd.crosstab(
        assignments["cluster_k2"], assignments["cluster_k4"],
        rownames=["K2 cluster"], colnames=["K4 cluster"]
    ).to_csv(OUT / "k2_k4_crosstab.csv")
    cross_ari = adjusted_rand_score(assignments.cluster_k2, assignments.cluster_k4)

    # Verify the new K=2 run against the original saved model, allowing label permutation.
    original_labels = artifact["model"].predict(X)
    baseline_ari = adjusted_rand_score(original_labels, assignments.cluster_k2)
    original_metrics = evaluate(X, original_labels, artifact["model"])
    pd.DataFrame([{"comparison":"original_baseline_vs_new_k2",
                   "adjusted_rand_index":baseline_ari,
                   "original_silhouette":original_metrics["silhouette"],
                   "new_silhouette":float(silhouette_score(X, assignments.cluster_k2))},
                  {"comparison":"k2_vs_k4","adjusted_rand_index":cross_ari}]).to_csv(
        OUT / "baseline_comparison.csv", index=False)

    metadata = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": actual,
        "baseline_model": str(BASELINE.relative_to(ROOT)),
        "training_rows": len(X),
        "k_values": K_VALUES,
        "seeds": SEEDS,
        "preprocessing": "Exact saved baseline parameters; no refitting.",
        "selection": "Minimum-inertia representative run for each K. No final K selected.",
        "original_baseline_vs_k2_ari": baseline_ari,
        "k2_vs_k4_ari": cross_ari,
        "limitations": [
            "Metrics measure environmental clustering, not suitability accuracy.",
            "Random-seed stability is not spatial, bootstrap, or source-data stability.",
            "K=4 is not automatically better because it has more clusters.",
            "Source confidence and geometry-method sensitivity remain to be evaluated.",
            "Historical vendor evidence and legal/capacity constraints are not training inputs.",
        ],
    }
    (REPORT / "kmeans_comparison.json").write_text(json.dumps(metadata, indent=2),
                                                    encoding="utf-8")
    print(f"\nOriginal baseline vs new K=2 ARI: {baseline_ari:.4f}")
    print(f"K=2 vs K=4 ARI: {cross_ari:.4f}")
    print(f"Saved comparison outputs to: {OUT}")
    print("Existing baseline model and outputs were not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
