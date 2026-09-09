"""Stage 01: read-only, reproducible audit of Nashik ML source data."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
NMC = ROOT / "data/raw/nmc"
OSM = ROOT / "data/raw/osm"
OUT = ROOT / "reports/data_quality"
CATEGORIES = ["vegetable_fruit", "food", "clothing", "flower",
              "general_goods", "other", "unknown"]
TYPES = {"FREE", "RESTRICTED", "NO_VENDING"}
DIVISIONS = {"Nashik East", "Nashik West", "Panchavati",
             "Nashik Road", "New Nashik", "Satpur"}
SCHEMAS = {
    "official_zones.csv": ["zone_id","division","zone_type","official_description","capacity"],
    "vendors.csv": ["vendor_id","source_serial_no","source_page","division",
        "business_type_original","business_type_english","business_category",
        "business_translation_status"],
    "vendor_zone_assignments.csv": ["vendor_id","division","location_group_id",
        "proposed_zone_id","match_status","match_score","verified_zone_id","allocation_status"],
    "zone_vendor_evidence.csv": ["zone_id","proposed_vendor_count",
        "text_associated_vendor_count","review_required_vendor_count"],
    "location_zone_crosswalk.csv": ["location_group_id","division","proposed_zone_id",
        "match_status","source_vendor_count"],
    "business_translation_audit.csv": ["business_type_original","business_category",
        "translation_status","vendor_count"],
}
OSM_FILES = ["roads_clean.gpkg","commercial_model_points.gpkg","landuse_clean.gpkg",
             "transport_deduplicated.gpkg","facilities_deduplicated.gpkg"]

def text(s):
    return s.astype("string").fillna("").str.strip()

def numeric(s):
    return pd.to_numeric(text(s).replace("", pd.NA), errors="coerce")

def filled(s):
    return text(s).ne("")

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_csv(path):
    return pd.read_csv(path, dtype="string", keep_default_na=False,
                       encoding="utf-8-sig", low_memory=False)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero on blocking errors or warnings")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    issues, inventory, metrics = [], [], {}
    frames = {}
    def issue(level, code, message, count=None, examples=None):
        issues.append({"severity":level,"code":code,"message":message,
            "count":count,"examples":json.dumps(examples or [],ensure_ascii=False)})
    def check(condition, level, code, message, count=None, examples=None):
        if not condition: issue(level,code,message,count,examples)
    def inventory_file(path, rows=None):
        inventory.append({"path":str(path.relative_to(ROOT)),
            "bytes":path.stat().st_size,"sha256":sha256(path),"records":rows})
    def unique(df, col, label):
        ids = text(df[col])
        dup = ids.ne("") & ids.duplicated(keep=False)
        check(not ids.eq("").any(),"ERROR","EMPTY_ID",f"{label}: empty {col}",
              int(ids.eq("").sum()))
        check(not dup.any(),"ERROR","DUPLICATE_ID",f"{label}: duplicate {col}",
              int(dup.sum()),ids[dup].head(10).tolist())
    def foreign(values, valid, label, allow_empty=True):
        v=text(values)
        bad=v.ne("") & ~v.isin(valid)
        if not allow_empty: bad |= v.eq("")
        check(not bad.any(),"ERROR","UNKNOWN_REFERENCE",label,
              int(bad.sum()),v[bad].head(10).tolist())
    def number_check(df,col,label,nonnegative=True,integer=False):
        if col not in df: return None
        s=text(df[col]); n=numeric(s)
        bad=s.ne("") & n.isna()
        if nonnegative: bad |= n.lt(0).fillna(False)
        if integer: bad |= n.notna() & n.mod(1).ne(0)
        check(not bad.any(),"ERROR","INVALID_NUMBER",f"{label}.{col}",
              int(bad.sum()),s[bad].head(10).tolist())
        return n
    def compare_counts(expected, actual, label):
        e=expected.reindex(actual.index,fill_value=0).astype(int)
        a=actual.astype(int)
        bad=e.ne(a)
        check(not bad.any(),"ERROR","COUNT_MISMATCH",label,
              int(bad.sum()),[{"key":str(k),"source":int(e[k]),"recomputed":int(a[k])}
                                for k in a[bad].index[:10]])

    for name,required in SCHEMAS.items():
        path=NMC/name
        if not path.exists():
            issue("ERROR","MISSING_FILE",f"Required file: {path.relative_to(ROOT)}")
            continue
        try:
            df=read_csv(path)
            inventory_file(path,len(df))
            frames[name]=df
            missing=set(required)-set(df.columns)
            check(not missing,"ERROR","MISSING_COLUMNS",name,
                  len(missing),sorted(missing))
            check(len(df)>0,"ERROR","EMPTY_DATASET",name)
            check(len(df.columns)==len(set(df.columns)),"ERROR","DUPLICATE_COLUMNS",name)
            metrics[name]={"rows":len(df),"columns":len(df.columns),
                "missing_by_column":{c:int(text(df[c]).eq("").sum()) for c in df.columns}}
        except Exception as exc:
            issue("ERROR","READ_FAILURE",f"{name}: {exc}")

    z=frames.get("official_zones.csv")
    v=frames.get("vendors.csv")
    a=frames.get("vendor_zone_assignments.csv")
    e=frames.get("zone_vendor_evidence.csv")
    c=frames.get("location_zone_crosswalk.csv")
    t=frames.get("business_translation_audit.csv")
    if z is not None:
        unique(z,"zone_id","Official zones")
        check(text(z["zone_type"]).isin(TYPES).all(),"ERROR","INVALID_ZONE_TYPE","Unknown zone type")
        check(text(z["division"]).isin(DIVISIONS | {"Citywide"}).all(),"ERROR","INVALID_DIVISION","Unknown official division",
              int((~text(z["division"]).isin(DIVISIONS | {"Citywide"})).sum()),
              text(z.loc[~text(z["division"]).isin(DIVISIONS | {"Citywide"}),"division"]).drop_duplicates().tolist())
        number_check(z,"capacity","Official zones",integer=True)
        metrics["official_zone_type_counts"]=text(z["zone_type"]).value_counts().to_dict()
        metrics["missing_official_capacity"]=int(text(z["capacity"]).eq("").sum())
        zone_ids=set(text(z["zone_id"]))
        zone_lookup=z.set_index("zone_id")
    else: zone_ids=set()
    if v is not None:
        unique(v,"vendor_id","Vendors")
        vendor_ids=set(text(v["vendor_id"]))
        check(text(v["division"]).isin(DIVISIONS).all(),"ERROR","INVALID_DIVISION","Unknown vendor division")
        foreign(v["business_category"],set(CATEGORIES),"Unknown business category",False)
        metrics["business_category_counts"]=text(v["business_category"]).value_counts().to_dict()
        metrics["translation_status_counts"]=text(v["business_translation_status"]).value_counts().to_dict()
        missing_business=text(v["business_type_english"]).eq("") | text(v["business_category"]).eq("unknown")
        if missing_business.any():
            issue("WARNING","BUSINESS_REVIEW","Unresolved English business categories",
                  int(missing_business.sum()))
        if {"source_serial_no","source_page"}.issubset(v.columns):
            pair=text(v["source_serial_no"])+"|"+text(v["source_page"])
            check(not pair.duplicated().any(),"ERROR","DUPLICATE_SOURCE_ID",
                  "Vendor serial/page identity is not unique")
        if "phone_number" in v:
            phone=text(v["phone_number"])
            bad=phone.ne("") & ~phone.str.fullmatch(r"\+?[0-9]{10,15}").fillna(False)
            if bad.any(): issue("WARNING","PHONE_FORMAT","Phone fields require review",
                                int(bad.sum()))
    else: vendor_ids=set()
    if a is not None:
        unique(a,"vendor_id","Assignments")
        foreign(a["vendor_id"],vendor_ids,"Assignments reference unknown vendors",False)
        foreign(a["proposed_zone_id"],zone_ids,"Unknown proposed zone")
        foreign(a["verified_zone_id"],zone_ids,"Unknown verified zone")
        for col in ["match_score"]:
            n=number_check(a,col,"Assignments",nonnegative=True)
            if n is not None:
                bad=n.gt(100).fillna(False)
                check(not bad.any(),"ERROR","MATCH_SCORE_RANGE","Match scores exceed 100",int(bad.sum()))
        for col in ["verified_zone_id","allocation_status","spatial_verification_status"]:
            if col in a:
                metrics[f"assignment_{col}_counts"]=text(a[col]).value_counts().to_dict()
        metrics["assignment_match_status_counts"]=text(a["match_status"]).value_counts().to_dict()
        if v is not None:
            missing_ids=vendor_ids-set(text(a["vendor_id"]))
            check(not missing_ids,"ERROR","MISSING_ASSIGNMENT","Vendors without assignment records",
                  len(missing_ids),sorted(missing_ids)[:10])
            va=a.merge(v[["vendor_id","division","business_category"]],
                       on="vendor_id",suffixes=("_assignment","_vendor"),validate="one_to_one")
            mismatch=text(va["division_assignment"]).ne(text(va["division_vendor"]))
            check(not mismatch.any(),"ERROR","VENDOR_DIVISION_MISMATCH","Vendor division differs between files",
                  int(mismatch.sum()))
        if z is not None:
            for field in ["division","zone_type"]:
                source_col="proposed_zone_type" if field=="zone_type" else field
                if source_col in a:
                    expected=a["proposed_zone_id"].map(zone_lookup[field])
                    bad=filled(a["proposed_zone_id"]) & expected.notna() & text(a[source_col]).ne(text(expected))
                    check(not bad.any(),"ERROR","ZONE_ATTRIBUTE_MISMATCH",f"Assignment {source_col} differs from master",
                          int(bad.sum()))
            no_vending=set(z.loc[text(z["zone_type"]).eq("NO_VENDING"),"zone_id"])
            restricted=set(z.loc[text(z["zone_type"]).eq("RESTRICTED"),"zone_id"])
            for label,subset in [("NO_VENDING",no_vending),("RESTRICTED",restricted)]:
                count=int(text(a["proposed_zone_id"]).isin(subset).sum())
                if count: issue("INFO","HISTORICAL_LEGAL_STATUS",
                    f"{count} historical proposals reference {label} zones; do not treat as eligible allocation.",count)
        if "candidate_zone_ids" in a:
            for row in a[["vendor_id","candidate_zone_ids"]].itertuples(index=False):
                for zid in re.split(r"\s*[|;,]\s*",str(row.candidate_zone_ids).strip()):
                    if zid and zid not in zone_ids:
                        issue("ERROR","INVALID_ALTERNATIVE_ZONE",f"{row.vendor_id}: {zid}")
        metrics["proposed_vendor_count"]=int(filled(a["proposed_zone_id"]).sum())
    if e is not None:
        unique(e,"zone_id","Zone evidence")
        foreign(e["zone_id"],zone_ids,"Evidence references unknown zones",False)
        if z is not None:
            check(set(text(e["zone_id"]))==zone_ids,"ERROR","EVIDENCE_COVERAGE",
                  "Evidence must contain exactly one row per official zone")
        count_cols=[col for col in e.columns if col.endswith("_count")]
        for col in count_cols: number_check(e,col,"Evidence",integer=True)
        for col in ["verified_occupancy","verified_available_capacity"]:
            number_check(e,col,"Evidence",integer=True)
        if a is not None and v is not None and not a["vendor_id"].duplicated().any():
            joined=a.merge(v[["vendor_id","business_category"]],on="vendor_id",validate="one_to_one")
            joined=joined[filled(joined["proposed_zone_id"])]
            idx=e["zone_id"]
            total=joined.groupby("proposed_zone_id").size()
            compare_counts(total,e.set_index("zone_id")["proposed_vendor_count"].pipe(numeric).fillna(0),
                           "Proposed vendor counts")
            for status,col in [("text_association","text_associated_vendor_count"),
                               ("needs_review","review_required_vendor_count")]:
                counts=joined.loc[text(joined["match_status"]).eq(status)].groupby("proposed_zone_id").size()
                compare_counts(counts,e.set_index("zone_id")[col].pipe(numeric).fillna(0),col)
            for cat in CATEGORIES:
                col=cat+"_count"
                if col in e:
                    counts=joined.loc[text(joined["business_category"]).eq(cat)].groupby("proposed_zone_id").size()
                    compare_counts(counts,e.set_index("zone_id")[col].pipe(numeric).fillna(0),col)
            if "distinct_location_groups" in e:
                counts=joined[filled(joined["location_group_id"])].groupby("proposed_zone_id")["location_group_id"].nunique()
                compare_counts(counts,e.set_index("zone_id")["distinct_location_groups"].pipe(numeric).fillna(0),
                               "Distinct location groups")
        if z is not None:
            for col,left in [("official_capacity","capacity"),("division","division"),("zone_type","zone_type")]:
                if col in e:
                    expected=e["zone_id"].map(zone_lookup[left])
                    bad=text(e[col]).ne(text(expected))
                    check(not bad.any(),"ERROR","EVIDENCE_MASTER_MISMATCH",col,int(bad.sum()))
        for col in ["verified_occupancy","verified_available_capacity"]:
            if col in e and filled(e[col]).any():
                issue("WARNING","UNVERIFIED_LIVE_FIELD",
                      f"{col} is populated. Require source/date/approval before treating it as live.",int(filled(e[col]).sum()))
    if c is not None:
        unique(c,"location_group_id","Location crosswalk")
        foreign(c["proposed_zone_id"],zone_ids,"Crosswalk references unknown zone")
        if a is not None:
            foreign(a["location_group_id"],set(text(c["location_group_id"])),"Assignment references unknown location group")
            if "source_vendor_count" in c:
                actual=a[filled(a["location_group_id"])].groupby("location_group_id").size()
                compare_counts(actual,c.set_index("location_group_id")["source_vendor_count"].pipe(numeric).fillna(0),
                               "Crosswalk location-group counts")
    if t is not None and v is not None:
        # The original label, not the English translation, is the audit key.
        counts=v.groupby("business_type_original",dropna=False).size()
        if "vendor_count" in t:
            compare_counts(counts,t.set_index("business_type_original")["vendor_count"].pipe(numeric).fillna(0),
                           "Translation audit counts")
        # Blank source descriptions are legitimate audit groups, not missing IDs.
        check(not text(t["business_type_original"]).duplicated().any(),
              "ERROR","DUPLICATE_TRANSLATION_LABEL","Translation audit contains duplicate original labels")

    # Geometry is audited separately from legal-zone attributes.
    geo_path=NMC/"official_zones_geometries.geojson"
    if not geo_path.exists():
        issue("ERROR","MISSING_GEOMETRY_FILE","Missing reference geometry GeoJSON")
    else:
        try:
            geo=gpd.read_file(geo_path)
            inventory_file(geo_path,len(geo))
            check("zone_id" in geo,"ERROR","MISSING_GEOMETRY_ID","Geometry must have zone_id")
            if "zone_id" in geo:
                unique(geo,"zone_id","Reference geometry")
                foreign(geo["zone_id"],zone_ids,"Geometry references unknown official zone",False)
                check(set(text(geo["zone_id"]))==zone_ids,"ERROR","GEOMETRY_COVERAGE",
                      "Reference geometry must contain every official zone ID")
            check(geo.crs is not None,"ERROR","MISSING_CRS","Reference geometry has no CRS")
            if geo.crs:
                geo=geo.to_crs("EPSG:4326")
            nonnull=geo.geometry.notna() & ~geo.geometry.is_empty
            valid=geo.geometry.is_valid.fillna(False)
            polygon=geo.geometry.geom_type.isin(["Polygon","MultiPolygon"])
            bad=nonnull & (~valid | ~polygon)
            check(not bad.any(),"ERROR","INVALID_ZONE_GEOMETRY","Invalid or non-polygon reference",
                  int(bad.sum()),text(geo.loc[bad,"zone_id"]).head(10).tolist())
            bounds=geo.geometry.bounds
            envelope=(bounds.minx.between(72.5,75) & bounds.maxx.between(72.5,75) &
                      bounds.miny.between(19,21) & bounds.maxy.between(19,21))
            bad=nonnull & ~envelope.fillna(False)
            check(not bad.any(),"ERROR","GEOMETRY_BOUNDS","Reference outside broad Nashik sanity envelope",
                  int(bad.sum()))
            if "geometry_usable_for_reference_model" in geo:
                flag=geo["geometry_usable_for_reference_model"].astype("string").str.lower().isin(["true","1","yes"])
                check(not (flag & ~nonnull).any(),"ERROR","USABLE_WITHOUT_GEOMETRY","Usable flag set on missing geometry")
                usable=flag & nonnull & valid & polygon & envelope.fillna(False)
            else:
                issue("WARNING","MISSING_GEOMETRY_CONFIDENCE","No usable-reference flag; all geometries require review.")
                usable=nonnull & valid & polygon & envelope.fillna(False)
            if "official_boundary_verified" in geo:
                verified=geo["official_boundary_verified"].astype("string").str.lower().isin(["true","1","yes"])
                if verified.any(): issue("WARNING","LEGAL_VERIFICATION_CLAIM","Verify source evidence for claimed legal boundaries",int(verified.sum()))
            if z is not None and "zone_type" in geo:
                expected=geo["zone_id"].map(zone_lookup["zone_type"])
                bad=expected.notna() & text(geo["zone_type"]).ne(text(expected))
                check(not bad.any(),"ERROR","GEOMETRY_ZONE_TYPE_MISMATCH","Geometry legal type differs from master",int(bad.sum()))
            metrics["geometry"]={"records":len(geo),"non_null":int(nonnull.sum()),
                "usable_references":int(usable.sum()),"missing":int((~nonnull).sum()),
                "invalid":int(bad.sum()) if False else int((nonnull & (~valid | ~polygon)).sum()),
                "source_status_counts":text(geo["geometry_status"]).value_counts().to_dict() if "geometry_status" in geo else {}}
            if usable.sum():
                metric_geo=geo.loc[usable].to_crs("EPSG:32643")
                areas=metric_geo.geometry.area
                check(areas.gt(0).all(),"ERROR","ZERO_AREA","Reference geometry has zero area")
                metrics["geometry"]["area_sqm_median"]=float(areas.median())
                # Very large buffers are not rejected automatically; they require inspection.
                huge=areas.gt(1_000_000)
                if huge.any(): issue("WARNING","LARGE_REFERENCE_GEOMETRY","Reference area exceeds 1 square kilometre",int(huge.sum()))
        except Exception as exc:
            issue("ERROR","GEOMETRY_READ_FAILURE",str(exc))

    for name in OSM_FILES:
        path=OSM/name
        if not path.exists():
            issue("ERROR","MISSING_OSM_FILE",f"Missing {name}")
            continue
        try:
            layer=gpd.read_file(path)
            inventory_file(path,len(layer))
            check(not layer.empty,"ERROR","EMPTY_OSM",name)
            check(layer.crs is not None,"ERROR","OSM_MISSING_CRS",name)
            if layer.crs:
                layer=layer.to_crs("EPSG:4326")
            nonnull=layer.geometry.notna() & ~layer.geometry.is_empty
            invalid=nonnull & ~layer.geometry.is_valid.fillna(False)
            if invalid.any(): issue("WARNING","OSM_INVALID_GEOMETRY",name,int(invalid.sum()))
            missing=int((~nonnull).sum())
            if missing: issue("WARNING","OSM_MISSING_GEOMETRY",name,missing)
            expected_types=(["LineString","MultiLineString"] if name.startswith("roads") else
                            ["Polygon","MultiPolygon"] if name.startswith("landuse") else ["Point","MultiPoint"])
            wrong=nonnull & ~layer.geometry.geom_type.isin(expected_types)
            if wrong.any(): issue("WARNING","OSM_GEOMETRY_TYPE",name,int(wrong.sum()),
                                 layer.loc[wrong].geometry.geom_type.head(5).tolist())
            metrics[name]={"records":len(layer),"missing_geometry":missing,
                           "invalid_geometry":int(invalid.sum()),
                           "geometry_types":layer.geometry.geom_type.value_counts().to_dict(),
                           "crs":"EPSG:4326"}
        except Exception as exc:
            issue("ERROR","OSM_READ_FAILURE",f"{name}: {exc}")

    # Historical records and draft geometry must never silently become live legal availability.
    issue("INFO","DATA_SEMANTICS","Historical proposed associations are not verified allocations, demand, sales, or live occupancy.")
    issue("INFO","GEOMETRY_SEMANTICS","Reference geometry is not an authoritative legal boundary or measured vending area.")
    issue("INFO","LABEL_REQUIREMENT","Supervised accuracy and ranking metrics require independent outcomes or expert relevance labels.")
    metrics["issues_by_severity"]=dict(Counter(x["severity"] for x in issues))
    metrics["audit_timestamp_utc"]=datetime.now(timezone.utc).isoformat()
    metrics["validator_version"]="1.0.0"
    metrics["ready_for_feature_engineering"]=not any(x["severity"]=="ERROR" for x in issues)
    pd.DataFrame(issues,columns=["severity","code","message","count","examples"]).to_csv(OUT/"issues.csv",index=False)
    pd.DataFrame(inventory).to_csv(OUT/"input_manifest.csv",index=False)
    (OUT/"metrics.json").write_text(json.dumps(metrics,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    lines=["# Nashik ML — Data quality report","",
           f"Generated: {metrics['audit_timestamp_utc']}","",
           f"Blocking errors: {metrics['issues_by_severity'].get('ERROR',0)}",
           f"Warnings: {metrics['issues_by_severity'].get('WARNING',0)}","",
           "## Summary"]
    for name in SCHEMAS:
        if name in metrics: lines.append(f"- {name}: {metrics[name]['rows']:,} records")
    if "geometry" in metrics:
        lines.append(f"- Usable reference geometries: {metrics['geometry']['usable_references']}")
    lines += ["","## Issues"]
    for x in issues:
        lines.append(f"- **{x['severity']} — {x['code']}**: {x['message']}" +
                     (f" ({x['count']})" if x["count"] is not None else ""))
    lines += ["","## Interpretation",
        "No source files were modified. Errors block dependable feature engineering.",
        "Warnings require investigation but do not automatically block exploratory work.",
        "Counts are computed from the present files, not hard-coded historical totals.",
        "The full input SHA-256 manifest makes this run reproducible.",
        "Reference geometry and historical associations must not be presented as legally verified or current occupancy.",
        "Training labels, model performance and suitability accuracy are not established by this audit."]
    (OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"\nReports: {OUT}")
    if any(x["severity"]=="ERROR" for x in issues): return 1
    if args.strict and any(x["severity"]=="WARNING" for x in issues): return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
