from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


# ---------------------------------------------------------
# PROJECT PATHS
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

FEATURES_FILE = ROOT / "data" / "processed" / "zone_features.csv"
ASSIGNMENTS_FILE = (
    ROOT / "data" / "model_outputs" / "kmeans" / "training_assignments.csv"
)
MODEL_FILE = ROOT / "models" / "kmeans" / "zone_kmeans.joblib"

OUTPUT_DIR = ROOT / "reports" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# SAME 12 FEATURES USED FOR K-MEANS
# ---------------------------------------------------------

FEATURE_COLS = [
    "distance_to_major_road_m",
    "road_density_250m_per_km2",
    "pedestrian_road_density_250m_per_km2",
    "commercial_poi_count_250m",
    "market_poi_count_500m",
    "food_poi_count_250m",
    "bus_count_500m",
    "distance_to_bus_access_m",
    "healthcare_count_500m",
    "education_count_500m",
    "toilet_count_500m",
    "parking_count_500m",
]


# ---------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------

features = pd.read_csv(FEATURES_FILE)
assignments = pd.read_csv(ASSIGNMENTS_FILE)

print("Features rows:", len(features))
print("Assignments rows:", len(assignments))

# Find cluster column automatically
possible_cluster_cols = [
    "cluster",
    "cluster_id",
    "kmeans_cluster",
    "cluster_label",
]

cluster_col = None

for col in possible_cluster_cols:
    if col in assignments.columns:
        cluster_col = col
        break

if cluster_col is None:
    raise ValueError(
        "Could not find cluster column.\n"
        f"Available assignment columns: {assignments.columns.tolist()}"
    )

print("Using cluster column:", cluster_col)


# ---------------------------------------------------------
# JOIN FEATURES WITH ACTUAL CLUSTER ASSIGNMENTS
# ---------------------------------------------------------

df = features.merge(
    assignments[["zone_id", cluster_col]],
    on="zone_id",
    how="inner",
)

print("Merged rows:", len(df))

if len(df) == 0:
    raise ValueError("No rows matched by zone_id.")


# ---------------------------------------------------------
# KEEP ONLY MODEL FEATURES
# ---------------------------------------------------------

X = df[FEATURE_COLS].copy()


# ---------------------------------------------------------
# PREPROCESSING FOR VISUALIZATION
#
# We reproduce the main transformations used before clustering:
# log1p -> clipping -> median imputation -> standardization.
#
# PCA is ONLY for plotting.
# ---------------------------------------------------------

# log1p for non-negative GIS variables
for col in FEATURE_COLS:
    X[col] = np.log1p(X[col].clip(lower=0))


# Clip to 1st and 99th percentiles
for col in FEATURE_COLS:
    low = X[col].quantile(0.01)
    high = X[col].quantile(0.99)

    X[col] = X[col].clip(lower=low, upper=high)


# Median imputation
X = X.fillna(X.median())


# Standardize manually for visualization
means = X.mean()
stds = X.std(ddof=0).replace(0, 1)

X_scaled = (X - means) / stds


# ---------------------------------------------------------
# PCA: 12 FEATURES -> 2 DIMENSIONS
# ---------------------------------------------------------

pca = PCA(n_components=2, random_state=42)
X_2d = pca.fit_transform(X_scaled)

df["PC1"] = X_2d[:, 0]
df["PC2"] = X_2d[:, 1]


print(
    "PCA explained variance:",
    pca.explained_variance_ratio_.round(4).tolist(),
)


# ---------------------------------------------------------
# BEFORE PLOT
# ---------------------------------------------------------

plt.figure(figsize=(10, 7))

plt.scatter(
    df["PC1"],
    df["PC2"],
    alpha=0.75,
    s=45,
)

plt.title(
    "Before K-Means Clustering\n"
    "258 GIS-Ready Vending Zones"
)
plt.xlabel("PCA Component 1")
plt.ylabel("PCA Component 2")

plt.grid(alpha=0.2)

plt.tight_layout()

before_file = OUTPUT_DIR / "kmeans_before.png"

plt.savefig(
    before_file,
    dpi=300,
    bbox_inches="tight",
)

plt.close()


# ---------------------------------------------------------
# AFTER PLOT
# ---------------------------------------------------------

plt.figure(figsize=(10, 7))

clusters = sorted(df[cluster_col].dropna().unique())

for cluster in clusters:

    subset = df[df[cluster_col] == cluster]

    plt.scatter(
        subset["PC1"],
        subset["PC2"],
        alpha=0.8,
        s=48,
        label=f"Cluster {cluster} (n={len(subset)})",
    )


# Calculate visible centers in PCA space
for cluster in clusters:

    subset = df[df[cluster_col] == cluster]

    center_x = subset["PC1"].mean()
    center_y = subset["PC2"].mean()

    plt.scatter(
        center_x,
        center_y,
        marker="X",
        s=220,
        edgecolors="black",
        linewidths=1.5,
    )


plt.title(
    "After K-Means Environmental Profiling\n"
    "Selected Baseline: K = 2"
)

plt.xlabel("PCA Component 1")
plt.ylabel("PCA Component 2")

plt.legend()

plt.grid(alpha=0.2)

plt.tight_layout()

after_file = OUTPUT_DIR / "kmeans_after.png"

plt.savefig(
    after_file,
    dpi=300,
    bbox_inches="tight",
)

plt.close()


# ---------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------

print()
print("Cluster distribution:")
print(df[cluster_col].value_counts().sort_index())

print()
print("Saved:")
print(before_file)
print(after_file)