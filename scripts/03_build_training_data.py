"""03 — Build auditable vendor-zone pairs and historical evidence.

No negative suitability labels, fabricated outcomes, or unverified vacancy.
Run: python scripts/03_build_training_data.py
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NMC = ROOT / "data/raw/nmc"
FEATURES = ROOT / "data/processed/zone_features.csv"
CLUSTERS = ROOT / "data/model_outputs/kmeans/zones_with_clusters.csv"
OUT = ROOT / "data/processed"
REPORT = ROOT / "reports/data_quality"
CATEGORIES = ["vegetable_fruit", "food", "clothing", "flower",
              "general_goods", "other", "unknown"]
REQUIRED = {
    "official_zones.csv": ["zone_id", "division", "zone_type", "capacity"],
    "vendors.csv": ["vendor_id", "division", "business_category",
                    "business_type_original", "business_type_english",
                    "business_translation_status"],
    "vendor_zone_assignments.csv": ["vendor_id", "location_group_id",
        "proposed_zone_id", "match_status", "match_score",
        "verified_zone_id", "allocation_status"],
    "zone_vendor_evidence.csv": ["zone_id", "proposed_vendor_count",
        "text_associated_vendor_count", "review_required_vendor_count"],
}
EVIDENCE_COLS = ["proposed_vendor_count", "text_associated_vendor_count",
    "review_required_vendor_count"] + [c + "_count" for c in CATEGORIES]

def read(path):
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype="string", keep_default_na=False,
                       encoding="utf-8-sig")

def txt(series):
    return series.astype("string").fillna("").str.strip()

def number(series):
    return pd.to_numeric(txt(series).replace("", pd.NA), errors="coerce")

def unique(frame, key, label):
    v = txt(frame[key])
    if v.eq("").any() or v.duplicated().any():
        raise ValueError(f"{label}: empty or duplicate {key}")

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize-pairs", action="store_true",
                        help="Explicitly generate the large unlabeled Cartesian pair table.")
    parser.add_argument("--max-pairs", type=int, default=2_000_000)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    inputs = {}
    manifest = []
    for name, columns in REQUIRED.items():
        path = NMC/name
        d = read(path)
        missing = set(columns)-set(d.columns)
        if missing:
            raise ValueError(f"{name}: missing {sorted(missing)}")
        inputs[name] = d
        manifest.append({"file":str(path.relative_to(ROOT)),
                         "sha256":sha256(path),"rows":len(d)})
    z = inputs["official_zones.csv"]
    v = inputs["vendors.csv"]
    a = inputs["vendor_zone_assignments.csv"]
    e = inputs["zone_vendor_evidence.csv"]
    for frame,key,label in [(z,"zone_id","Zones"),(v,"vendor_id","Vendors"),
                            (a,"vendor_id","Assignments"),(e,"zone_id","Evidence")]:
        unique(frame,key,label)
    zone_ids = set(z.zone_id)
    if set(e.zone_id)!=zone_ids or set(a.vendor_id)!=set(v.vendor_id):
        raise ValueError("Zone/vendor ID coverage differs between source tables.")
    if not txt(a.proposed_zone_id).replace("",pd.NA).dropna().isin(zone_ids).all():
        raise ValueError("Unknown proposed zone ID.")
    if not txt(a.verified_zone_id).replace("",pd.NA).dropna().isin(zone_ids).all():
        raise ValueError("Unknown verified zone ID.")
    if not txt(v.business_category).isin(CATEGORIES).all():
        raise ValueError("Unknown normalized business category.")
    if (txt(a.verified_zone_id)!="").any():
        raise ValueError("Verified allocations exist: review their provenance before extending this historical-only pipeline.")

    # Canonical zone attributes override duplicate or stale source columns.
    zone_cols = ["zone_id","division","zone_type","capacity","official_description"]
    zone_cols = [c for c in zone_cols if c in z]
    zone = z[zone_cols].rename(columns={"division":"zone_division",
        "capacity":"official_capacity"})
    zone["official_capacity"] = number(zone["official_capacity"])
    if zone.official_capacity.lt(0).any():
        raise ValueError("Negative official capacity.")
    f = read(FEATURES)
    unique(f,"zone_id","GIS features")
    if set(f.zone_id)!=zone_ids:
        raise ValueError("GIS features do not cover all official zone IDs.")
    manifest.append({"file":str(FEATURES.relative_to(ROOT)),
                     "sha256":sha256(FEATURES),"rows":len(f)})
    # Explicitly exclude duplicate legal/capacity attributes from GIS join.
    excluded = {"division","zone_type","official_capacity","official_description"}
    f = f.drop(columns=list(excluded),errors="ignore")
    zone = zone.merge(f,on="zone_id",validate="one_to_one")
    for field in ["reference_point_easting","reference_point_northing"]:
        if field in zone:
            zone = zone.drop(columns=field)
    # Feature-only records never supply independently verified capacity.


    if CLUSTERS.exists():
        c = read(CLUSTERS)
        unique(c,"zone_id","Cluster output")
        if set(c.zone_id)!=zone_ids:
            raise ValueError("Cluster output does not cover all official zones.")
        if "cluster" not in c:
            raise ValueError("Cluster output missing cluster column.")
        # Cluster IDs are retained as categorical features, not numeric rankings.
        c = c[["zone_id","cluster"]].rename(columns={"cluster":"environment_cluster"})
        c["environment_cluster"] = txt(c.environment_cluster).replace("",pd.NA)
        zone = zone.merge(c,on="zone_id",validate="one_to_one")
        manifest.append({"file":str(CLUSTERS.relative_to(ROOT)),
                         "sha256":sha256(CLUSTERS),"rows":len(c)})
    else:
        zone["environment_cluster"] = pd.NA

    # Read-only evidence: never use counts as verified occupancy or available places.
    evidence = e[["zone_id"]+EVIDENCE_COLS].copy()
    for col in EVIDENCE_COLS:
        evidence[col] = number(evidence[col])
        if evidence[col].isna().any() or evidence[col].lt(0).any():
            raise ValueError(f"Invalid evidence count: {col}")
    zone = zone.merge(evidence,on="zone_id",validate="one_to_one")
    expected = a.loc[txt(a.proposed_zone_id)!=""].groupby("proposed_zone_id").size()
    actual = zone.set_index("zone_id").proposed_vendor_count
    if not expected.reindex(actual.index,fill_value=0).astype(int).equals(actual.astype(int)):
        raise ValueError("Historical evidence does not reconcile with assignments.")

    # Reproducible observed-count compatibility: no fabricated successes/negatives.
    valid = a.merge(v[["vendor_id","business_category"]],on="vendor_id",validate="one_to_one")
    observed = valid.loc[txt(valid.proposed_zone_id)!=""].copy()
    compatibility_source = observed.loc[txt(observed.match_status)=="text_association"].copy()
    category_counts = compatibility_source.groupby(["proposed_zone_id","business_category"]).size()
    city_counts = compatibility_source.business_category.value_counts()
    city_total = int(city_counts.sum())
    if city_total == 0:
        raise ValueError("No historical proposed associations.")
    priors = {cat:int(city_counts.get(cat,0))/city_total for cat in CATEGORIES}
    # This is a transparent statistical reference, not a learned suitability model.
    alpha = 20.0
    compatibility = []
    for zid, group in compatibility_source.groupby("proposed_zone_id"):
        n = len(group)
        for cat in CATEGORIES:
            count = int(category_counts.get((zid,cat),0))
            share = (count + alpha*priors[cat])/(n+alpha)
            compatibility.append({"zone_id":zid,"business_category":cat,
                "historical_zone_count":n,"historical_same_business_count":count,
                "smoothed_business_share":share,"citywide_business_share":priors[cat],
                "historical_lift":share/priors[cat] if priors[cat]>0 else np.nan})
    pd.DataFrame(compatibility).to_csv(
        OUT/"historical_business_compatibility.csv",index=False,encoding="utf-8-sig")

    # A vendor's historical association is a retrieval target, not a suitability label.
    keep = ["vendor_id","division","business_type_original","business_type_english",
            "business_category","business_translation_status"]
    vendors = v[keep].rename(columns={"division":"vendor_division"})
    assignment_cols = ["vendor_id","location_group_id","proposed_zone_id","match_status",
                       "match_score","verified_zone_id","allocation_status"]
    assignment = a[assignment_cols].copy()
    assignment["match_score"] = number(assignment.match_score)
    if assignment.match_score.lt(0).any() or assignment.match_score.gt(100).any():
        raise ValueError("Match scores outside 0–100.")
    registry = vendors.merge(assignment,on="vendor_id",validate="one_to_one")
    registry.to_csv(OUT/"vendor_training_registry.csv",index=False,encoding="utf-8-sig")

    # Evidence rows retain every proposed mapping, including restricted and no-vending
    # historical records. Those are NOT recommended candidates.
    historical = registry.loc[txt(registry.proposed_zone_id)!=""].copy()
    historical = historical.rename(columns={"proposed_zone_id":"zone_id"})
    historical = historical.merge(zone,on="zone_id",validate="many_to_one")
    historical["pair_source"]="HISTORICAL_PROPOSED_ASSOCIATION"
    historical["relevance_label"]=pd.NA
    historical["suitability_label"]=pd.NA
    historical["label_status"]="UNLABELED"
    historical.to_csv(OUT/"historical_vendor_zone_pairs.csv",index=False,encoding="utf-8-sig")

    # Candidate universe is a deterministic policy snapshot, not an allocation.
    # Unknown live capacity remains unknown; eligibility is conditional on verification.
    eligible = zone.loc[(txt(zone.zone_type)=="FREE") &
        (zone.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"]))].copy()
    eligible["candidate_policy_status"]="REQUIRES_LIVE_CAPACITY_AND_MUNICIPAL_CHECK"
    eligible.to_csv(OUT/"candidate_zone_snapshot.csv",index=False,encoding="utf-8-sig")
    registry["request_division"]=registry.vendor_division
    registry["request_mode"]="EXPLORATORY_EXISTING_VENDOR"
    registry["current_zone_verified"]=pd.NA

    # We do not materialize millions of redundant rows unnecessarily. A canonical
    # candidate table plus vendor registry defines the complete Cartesian pair set.
    # The optional sample materializes a small, bounded test set, not training labels.
    pair_count = len(registry)*len(eligible)
    if args.materialize_pairs and pair_count <= args.max_pairs:
        lhs = registry[["vendor_id","business_category","request_division","request_mode",
                        "proposed_zone_id","current_zone_verified"]].copy()
        lhs["_join"]=1
        rhs = eligible.drop(columns=["official_description"],errors="ignore").copy()
        rhs["_join"]=1
        pairs = lhs.merge(rhs,on="_join",validate="many_to_many").drop(columns="_join")
        pairs["preferred_division_match"]=pairs.request_division.eq(pairs.zone_division)
        pairs["historical_proposed_zone_match"]=pairs.proposed_zone_id.eq(pairs.zone_id)
        pairs["relevance_label"]=pd.NA
        pairs["suitability_label"]=pd.NA
        pairs["label_status"]="UNLABELED"
        pairs.to_csv(OUT/"vendor_zone_pairs.csv",index=False,encoding="utf-8-sig")
        materialized=True
    else:
        materialized=False
        # Compact registry + zone snapshot define the complete pair universe.
        # Do not silently truncate or create an empty file pretending to be training data.
        if args.materialize_pairs:
            raise ValueError(f"{pair_count:,} pairs exceed --max-pairs={args.max_pairs:,}.")
        stale = OUT/"vendor_zone_pairs.csv"
        if stale.exists():
            stale.unlink()

    # Deterministic, group-aware development splits. These are NOT accuracy estimates.
    # All vendors from a location group stay together to avoid obvious group leakage.
    groups = registry.location_group_id.fillna("").astype(str)
    groups = groups.where(groups.ne(""),registry.vendor_id.astype(str))
    def split_group(g):
        value=int(hashlib.sha256(("nashik-v1|"+g).encode()).hexdigest()[:8],16)%100
        return "train" if value<70 else "validation" if value<85 else "test"
    registry["development_split"]=groups.map(split_group)
    # Match group splits back into the historical table without changing its labels.
    splits=registry[["vendor_id","development_split"]]
    historical = historical.merge(splits,on="vendor_id",validate="one_to_one")
    historical.to_csv(OUT/"historical_vendor_zone_pairs.csv",index=False,encoding="utf-8-sig")
    registry.to_csv(OUT/"vendor_training_registry.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame({"vendor_id":registry.vendor_id,
                  "location_group_id":groups,
                  "development_split":registry.development_split}).to_csv(
        OUT/"development_splits.csv",index=False,encoding="utf-8-sig")

    metrics = {
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "stage":"03_build_training_data","version":"1.0.0",
        "vendor_records":len(registry),"official_zones":len(zone),
        "historical_proposed_pairs":len(historical),
        "unmapped_vendor_records":int(txt(a.proposed_zone_id).eq("").sum()),
        "historical_text_associations":int((historical.match_status=="text_association").sum()),
        "historical_review_candidates":int((historical.match_status=="needs_review").sum()),
        "candidate_zones_before_live_capacity":len(eligible),
        "potential_pairs":pair_count,"pairs_materialized":materialized,
        "development_split_counts":registry.development_split.value_counts().to_dict(),
        "independent_suitability_labels":0,
        "historical_compatibility_records":len(compatibility_source),
        "historical_compatibility_alpha":alpha,
        "historical_compatibility_source":"text_association only; descriptive, not fitted suitability",
        "citywide_category_shares":priors,
        "input_manifest":manifest,
        "limitations":[
            "All candidate pairs are unlabeled for suitability.",
            "Proposed associations are not verified successful allocations.",
            "Unobserved pairs are not negative labels.",
            "Historical compatibility uses the full evidence set; it is not an outcome predictor.",
            "Compatibility must be fitted on training-only evidence during a future evaluated model.",
            "Historical evidence derived from the same vendors can leak targets if used as an evaluation feature.",
            "Current capacity and legal status require verified live municipal data.",
            "Reference geometry is not an official legal boundary.",
            "These development splits do not constitute a validated recommendation test set.",
            "No accuracy, F1, ROC-AUC, or NDCG is claimed.",
        ]
    }
    (REPORT/"training_data_metrics.json").write_text(
        json.dumps(metrics,indent=2,ensure_ascii=False),encoding="utf-8")
    print(f"Vendors: {len(registry):,} | Zones: {len(zone)}")
    print(f"Historical proposed pairs: {len(historical):,}")
    print(f"Unmapped vendor records: {metrics['unmapped_vendor_records']:,}")
    print(f"FREE reference candidates (pending live checks): {len(eligible)}")
    print(f"Potential vendor-zone pairs: {pair_count:,}")
    print(f"Full pair table materialized: {materialized}")
    if not materialized:
        print("Compact registry + candidate snapshot define the pair universe.")
        print("Optional: --materialize-pairs --max-pairs 2000000")
    print("Suitability labels: 0 independently verified.")
    print("Saved outputs to:",OUT)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:",exc,file=sys.stderr)
        sys.exit(1)
