"""Transparent exploratory MCDA recommendation engine, not a trained predictor."""
from __future__ import annotations
import argparse, json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/processed"
RAW=ROOT/"data/raw/nmc"
OUT=ROOT/"data/outputs"
CATEGORIES=["vegetable_fruit","food","clothing","flower","general_goods","other"]
WEIGHTS={"business":.25,"commercial":.20,"access":.20,"facilities":.15,"preference":.10,"historical":.10}
# Policy-configurable, illustrative baseline parameters, not learned coefficients.
def clip(x): return np.clip(x,0,1)
def saturation(x,scale): return clip(np.log1p(np.maximum(x,0))/np.log1p(scale))
def proximity(x,scale): return clip(np.exp(-np.maximum(x,0)/scale))
def num(s): return pd.to_numeric(s,errors="coerce")

def load():
    z=pd.read_csv(DATA/"candidate_zone_snapshot.csv",dtype={"zone_id":str})
    v=pd.read_csv(DATA/"vendor_training_registry.csv",dtype={"vendor_id":str})
    for d,key in [(z,"zone_id"),(v,"vendor_id")]:
        if d[key].isna().any() or d[key].duplicated().any(): raise ValueError("Invalid IDs")
    # The source file deliberately contains no verified live occupancy.
    # An officer-maintained snapshot is a separate, optional input.
    path=RAW/"zone_live_status.csv"
    if path.exists():
        live=pd.read_csv(path,dtype={"zone_id":str}).fillna("")
        required={"zone_id","verified_available_capacity","status","verified_at","verified_by"}
        if not required.issubset(live): raise ValueError("Invalid live status schema")
        if live.zone_id.duplicated().any() or not live.zone_id.isin(z.zone_id).all():
            raise ValueError("Invalid live status zone IDs")
        allowed={"OPEN","CLOSED","SUSPENDED","NO_VENDING","RESTRICTED"}
        if not live.status.astype(str).str.upper().isin(allowed).all():
            raise ValueError("Unknown live status; use OPEN, CLOSED, SUSPENDED, NO_VENDING or RESTRICTED")
        values=num(live.verified_available_capacity)
        if values.lt(0).any() or values.isna().any():
            raise ValueError("Live status records require nonnegative verified available capacity")
        z=z.merge(live[list(required)],on="zone_id",how="left",validate="one_to_one")
    else:
        for c in ["verified_available_capacity","status","verified_at","verified_by"]:
            z[c]=pd.NA
    audit=ROOT/"reports/data_quality/geometry_duplicates/zone_reference_audit.csv"
    if audit.exists():
        a=pd.read_csv(audit,dtype={"zone_id":str})
        if a.zone_id.duplicated().any():
            raise ValueError("Duplicate zone IDs in reference audit")
        cols=["zone_id","reference_group_id","shared_reference_group_size",
              "shared_reference","reference_warning"]
        z=z.merge(a[cols],on="zone_id",how="left",validate="one_to_one")
    else:
        z["reference_group_id"]=pd.NA
        z["shared_reference_group_size"]=pd.NA
        z["shared_reference"]=False
        z["reference_warning"]="Reference audit unavailable; exact site-level boundary not verified."
    return z,v

def recommend(business,division="",vendor_id="",top_n=3,exclude_zone="",
              require_verified=False):
    z,v=load()
    if vendor_id:
        found=v.loc[v.vendor_id.eq(vendor_id)]
        if len(found)!=1:raise ValueError("Unknown vendor ID")
        rec=found.iloc[0]
        if business=="":business=str(rec.business_category)
        if not division:division=str(rec.vendor_division)
        # A proposed historical association is not a verified current location.
        # Never exclude it automatically.
    if business not in CATEGORIES:raise ValueError("Select a known business category")
    if division and division not in set(z.loc[z.zone_division.ne("Citywide"),"zone_division"].dropna()):
        raise ValueError("Unknown division")
    if top_n<1 or top_n>20:raise ValueError("top_n must be 1–20")
    z=z.loc[z.zone_type.eq("FREE") &
        z.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"])].copy()
    if exclude_zone:
        if exclude_zone not in set(z.zone_id):
            raise ValueError("Excluded zone is not a valid FREE reference candidate")
        z=z.loc[z.zone_id.ne(exclude_zone)]
    z["live_available"]=num(z.verified_available_capacity)
    if z.live_available.lt(0).any():
        raise ValueError("Negative verified available capacity")
    z["live_status"]=z.status.fillna("").astype(str).str.upper()
    timestamps=pd.to_datetime(z.verified_at,errors="coerce",utc=True)
    age=pd.Timestamp.now(tz="UTC")-timestamps
    recent=age.ge(pd.Timedelta(0)) & age.le(pd.Timedelta(days=7))
    z["live_verified"]=z.live_status.eq("OPEN") & z.live_available.gt(0) & recent & (
        z.verified_by.fillna("").astype(str).str.strip().ne(""))
    z=z.loc[~z.live_status.isin(["CLOSED","SUSPENDED","NO_VENDING","RESTRICTED"]) &
            ~(z.live_available.notna() & z.live_available.le(0))]
    if require_verified:z=z.loc[z.live_verified]
    if z.empty:return pd.DataFrame()
    z=z.reset_index(drop=True)
    z["candidate_status"]=np.where(z.live_verified,"VERIFIED_SNAPSHOT","EXPLORATORY_UNVERIFIED")
    # Divisional preference is a ranking preference, not an invented hard constraint.
    # Prefer a full local top N, then fill explicitly from other divisions.
    local=z.zone_division.eq(division) if division else pd.Series(True,index=z.index)
    z["preference_score"]=np.where(local,1.0,.0) if division else .5
    z["fallback_used"]=False

    # Missing values stay unknown. Missing components are omitted with weight
    # renormalization; they never silently become zero accessibility.
    def feature(name):return num(z[name]) if name in z else pd.Series(np.nan,index=z.index)
    # Missing source features are not zero; mean of available components only.
    def mean_available(parts):
        return pd.concat(parts,axis=1).mean(axis=1,skipna=True)
    commercial=mean_available([saturation(feature("commercial_poi_count_250m"),12),
        saturation(feature("market_poi_count_500m"),4),saturation(feature("food_poi_count_250m"),8)])
    access=mean_available([proximity(feature("distance_to_major_road_m"),400),
        proximity(feature("distance_to_bus_access_m"),1000),
        saturation(feature("pedestrian_road_density_250m_per_km2"),5000)])
    facilities=mean_available([saturation(feature("healthcare_count_500m"),15),
        saturation(feature("education_count_500m"),6),saturation(feature("toilet_count_500m"),3),
        saturation(feature("parking_count_500m"),4)])
    # Recompute compatibility from historical text associations so the current
    # vendor's entire location group can be excluded (leave-group-out evidence).
    evidence=v.loc[v.match_status.eq("text_association") &
        v.proposed_zone_id.notna() & v.proposed_zone_id.ne("")].copy()
    if vendor_id:
        group=rec.location_group_id
        if pd.notna(group) and str(group).strip():
            evidence=evidence.loc[evidence.location_group_id.ne(group)]
        else:
            evidence=evidence.loc[evidence.vendor_id.ne(vendor_id)]
    counts=evidence.business_category.value_counts()
    total=int(counts.sum())
    prior=float(counts.get(business,0)/total) if total else 0.0
    grouped=evidence.groupby("proposed_zone_id")
    n_by=grouped.size()
    same_by=evidence.loc[evidence.business_category.eq(business)].groupby("proposed_zone_id").size()
    z["historical_zone_count"]=z.zone_id.map(n_by).fillna(0)
    z["historical_same_business_count"]=z.zone_id.map(same_by).fillna(0)
    z["citywide_business_share"]=prior
    z["smoothed_business_share"]=(z.historical_same_business_count+20*prior)/(z.historical_zone_count+20)
    z["historical_lift"]=z.smoothed_business_share/prior if prior>0 else np.nan
    n=num(z.historical_zone_count).fillna(0)
    same=num(z.historical_same_business_count).fillna(0)
    prior=num(z.citywide_business_share)
    # Lift is evidence about historic concentration, not demand or success.
    lift=num(z.historical_lift)
    business_score=clip(np.log1p(lift.clip(lower=0))/np.log(3))
    reliability=n/(n+20)
    # Confidence shrinks weak associations toward neutral; does not manufacture positives.
    business_score=.5+(business_score-.5)*reliability
    business_score=business_score.where(prior.gt(0),np.nan)
    history=saturation(n,50)
    components={"business":business_score,"commercial":commercial,"access":access,
        "facilities":facilities,"preference":z.preference_score,"historical":history}
    numerator=pd.Series(0.0,index=z.index)
    denominator=pd.Series(0.0,index=z.index)
    for name,series in components.items():
        z[name+"_score"]=series
        valid=series.notna()
        z[name+"_contribution"]=series.fillna(0)*WEIGHTS[name]*100
        numerator=numerator.add(series.fillna(0)*WEIGHTS[name])
        denominator=denominator.add(valid.astype(float)*WEIGHTS[name])
    z["score"]=100*numerator/denominator.replace(0,np.nan)
    z["score_coverage"]=denominator
    z["evidence_count"]=n
    z["evidence_method"]="TEXT_ASSOCIATIONS_LEAVE_LOCATION_GROUP_OUT" if vendor_id else "TEXT_ASSOCIATIONS_FULL_REFERENCE"
    z["same_business_count"]=same
    # No numeric score can authorize an allocation.
    z["score_type"]="ILLUSTRATIVE_MCDA_NOT_SUCCESS_PROBABILITY"
    z["limitations"]="OSM coverage incomplete; historical association is not success; reference geometry unverified; live status snapshot is not a permit"
    z["reference_warning"]=z.reference_warning.fillna("Analytical reference only; site-level verification required.")
    z["shared_reference"]=z.shared_reference.fillna(False).astype(bool)
    z["rank"]=0
    z=z.sort_values(["score","zone_id"],ascending=[False,True],na_position="last")
    if division:
        first=z.loc[z.zone_division.eq(division)].head(top_n)
        remaining=z.loc[~z.zone_id.isin(first.zone_id)].head(top_n-len(first)).copy()
        remaining["fallback_used"]=True
        result=pd.concat([first,remaining],ignore_index=True)
    else:result=z.head(top_n).copy().reset_index(drop=True)
    result["rank"]=np.arange(1,len(result)+1)
    result["reason"]=result.apply(lambda r:"; ".join(
        [f"{name}: {r[name+'_score']:.2f}" for name in WEIGHTS
         if pd.notna(r[name+"_score"])])+("; outside preferred division" if r.fallback_used else ""),axis=1)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--business",default="")
    p.add_argument("--division",default="")
    p.add_argument("--vendor-id",default="")
    p.add_argument("--exclude-zone",default="")
    p.add_argument("--top-n",type=int,default=3)
    p.add_argument("--require-verified",action="store_true")
    args=p.parse_args()
    result=recommend(args.business,args.division,args.vendor_id,args.top_n,
                     args.exclude_zone,args.require_verified)
    OUT.mkdir(parents=True,exist_ok=True)
    if result.empty:
        pd.DataFrame(columns=["rank","zone_id","zone_division","score","candidate_status",
                              "fallback_used","reason"]).to_csv(
            OUT/"recommendations.csv",index=False,encoding="utf-8-sig")
    else:
        result.to_csv(OUT/"recommendations.csv",index=False,encoding="utf-8-sig")
    if result.empty:
        print("No candidates meet the requested filters. No allocation can be inferred.")
    else:
        cols=["rank","zone_id","zone_division","score","candidate_status","fallback_used","reason"]
        print(result[cols].to_string(index=False))
    print("\nSaved:",OUT/"recommendations.csv")
    print("Scores are illustrative decision-support values, not probabilities or permits.")
    print("Only a municipal-authorized, recent status snapshot can establish verified availability.")

if __name__=="__main__":
    main()
