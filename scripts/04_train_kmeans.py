"""03 — Audited environmental K-Means experiments.

Uses only GIS environmental features. No suitability/outcome labels are invented.
Run: python scripts/03_train_kmeans.py
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import (silhouette_score, davies_bouldin_score,
                             calinski_harabasz_score, adjusted_rand_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, RobustScaler, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/zone_features.csv"
OUT = ROOT / "data/model_outputs/kmeans"
MODELS = ROOT / "models/kmeans"
REPORT = ROOT / "reports/metrics"
SEEDS = [11, 23, 37, 53, 71]
GROUPS = {
    "road_access": ["distance_to_major_road_m", "road_density_250m_per_km2",
                    "pedestrian_road_density_250m_per_km2"],
    "commercial": ["commercial_poi_count_250m", "market_poi_count_500m",
                   "food_poi_count_250m"],
    "transport": ["bus_count_500m", "distance_to_bus_access_m"],
    "facilities": ["healthcare_count_500m", "education_count_500m",
                   "toilet_count_500m", "parking_count_500m"],
}
DISTANCES = {"distance_to_major_road_m", "distance_to_bus_access_m"}
FEATURES = [f for group in GROUPS.values() for f in group]

def hash_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def transform_counts(x):
    return np.log1p(np.maximum(np.asarray(x,dtype=float),0))

def preprocess(x, variant="balanced"):
    """Fit preprocessing on the training population only."""
    # All selected features are nonnegative. Log reduces count/distance skew.
    logged=np.log1p(x)
    lower=logged.quantile(.01)
    upper=logged.quantile(.99)
    clipped=logged.clip(lower=lower,upper=upper,axis=1)
    median=clipped.median()
    filled=clipped.fillna(median)
    scaler=RobustScaler() if variant=="robust" else StandardScaler()
    scaled=scaler.fit_transform(filled)
    weights=np.array([1/np.sqrt(len(GROUPS[g])) for g,fs in GROUPS.items() for f in fs])
    if variant=="unweighted":
        weights=np.ones(len(FEATURES))
    return scaled*weights,{"lower":lower,"upper":upper,"median":median,
                            "scaler":scaler,"weights":weights,"variant":variant}

def apply_preprocess(x,params):
    logged=np.log1p(x)
    clipped=logged.clip(lower=params["lower"],upper=params["upper"],axis=1)
    filled=clipped.fillna(params["median"])
    return params["scaler"].transform(filled)*params["weights"]

def metrics_for(x,labels,model):
    return {"silhouette":float(silhouette_score(x,labels)),
            "davies_bouldin":float(davies_bouldin_score(x,labels)),
            "calinski_harabasz":float(calinski_harabasz_score(x,labels)),
            "inertia":float(model.inertia_)}

def experiment(x,k):
    trials=[]
    for seed in SEEDS:
        model=KMeans(n_clusters=k,n_init=20,random_state=seed)
        labels=model.fit_predict(x)
        if len(np.unique(labels))<2:
            continue
        trials.append((model,labels,metrics_for(x,labels,model)))
    if not trials:
        return None
    aris=[adjusted_rand_score(a[1],b[1])
          for i,a in enumerate(trials) for b in trials[i+1:]]
    scores=[t[2]["silhouette"] for t in trials]
    best=max(trials,key=lambda t:t[2]["silhouette"])
    sizes=np.bincount(best[1],minlength=k)
    result={"k":k,"silhouette_mean":float(np.mean(scores)),
            "silhouette_std":float(np.std(scores)),
            "stability_ari_mean":float(np.mean(aris)) if aris else np.nan,
            "stability_ari_min":float(np.min(aris)) if aris else np.nan,
            "min_cluster_size":int(sizes.min()),
            "max_cluster_size":int(sizes.max()),"best_seed":int(best[0].random_state)}
    result.update({key:val for key,val in best[2].items() if key!="silhouette"})
    return result,best

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--k-min",type=int,default=2)
    parser.add_argument("--k-max",type=int,default=8)
    parser.add_argument("--variant",choices=["balanced","unweighted","robust"],default="balanced")
    args=parser.parse_args()
    if args.k_min<2 or args.k_max<args.k_min:
        raise ValueError("Invalid K range")
    for p in (OUT,MODELS,REPORT):p.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(INPUT)
    missing=set(FEATURES+["zone_id","geometry_usable_for_reference_model"])-set(d.columns)
    if missing:raise ValueError(f"Missing columns: {sorted(missing)}")
    if d.zone_id.isna().any() or d.zone_id.duplicated().any():
        raise ValueError("Zone IDs must be unique and nonempty")
    mask=d.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"])
    population=d.loc[mask].copy().reset_index(drop=True)
    x=population[FEATURES].apply(pd.to_numeric,errors="coerce")
    if np.isinf(x.to_numpy()).any() or (x<0).any().any():
        raise ValueError("Invalid environmental values")
    # If all values are missing/constant, they cannot carry useful information.
    all_missing=x.columns[x.notna().sum()==0].tolist()
    if all_missing:raise ValueError(f"All-missing features: {all_missing}")
    if len(x)<args.k_max+1:raise ValueError("Insufficient zones for requested K range")
    transformed,params=preprocess(x,args.variant)
    variances=np.var(transformed,axis=0)
    active=np.flatnonzero(variances>1e-12)
    if len(active)<2:raise ValueError("Fewer than two nonconstant features")
    X=transformed[:,active]
    results=[];best_models={}
    for k in range(args.k_min,args.k_max+1):
        result=experiment(X,k)
        if result:
            row,best=result
            results.append(row);best_models[k]=best
            print(f"K={k} silhouette={row['silhouette_mean']:.4f} "
                  f"ARI={row['stability_ari_mean']:.4f} min_size={row['min_cluster_size']}")
    evaluation=pd.DataFrame(results)
    if evaluation.empty:raise ValueError("No valid clustering result")
    # Selection is a documented heuristic, not a claim of true optimal K.
    minimum=max(3,int(np.ceil(.02*len(X))))
    eligible=evaluation[(evaluation.min_cluster_size>=minimum)&
                        (evaluation.stability_ari_mean>=.80)].copy()
    selection_note="Silhouette among stable, non-tiny cluster solutions."
    if eligible.empty:
        eligible=evaluation.copy()
        selection_note="No solution met stability/size thresholds; provisional silhouette selection."
    chosen=eligible.sort_values(["silhouette_mean","stability_ari_mean","k"],
                                ascending=[False,False,True]).iloc[0]
    k=int(chosen.k)
    model,labels,_=best_models[k]
    population["cluster"]=labels
    population["distance_to_centroid"]=np.min(model.transform(X),axis=1)
    # Save all official records, including those without usable references.
    result=d.merge(population[["zone_id","cluster","distance_to_centroid"]],
                   on="zone_id",how="left",validate="one_to_one")
    result.to_csv(OUT/"zones_with_clusters.csv",index=False,encoding="utf-8-sig")
    evaluation.to_csv(OUT/"k_evaluation.csv",index=False)
    profile=population.groupby("cluster")[FEATURES].median()
    profile.insert(0,"zone_count",population.groupby("cluster").size())
    profile.to_csv(OUT/"cluster_profiles.csv")
    population[["zone_id","cluster","distance_to_centroid"]].to_csv(
        OUT/"training_assignments.csv",index=False)
    artifact={"model":model,"preprocessing":params,"active_indices":active,
              "features":FEATURES,"groups":GROUPS,"selected_k":k,
              "training_zone_ids":population.zone_id.tolist(),
              "input_sha256":hash_file(INPUT),"version":"1.0.0"}
    joblib.dump(artifact,MODELS/"zone_kmeans.joblib")
    metadata={"generated_utc":datetime.now(timezone.utc).isoformat(),
              "input_sha256":hash_file(INPUT),"training_rows":len(population),
              "selected_k":k,"selection_note":selection_note,"variant":args.variant,
              "features":FEATURES,"active_features":[FEATURES[i] for i in active],
              "excluded_features":["official_capacity","zone_type",
                  "reference_geometry_area_sqm","reference_geometry_perimeter_m",
                  "all historical vendor evidence","all sparse land-use shares"],
              "limitations":["Unsupervised metrics do not measure suitability accuracy.",
                  "OSM is incomplete; zero observed POIs does not prove zero real-world POIs.",
                  "Reference points are approximate, not verified legal vending positions.",
                  "Candidate feature groups and thresholds require sensitivity testing.",
                  "No labels, outcomes, or expert judgments were used."]}
    (REPORT/"kmeans_run.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    print(f"\nSelected provisional K={k}. {selection_note}")
    print(f"Saved: {MODELS/'zone_kmeans.joblib'}")
    print(f"Reports: {OUT/'k_evaluation.csv'}")
    print("No suitability accuracy has been measured.")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
