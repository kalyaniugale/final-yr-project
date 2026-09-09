"""Read-only research recommendation API. Run with uvicorn api:app --reload."""
from __future__ import annotations
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mcda_engine import ROOT, DATA, recommend, CATEGORIES

app=FastAPI(title="Nashik Vendor Zoning Research API",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],
                   allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["Content-Type"])

def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(np.floating,)):return None if not np.isfinite(value) else float(value)
    if isinstance(value,(np.bool_,)):return bool(value)
    if value is None or value is pd.NA:return None
    if isinstance(value,float) and not np.isfinite(value):return None
    try:
        if pd.isna(value):return None
    except (TypeError,ValueError):pass
    return value

class Request(BaseModel):
    business: str=""
    division: str=""
    vendor_id: str=""
    exclude_zone: str=""
    top_n: int=Field(default=3,ge=1,le=20)
    require_verified: bool=False


FACTOR_WEIGHTS={"business":25,"commercial":20,"access":20,"facilities":15,"preference":10,"historical":10}
def metric(r,name,digits=0):
    value=r.get(name)
    try:
        x=float(value)
        if np.isfinite(x):return f"{x:,.{digits}f}"
    except (TypeError,ValueError):pass
    return None

def explain(r):
    """Source-grounded, deterministic explanations; no generated suitability claims."""
    def count(name):
        x=metric(r,name)
        return x if x is not None else "unknown"
    def distance(name):
        x=metric(r,name)
        return f"{x} m" if x is not None else "unknown"
    n=metric(r,"evidence_count")
    same=metric(r,"same_business_count")
    items={
      "business":{
        "title":"Business compatibility",
        "summary":f"{same or '0'} same-business records among {n or '0'} historical associations.",
        "details":"The score compares the business's historical concentration with its citywide share, using smoothing to reduce the influence of small samples. Presence is not evidence of successful sales.",
        "evidence":[{"label":"Same-business records","value":same or "0"},
                    {"label":"Historical associations","value":n or "0"},
                    {"label":"Evidence source","value":"Text-associated vendor records"}]},
      "commercial":{
        "title":"Commercial surroundings",
        "summary":f"{count('commercial_poi_count_250m')} mapped commercial POIs within 250 m; {count('market_poi_count_500m')} markets within 500 m.",
        "details":"Nearby mapped commercial activity provides context for possible customer activity. It is not measured footfall, sales, or a guarantee of demand.",
        "evidence":[{"label":"Commercial POIs · 250 m","value":count("commercial_poi_count_250m")},
                    {"label":"Markets · 500 m","value":count("market_poi_count_500m")},
                    {"label":"Food POIs · 250 m","value":count("food_poi_count_250m")}]},
      "access":{
        "title":"Road and transport access",
        "summary":f"{distance('distance_to_major_road_m')} from a major road and {distance('distance_to_bus_access_m')} from mapped bus access.",
        "details":"Distances are measured from an approximate analytical reference point. Road density and transport proximity describe access, not pedestrian footfall or traffic safety.",
        "evidence":[{"label":"Major-road distance","value":distance("distance_to_major_road_m")},
                    {"label":"Bus-access distance","value":distance("distance_to_bus_access_m")},
                    {"label":"Pedestrian-road density","value":(metric(r,"pedestrian_road_density_250m_per_km2") or "unknown")+" m/km²"}]},
      "facilities":{
        "title":"Nearby facilities",
        "summary":f"{count('healthcare_count_500m')} healthcare and {count('education_count_500m')} education features mapped within 500 m.",
        "details":"Infrastructure counts describe the surrounding environment. Missing OSM records should not be interpreted as proof that facilities do not exist.",
        "evidence":[{"label":"Healthcare · 500 m","value":count("healthcare_count_500m")},
                    {"label":"Education · 500 m","value":count("education_count_500m")},
                    {"label":"Public toilets · 500 m","value":count("toilet_count_500m")},
                    {"label":"Parking · 500 m","value":count("parking_count_500m")}]},
      "preference":{
        "title":"Preferred division",
        "summary":f"Located in {r.get('zone_division') or 'an unspecified division'}.",
        "details":"A preferred-division match receives a higher preference score. When fewer than three local candidates qualify, the system can show clearly identified alternatives outside the division.",
        "evidence":[{"label":"Zone division","value":r.get("zone_division")},
                    {"label":"Fallback","value":"Yes" if r.get("fallback_used") else "No"}]},
      "historical":{
        "title":"Historical evidence",
        "summary":f"{n or '0'} text-associated vendor records contribute to the evidence-density factor.",
        "details":"This measures the volume of historical association evidence, not current occupancy, available capacity, or commercial success. For an existing vendor, the recorded location group is excluded from its own evidence.",
        "evidence":[{"label":"Association records","value":n or "0"},
                    {"label":"Evidence method","value":r.get("evidence_method")}]} }
    result=[]
    for key,weight in FACTOR_WEIGHTS.items():
        item=items[key]
        score=r.get(key+"_score")
        contribution=r.get(key+"_contribution")
        result.append({"key":key,"label":item["title"],"score":score,
            "weight":weight,"contribution":contribution,
            "summary":item["summary"],"details":item["details"],"evidence":item["evidence"]})
    return result

@app.get("/api/health")
def health():return {"status":"ok","mode":"research"}

@app.get("/api/options")
def options():
    z=pd.read_csv(DATA/"candidate_zone_snapshot.csv",usecols=["zone_division"])
    divisions=sorted(x for x in z.zone_division.dropna().unique() if x!="Citywide")
    return {"categories":CATEGORIES,"divisions":divisions,"mode":"exploratory",
            "notice":"No live municipal availability is inferred from historical records."}

@app.get("/api/vendor/{vendor_id}")
def vendor(vendor_id:str):
    # Return only non-identifying model fields. This is not an identity-verification endpoint.
    v=pd.read_csv(DATA/"vendor_training_registry.csv",dtype={"vendor_id":str})
    found=v.loc[v.vendor_id.eq(vendor_id)]
    if found.empty:raise HTTPException(404,"Vendor ID not found")
    r=found.iloc[0]
    return clean({"vendor_id":r.vendor_id,"business_category":r.business_category,
        "division":r.vendor_division,"historical_proposed_zone_id":r.proposed_zone_id,
        "current_zone_verified":r.current_zone_verified,
        "notice":"A historical proposed zone is not a verified current vending location."})

@app.post("/api/recommendations")
def recommendations(req:Request):
    try:
        result=recommend(req.business,req.division,req.vendor_id,req.top_n,
                         req.exclude_zone,req.require_verified)
    except ValueError as exc:raise HTTPException(422,str(exc))
    if result.empty:
        return {"recommendations":[],"count":0,"mode":"research",
                "notice":"No candidates meet the selected filters. No allocation is inferred."}
    fields=["rank","zone_id","zone_division","official_description","official_capacity",
        "score","score_type","candidate_status","fallback_used","reference_group_id",
        "shared_reference","shared_reference_group_size","reference_warning",
        "geometry_method","source_confidence","environment_cluster","evidence_count",
        "same_business_count","score_coverage","limitations","reason",
        "verified_available_capacity","verified_at","live_verified","evidence_method",
        "distance_to_major_road_m","distance_to_bus_access_m",
        "pedestrian_road_density_250m_per_km2","commercial_poi_count_250m",
        "market_poi_count_500m","food_poi_count_250m","healthcare_count_500m",
        "education_count_500m","toilet_count_500m","parking_count_500m"]
    records=[]
    for _,r in result.iterrows():
        item={k:r.get(k) for k in fields}
        item["factors"]=explain(r)
        records.append(clean(item))
    return {"recommendations":records,"count":len(records),"mode":"research",
            "notice":"Illustrative decision-support scores, not probabilities, vacancies, or permits."}

@app.get("/api/zones/geometry")
def geometry():
    """Reference points only: do not draw draft shared polygons as official areas."""
    path=ROOT/"reports/data_quality/geometry_duplicates/reference_points.geojson"
    if not path.exists():raise HTTPException(503,"Run geometry_duplicate_audit.py first.")
    import json
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

@app.get("/api/zone/{zone_id}")
def zone(zone_id:str):
    z=pd.read_csv(DATA/"candidate_zone_snapshot.csv",dtype={"zone_id":str})
    r=z.loc[z.zone_id.eq(zone_id)]
    if r.empty:raise HTTPException(404,"Zone not found")
    return clean(r.iloc[0].to_dict())


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

@app.get("/api/implementation/summary")
def implementation_summary():
    """Non-sensitive implementation metrics for the local project dashboard."""
    zones = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id":str})
    vendors = pd.read_csv(DATA/"vendor_training_registry.csv", dtype={"vendor_id":str})
    candidate = pd.read_csv(DATA/"candidate_zone_snapshot.csv", dtype={"zone_id":str})
    geom = _read_json(ROOT/"reports/data_quality/geometry_duplicates/audit_summary.json")
    train = _read_json(ROOT/"reports/data_quality/training_data_metrics.json")
    kmeans_meta = _read_json(ROOT/"reports/metrics/kmeans_run.json")
    eval_path = ROOT/"data/model_outputs/kmeans/k_evaluation.csv"
    k_eval = pd.read_csv(eval_path).replace({np.nan: None}).to_dict("records") if eval_path.exists() else []
    return clean({
        "counts":{
            "official_zones":len(zones),
            "registered_vendors":len(vendors),
            "candidate_reference_zones":len(candidate),
            "historical_pairs":train.get("historical_proposed_pairs"),
            "usable_references":geom.get("usable_reference_count"),
            "unique_reference_groups":geom.get("unique_reference_groups"),
            "shared_reference_groups":geom.get("shared_reference_groups")
        },
        "kmeans":{
            "selected_k":kmeans_meta.get("selected_k",2),
            "training_rows":kmeans_meta.get("training_rows"),
            "variant":kmeans_meta.get("variant"),
            "evaluation":k_eval
        },
        "pipeline":[
            {"stage":"01","name":"Data validation","status":"complete","detail":"Schema, IDs, joins and source consistency"},
            {"stage":"02","name":"GIS feature engineering","status":"complete","detail":"Fixed-radius environmental features"},
            {"stage":"03","name":"Vendor-zone evidence","status":"complete","detail":"Historical pair registry and candidate snapshot"},
            {"stage":"04","name":"Environmental clustering","status":"complete","detail":"K-Means baseline and K comparison"},
            {"stage":"05","name":"Recommendation engine","status":"complete","detail":"Transparent weighted MCDA baseline"},
            {"stage":"06","name":"Expert relevance labels","status":"in_progress","detail":"Independent review workflow for supervised evaluation"}
        ],
        "model":{
            "ranking_model":"Weighted MCDA baseline",
            "environment_model":"K-Means environmental profiling",
            "explainability":"Exact weighted factor contributions",
            "shap_used":False
        }
    })

@app.get("/api/official-zones")
def official_zones(division: str = "", zone_type: str = "", limit: int = Query(308, ge=1, le=500)):
    z = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id":str})
    if division:
        z = z.loc[z.division.eq(division)]
    if zone_type:
        z = z.loc[z.zone_type.eq(zone_type)]
    audit_path = ROOT/"reports/data_quality/geometry_duplicates/zone_reference_audit.csv"
    if audit_path.exists():
        a = pd.read_csv(audit_path, dtype={"zone_id":str})
        cols=[c for c in ["zone_id","reference_group_id","shared_reference_group_size",
                          "shared_reference","reference_audit_status"] if c in a]
        z=z.merge(a[cols],on="zone_id",how="left",validate="one_to_one")
    cluster_path=ROOT/"data/model_outputs/kmeans/zones_with_clusters.csv"
    if cluster_path.exists():
        c=pd.read_csv(cluster_path,dtype={"zone_id":str})
        if "cluster" in c:
            z=z.merge(c[["zone_id","cluster"]].rename(columns={"cluster":"environment_cluster"}),
                      on="zone_id",how="left",validate="one_to_one")
    fields=[c for c in ["zone_id","division","zone_type","official_description","capacity","category",
                        "environment_cluster","reference_group_id","shared_reference_group_size",
                        "shared_reference","reference_audit_status"] if c in z]
    return {"zones":[clean(r) for r in z[fields].head(limit).to_dict("records")],
            "count":int(min(len(z),limit)),"total_matching":int(len(z))}


@app.get("/api/catalog")
def catalog(zone_type: str="",division: str="",q: str="",limit: int=308):
    """Official record catalogue; geometry and live status remain separate."""
    path=ROOT/"data/raw/nmc/official_zones.csv"
    d=pd.read_csv(path,dtype={"zone_id":str})
    if zone_type:d=d.loc[d.zone_type.eq(zone_type)]
    if division:d=d.loc[d.division.eq(division)]
    if q:
        words=q.strip()
        d=d.loc[d.zone_id.str.contains(words,case=False,na=False,regex=False) |
                d.official_description.str.contains(words,case=False,na=False,regex=False)]
    columns=["zone_id","division","zone_type","official_description","capacity","category"]
    return {"total":len(d),"zones":clean(d[columns].head(max(1,min(limit,308))).to_dict("records"))}

@app.get("/api/overview")
def overview():
    master=pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv")
    vendors=pd.read_csv(DATA/"vendor_training_registry.csv")
    features=pd.read_csv(DATA/"zone_features.csv")
    groups=master.zone_type.value_counts()
    audit=ROOT/"reports/data_quality/geometry_duplicates/audit_summary.json"
    audit_data=json.loads(audit.read_text()) if audit.exists() else {}
    return clean({"official_zones":len(master),"vendor_records":len(vendors),
        "reference_ready":int(features.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"]).sum()),
        "zone_types":groups.to_dict(),"reference_groups":audit_data.get("unique_reference_groups"),
        "shared_reference_zones":audit_data.get("zones_in_shared_reference_groups"),
        "model":{"clustering":"K-Means K=2 baseline","ranking":"Weighted MCDA",
                 "supervised":"Independent relevance collection in progress"}})

@app.get("/api/review-summary")
def review_summary():
    folder=ROOT/"reports/expert_review"
    path=folder/"expert_labels.csv"
    queue=folder/"review_queue.csv"
    if not queue.exists():
        return {"queue_count":0,"judgment_count":0,"reviewer_count":0,"rated_count":0,"abstained_count":0}
    q=pd.read_csv(queue)
    if not path.exists():
        return {"queue_count":len(q),"judgment_count":0,"reviewer_count":0,"rated_count":0,"abstained_count":0}
    d=pd.read_csv(path,dtype=str)
    return {"queue_count":len(q),"judgment_count":len(d),
        "reviewer_count":int(d.reviewer_id.nunique()),
        "rated_count":int(d.relevance.notna().sum()),
        "abstained_count":int(d.relevance.isna().sum())}
