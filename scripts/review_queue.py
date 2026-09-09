"""Create a score-blind, reproducible expert-review queue.

The queue is based on business profiles and zone strata, never MCDA rankings.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from mcda_engine import ROOT, DATA, CATEGORIES, load

OUT=ROOT/"reports/expert_review"
QUEUE=OUT/"review_queue.csv"
MANIFEST=OUT/"queue_manifest.json"
LABELS=OUT/"expert_labels.csv"
FIELDS=["zone_id","zone_division","official_description","environment_cluster",
        "geometry_status","geometry_method","geometry_source_evidence",
        "official_capacity","mapped_landuse_coverage_ratio_500m",
        "commercial_poi_count_250m","market_poi_count_500m","food_poi_count_250m",
        "distance_to_major_road_m","distance_to_bus_access_m","bus_count_500m",
        "healthcare_count_500m","education_count_500m","toilet_count_500m",
        "parking_count_500m"]

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def prepare(force=False):
    OUT.mkdir(parents=True,exist_ok=True)
    source=DATA/"candidate_zone_snapshot.csv"
    digest=sha(source)
    if QUEUE.exists() and not force:
        if not MANIFEST.exists():raise ValueError("Queue manifest missing; review before continuing.")
        manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest["source_sha256"]!=digest:
            raise ValueError("Source features changed. Archive the old review and create a new version; do not silently replace an active queue.")
        return pd.read_csv(QUEUE,dtype=str).fillna("")
    if force and LABELS.exists() and LABELS.stat().st_size>0:
        raise ValueError("Existing expert labels must be archived before rebuilding the queue.")
    z,_=load()
    z=z.loc[z.zone_type.eq("FREE") &
        z.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"])].copy()
    if z.empty:raise ValueError("No usable FREE reference candidates")
    z["stratum"]=z.zone_division.astype(str)+"|"+z.environment_cluster.fillna("NA").astype(str)
    z["_key"]=z.zone_id.map(lambda x:hashlib.sha256(("review-v1|"+x).encode()).hexdigest())
    chosen=z.sort_values("_key").groupby("stratum",group_keys=False).head(2)
    chosen=chosen.sort_values("_key").head(36)
    rows=[]
    for category in CATEGORIES:
        for _,r in chosen.iterrows():
            pid="P_"+hashlib.sha256(("v1|"+category+"|"+r.zone_id).encode()).hexdigest()[:14]
            row={"pair_id":pid,"vendor_profile_id":"PROFILE_"+category.upper(),
                 "business_category":category,"preferred_division":r.zone_division,
                 "evidence_version":"review-v1"}
            for field in FIELDS:row[field]=r.get(field,pd.NA)
            rows.append(row)
    queue=pd.DataFrame(rows)
    queue.to_csv(QUEUE,index=False,encoding="utf-8-sig")
    MANIFEST.write_text(json.dumps({"created_utc":datetime.now(timezone.utc).isoformat(),
        "source_sha256":digest,"source_file":str(source.relative_to(ROOT)),
        "queue_sha256":sha(QUEUE),"evidence_version":"review-v1",
        "selection":"Deterministic, at most two zones per division/cluster stratum, capped at 36 zones; six business profiles.",
        "notes":["Not sampled by MCDA score or historical business compatibility.",
                 "Not a probability sample of all possible vendor-zone pairs.",
                 "Reference zone geometry and live capacity are not independently verified.",
                 "Expert judgments are not verified business outcomes."]},
        indent=2),encoding="utf-8")
    return queue

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--force",action="store_true")
    args=p.parse_args()
    q=prepare(args.force)
    print(f"Review queue: {len(q)} pairs across {q.zone_id.nunique()} zones.")
    print("Saved:",QUEUE)
    print("No suitability labels have been generated.")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("ERROR:",exc,file=sys.stderr)
        sys.exit(1)
