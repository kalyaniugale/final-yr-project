"""02 V2 — Reproducible, fixed-context GIS features for Nashik reference zones.

Run from any directory: python scripts/02_build_zone_features.py
Raw inputs are read-only. Distances are metric, missing values remain missing.
No legal boundary, live vacancy, demand, or suitability is inferred here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
NMC = ROOT / "data" / "raw" / "nmc"
OSM = ROOT / "data" / "raw" / "osm"
OUT = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "data_quality"
METRIC_CRS = "EPSG:32643"
RADII = (250, 500)
FILES = {
    "roads": "roads_clean.gpkg",
    "commercial": "commercial_model_points.gpkg",
    "landuse": "landuse_clean.gpkg",
    "transport": "transport_deduplicated.gpkg",
    "facilities": "facilities_deduplicated.gpkg",
}
# Explicit, editable taxonomy. Unrecognized tags are reported, never guessed.
TAXONOMY = {
    "road_major": ["motorway", "trunk", "primary", "secondary",
                   "motorway_link", "trunk_link", "primary_link", "secondary_link"],
    "road_primary": ["motorway", "trunk", "primary", "motorway_link",
                     "trunk_link", "primary_link"],
    "road_secondary": ["secondary", "secondary_link"],
    "road_pedestrian": ["pedestrian", "footway", "path", "steps", "living_street"],
    "road_local": ["residential", "service", "tertiary", "unclassified",
                   "tertiary_link", "living_street"],
    "commercial_market": ["marketplace", "market", "market_hall"],
    "commercial_food": ["restaurant", "cafe", "fast_food", "food_court",
                        "food", "bakery", "ice_cream", "shop_bakery", "shop_dairy",
                        "shop_butcher", "shop_cheese", "shop_confectionery",
                        "shop_beverages", "shop_nuts;spices"],
    "commercial_retail": ["mall", "retail_area", "commercial_area", "shop_general",
                          "shop_yes", "shop_kiosk", "shop_supermarket",
                          "shop_clothes", "shop_clothes (or clothes;fabric)",
                          "shop_fabric", "shop_mobile_phone",
                          "shop_mobile_phone_accessories", "shop_electronics",
                          "shop_electrical", "shop_hardware", "shop_houseware",
                          "shop_furniture", "shop_jewelry", "shop_stationery",
                          "shop_books", "shop_cosmetics", "shop_beauty",
                          "shop_florist", "shop_footwear", "shop_shoes",
                          "shop_bakery", "shop_dairy", "shop_butcher",
                          "shop_cheese", "shop_confectionery", "shop_beverages",
                          "shop_nuts;spices"],
    "commercial_service": ["shop_car_repair", "shop_hairdresser", "shop_copyshop",
                           "shop_photo_studio", "shop_bicycle", "shop_travel_agency",
                           "office_company", "office_it", "office_engineering",
                           "office_telecommunication"],
    "transport_bus": ["bus_stop", "bus_station", "bus_platform", "bus_stand"],
    "transport_bus_station": ["bus_station", "bus_stand"],
    "transport_ambiguous": ["transit_platform", "transit_stop_position"],
    "transport_rail": ["railway_station", "train_station", "railway_halt",
                      "railway_stop", "station", "halt"],
    "facility_healthcare": ["hospital", "clinic", "doctors", "dentist",
                            "healthcare", "health_centre"],
    "facility_education": ["school", "college", "university", "kindergarten",
                           "library", "education"],
    "facility_toilet": ["toilets", "toilet", "public_toilet"],
    "facility_parking": ["parking", "parking_entrance", "parking_space"],
    "landuse_residential": ["residential"],
    "landuse_commercial": ["commercial", "retail"],
    "landuse_industrial": ["industrial"],
    "landuse_park": ["park", "garden", "recreation_ground", "grass", "village_green"],
}
LOG = logging.getLogger("zone_features")


def normalized(series):
    return series.astype("string").fillna("").str.strip().str.lower()


def clean_text(value):
    return "" if pd.isna(value) else str(value).strip()


def checksum(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    return pd.read_csv(path, dtype="string", keep_default_na=False,
                       encoding="utf-8-sig")


def require_columns(frame, names, source):
    missing = set(names) - set(frame.columns)
    if missing:
        raise ValueError(f"{source}: missing columns {sorted(missing)}")


def unique_ids(frame, col, source):
    ids = frame[col].astype("string").fillna("").str.strip()
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError(f"{source}: empty or duplicate {col}")


def read_spatial(path, expected, label):
    if not path.exists():
        raise FileNotFoundError(path)
    g = gpd.read_file(path)
    if g.crs is None:
        raise ValueError(f"{label}: CRS is missing; cannot calculate metres")
    if g.empty:
        raise ValueError(f"{label}: empty dataset")
    if g.geometry.isna().any() or g.geometry.is_empty.any():
        LOG.warning("%s: dropping %s missing/empty geometries",
                    label, int((g.geometry.isna() | g.geometry.is_empty).sum()))
        g = g.loc[g.geometry.notna() & ~g.geometry.is_empty].copy()
    bad = ~g.geometry.is_valid
    if bad.any():
        LOG.warning("%s: dropping %s invalid geometries", label, int(bad.sum()))
        g = g.loc[~bad].copy()
    wrong = ~g.geom_type.isin(expected)
    if wrong.any():
        raise ValueError(f"{label}: unexpected geometry types {g.loc[wrong].geom_type.unique().tolist()}")
    g = g.to_crs(METRIC_CRS)
    g = g.reset_index(drop=True)
    g["_fid"] = np.arange(len(g), dtype=int)
    return g


def classify(g, key, groups, audit):
    require_columns(g, [key], key)
    values = normalized(g[key])
    result = {}
    for group in groups:
        allowed = set(TAXONOMY[group])
        result[group] = values.isin(allowed)
    for label, count in values.value_counts(dropna=False).items():
        audit.append({"source": key, "feature_type": str(label),
                      "count": int(count),
                      "matched_groups": "|".join(k for k, mask in result.items()
                                                if label in TAXONOMY[k])})
    return result


def union_area(geometries):
    """Measure union area, not sum of overlapping OSM land-use polygons."""
    if not geometries:
        return 0.0
    return float(unary_union(geometries).area)


def nearby(frame, geometry):
    """Spatial index bounding-box query followed by exact intersection."""
    if frame.empty:
        return frame
    positions = list(frame.sindex.query(geometry, predicate="intersects"))
    return frame.iloc[positions]


def count_points(frame, geometry):
    return int(len(nearby(frame, geometry)))


def distance_to(frame, geometry):
    """Distance to nearest actual source geometry; NaN if source class absent."""
    if frame.empty:
        return np.nan
    # STRtree-backed nearest lookup; only distances to actual objects are measured.
    positions, distances = frame.sindex.nearest(
        geometry, return_all=False, return_distance=True)
    return float(distances[0]) if len(distances) else np.nan


def line_length(frame, geometry):
    selected = nearby(frame, geometry)
    return float(selected.geometry.intersection(geometry).length.sum()) if len(selected) else 0.0


def put_count(row, name, frame, buffer):
    row[name] = count_points(frame, buffer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--high-only", action="store_true",
                        help="Use only HIGH source-confidence geometries.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)

    manifest = []
    def record(path, count):
        manifest.append({"file": str(path.relative_to(ROOT)),
                         "sha256": checksum(path), "records": int(count)})

    master_path = NMC / "official_zones.csv"
    geo_path = NMC / "official_zones_geometries.geojson"
    master = read_csv(master_path)
    require_columns(master, ["zone_id", "division", "zone_type", "capacity"], master_path.name)
    unique_ids(master, "zone_id", "official zones")
    record(master_path, len(master))

    geo = gpd.read_file(geo_path)
    require_columns(geo, ["zone_id", "geometry_usable_for_reference_model",
                          "geometry_status", "geometry_source_evidence",
                          "geometry_method", "source_confidence",
                          "official_boundary_verified"], geo_path.name)
    unique_ids(geo, "zone_id", "reference geometry")
    if geo.crs is None:
        raise ValueError("Reference geometry CRS is missing")
    if set(geo.zone_id.astype(str)) != set(master.zone_id.astype(str)):
        raise ValueError("Reference geometry and master zone IDs do not match")
    record(geo_path, len(geo))
    geo = geo.to_crs(METRIC_CRS).set_index("zone_id", drop=False)

    # The attribute master is canonical. Only geometry/provenance fields are joined.
    provenance = ["zone_id", "geometry_usable_for_reference_model", "geometry_status",
                  "geometry_source_evidence", "geometry_method", "source_confidence",
                  "geometry_review_status", "official_boundary_verified"]
    provenance = [c for c in provenance if c in geo]
    zones = master.merge(geo[provenance].drop(columns="zone_id", errors="ignore"),
                         left_on="zone_id", right_index=True, validate="one_to_one")
    zones = gpd.GeoDataFrame(
        zones, geometry=gpd.GeoSeries([geo.loc[zid].geometry for zid in zones.zone_id],
                                      index=zones.index, crs=METRIC_CRS), crs=METRIC_CRS)
    flag = normalized(zones["geometry_usable_for_reference_model"]).isin(["true", "1", "yes"])
    source_conf = normalized(zones["source_confidence"])
    valid = zones.geometry.notna() & ~zones.geometry.is_empty & zones.geometry.is_valid
    valid &= zones.geom_type.isin(["Polygon", "MultiPolygon"])
    if args.high_only:
        valid &= source_conf.eq("high")
    usable = flag & valid
    if ((flag) & ~valid).any():
        LOG.warning("Some flagged geometries are invalid or excluded; retaining them as missing")
    LOG.info("Reference geometry: %s usable / %s total", int(usable.sum()), len(zones))

    layers = {}
    audit = []
    for key, filename in FILES.items():
        expected = (["LineString", "MultiLineString"] if key == "roads" else
                    ["Polygon", "MultiPolygon"] if key == "landuse" else ["Point", "MultiPoint"])
        layers[key] = read_spatial(OSM / filename, expected, key)
        record(OSM / filename, len(layers[key]))
        LOG.info("%s: %s features", key, len(layers[key]))

    roads = layers["roads"]
    require_columns(roads, ["road_class", "highway"], "roads")
    # Prefer explicit highway value; road_class is used only for the documented
    # broad road classification. No missing highway is assumed to be a major road.
    highway = normalized(roads["highway"])
    road_class = normalized(roads["road_class"])
    road_groups = classify(roads, "highway",
                           ["road_major", "road_primary", "road_secondary", "road_pedestrian", "road_local"], audit)
    road_groups["road_major"] |= road_class.isin(["major", "primary", "secondary"])
    road_groups["road_primary"] |= road_class.eq("primary")
    road_groups["road_secondary"] |= road_class.eq("secondary")
    road_groups["road_pedestrian"] |= road_class.eq("pedestrian")

    commercial = layers["commercial"]
    transport = layers["transport"]
    facilities = layers["facilities"]
    landuse = layers["landuse"]
    cg = classify(commercial, "feature_type", ["commercial_market", "commercial_food", "commercial_retail",
                            "commercial_service"], audit)
    tg = classify(transport, "feature_type",
                  ["transport_bus", "transport_bus_station", "transport_rail",
                   "transport_ambiguous"], audit)
    fg = classify(facilities, "feature_type",
                  ["facility_healthcare", "facility_education", "facility_toilet", "facility_parking"], audit)
    # Land-use tagging is explicit, with leisure used only for parks/gardens.
    require_columns(landuse, ["landuse", "leisure"], "landuse")
    lu = normalized(landuse["landuse"])
    leisure = normalized(landuse["leisure"])
    lg = classify(landuse, "landuse",
                  ["landuse_residential", "landuse_commercial", "landuse_industrial", "landuse_park"], audit)
    lg["landuse_park"] |= leisure.isin(TAXONOMY["landuse_park"])
    for value, n in leisure.value_counts().items():
        audit.append({"source": "leisure", "feature_type":str(value),"count":int(n),
                      "matched_groups":"landuse_park" if value in TAXONOMY["landuse_park"] else ""})

    road_sub = {k:roads.loc[v].copy() for k,v in road_groups.items()}
    com_sub = {k:commercial.loc[v].copy() for k,v in cg.items()}
    trans_sub = {k:transport.loc[v].copy() for k,v in tg.items()}
    fac_sub = {k:facilities.loc[v].copy() for k,v in fg.items()}
    lu_sub = {k:landuse.loc[v].copy() for k,v in lg.items()}

    # Environmental context uses the representative point, not polygon-size buffers.
    rows = []
    spatial = {}
    for i, zone in zones.iterrows():
        zid = zone.zone_id
        row = {"zone_id":zid, "division":zone.division, "zone_type":zone.zone_type,
               "official_capacity":pd.to_numeric(zone.capacity,errors="coerce"),
               "geometry_usable_for_reference_model":bool(usable.loc[i]),
               "geometry_status":zone.geometry_status,
               "geometry_method":zone.geometry_method,
               "geometry_source_evidence":zone.geometry_source_evidence,
               "source_confidence":zone.source_confidence,
               "official_boundary_verified":False,
               "feature_reference_crs":METRIC_CRS,
               "feature_status":"REFERENCE_READY" if usable.loc[i] else "NO_USABLE_REFERENCE"}
        if "geometry_review_status" in zones:
            row["geometry_review_status"]=zone.geometry_review_status
        if not usable.loc[i]:
            rows.append(row)
            continue
        geom = zone.geometry
        centre = geom.representative_point()
        spatial[zid] = centre
        buffers = {r:centre.buffer(r) for r in RADII}
        row["reference_geometry_area_sqm"] = float(geom.area)
        row["reference_geometry_perimeter_m"] = float(geom.length)
        row["reference_point_easting"] = float(centre.x)
        row["reference_point_northing"] = float(centre.y)
        row["context_method"] = "REPRESENTATIVE_POINT_FIXED_BUFFER"
        # Distance is from the analytical reference point. Zero means intersection,
        # not a claim that the exact legal vending spot touches that feature.
        for name, frame in [
            ("primary_road",road_sub["road_primary"]),
            ("secondary_road",road_sub["road_secondary"]),
            ("major_road",road_sub["road_major"]),
            ("bus_access",trans_sub["transport_bus"]),
            ("bus_station",trans_sub["transport_bus_station"]),
            ("railway_station",trans_sub["transport_rail"])]:
            row[f"distance_to_{name}_m"] = distance_to(frame, centre)
        for radius in RADII:
            b=buffers[radius]
            put_count(row,f"commercial_poi_count_{radius}m",commercial,b)
            for key,frame in com_sub.items():
                label=key.replace("commercial_","")
                put_count(row,f"{label}_poi_count_{radius}m",frame,b)
            for key,frame in trans_sub.items():
                label=key.replace("transport_","")
                put_count(row,f"{label}_count_{radius}m",frame,b)
            for key,frame in fac_sub.items():
                label=key.replace("facility_","")
                put_count(row,f"{label}_count_{radius}m",frame,b)
            # Retain raw lengths for audit, but density is the preferred model feature.
            area_km2=b.area/1_000_000
            for name,frame in [("road",roads),("major_road",road_sub["road_major"]),
                               ("pedestrian_road",road_sub["road_pedestrian"]),
                               ("local_road",road_sub["road_local"])]:
                length=line_length(frame,b)
                row[f"{name}_length_{radius}m"]=length
                row[f"{name}_density_{radius}m_per_km2"]=length/area_km2
        b=buffers[500]
        category_clips={}
        for key,frame in lu_sub.items():
            clips=[x.intersection(b) for x in nearby(frame,b).geometry]
            category_clips[key]=unary_union(clips) if clips else None
            label=key.replace("landuse_","")
            row[f"{label}_land_ratio_500m"]=(
                float(category_clips[key].area/b.area) if category_clips[key] is not None else 0.0)
        all_land=[x.intersection(b) for x in nearby(landuse,b).geometry]
        union=unary_union(all_land) if all_land else None
        row["mapped_landuse_coverage_ratio_500m"]=float(union.area/b.area) if union is not None else 0.0
        category_geoms=[x for x in category_clips.values() if x is not None]
        category_union=unary_union(category_geoms) if category_geoms else None
        row["classified_landuse_coverage_ratio_500m"]=float(category_union.area/b.area) if category_union is not None else 0.0
        row["landuse_category_overlap_ratio_500m"]=max(
            0.0,sum(x.area for x in category_geoms)/b.area-row["classified_landuse_coverage_ratio_500m"])
        row["landuse_missing_coverage_ratio_500m"]=max(0.0,1-row["mapped_landuse_coverage_ratio_500m"])
        coverage=row["classified_landuse_coverage_ratio_500m"]
        # Conditional proportions describe mapped land only; not the whole neighbourhood.
        # Below 10% coverage they are deliberately unavailable for model use.
        row["landuse_composition_reliable"]=bool(coverage>=0.10)
        for label in ["residential","commercial","industrial","park"]:
            raw=row[f"{label}_land_ratio_500m"]
            row[f"{label}_mapped_share_500m"]=raw/coverage if coverage>=0.10 else np.nan
        row["feature_status"]="REFERENCE_READY"
        rows.append(row)

    features=pd.DataFrame(rows)
    # Every zone has the same schema; unavailable geometry-derived features stay NaN.
    metadata_columns = {
        "zone_id", "division", "zone_type", "official_capacity",
        "geometry_usable_for_reference_model", "geometry_status", "geometry_method",
        "geometry_source_evidence", "source_confidence", "official_boundary_verified",
        "feature_reference_crs", "feature_status", "geometry_review_status",
        "context_method", "landuse_composition_reliable",
        "reference_point_easting", "reference_point_northing"
    }
    feature_columns = [c for c in features.columns if c not in metadata_columns]
    features[feature_columns]=features[feature_columns].apply(pd.to_numeric,errors="coerce")
    assert len(features)==len(master)
    assert features.zone_id.is_unique
    assert features.loc[~features.geometry_usable_for_reference_model,feature_columns].isna().all().all()
    nonnegative=features[feature_columns].select_dtypes(include="number")
    assert not (nonnegative.lt(-1e-8).fillna(False)).any().any()
    ratio_columns=[c for c in feature_columns if "ratio" in c and "overlap_ratio" not in c]
    assert not (features[ratio_columns].gt(1+1e-7).fillna(False)).any().any()

    # Ensure no infinite values reach downstream model preprocessing.
    assert not np.isinf(features[feature_columns].to_numpy(dtype=float)).any()
    # Save source-independent GIS features separately from historical vendor evidence.
    csv_path=OUT/"zone_features.csv"
    features.to_csv(csv_path,index=False,encoding="utf-8-sig")
    geometry_series=gpd.GeoSeries([spatial.get(zid) for zid in features.zone_id],crs=METRIC_CRS)
    geo_out=gpd.GeoDataFrame(features.copy(),geometry=geometry_series,crs=METRIC_CRS)
    gpkg_path=OUT/"zone_features.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()
    geo_out.to_file(gpkg_path,layer="zone_features",driver="GPKG",index=False)

    pd.DataFrame(audit).to_csv(REPORT/"osm_feature_taxonomy.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(manifest).to_csv(REPORT/"feature_input_manifest.csv",index=False)
    feature_dictionary=[
        {"feature":c,"unit":("metres per square kilometre" if "density" in c else "metres" if c.endswith("_m") else "square metres" if c.endswith("_sqm")
          else "ratio" if "ratio" in c else "count" if "_count_" in c else "source attribute"),
         "definition":"OSM-derived reference-area environmental feature; see source code for spatial operator."}
        for c in feature_columns]
    pd.DataFrame(feature_dictionary).to_csv(REPORT/"feature_dictionary.csv",index=False,encoding="utf-8-sig")

    # A conservative starting shortlist, NOT automatically accepted for training.
    # Strongly correlated radius variants and draft geometry area are not included.
    suggested = [
        "distance_to_major_road_m", "road_density_250m_per_km2",
        "pedestrian_road_density_250m_per_km2",
        "commercial_poi_count_250m", "market_poi_count_500m",
        "food_poi_count_250m", "bus_count_500m",
        "distance_to_bus_access_m", "healthcare_count_500m",
        "education_count_500m", "toilet_count_500m", "parking_count_500m"
    ]
    # Use source-specific raw category names exactly as generated above.
    suggested = [c for c in suggested if c in feature_columns]
    (REPORT/"suggested_model_features.json").write_text(
        json.dumps({"status":"CANDIDATE_ONLY_NOT_TRAINED",
                    "features":suggested,
                    "notes":["Review correlations and distributions before training.",
                             "Land-use shares excluded pending coverage assessment.",
                             "Draft geometry area and perimeter are audit-only.",
                             "Raw counts are observed OSM presence proxies, not demand.",
                             "Do not use capacity or historical associations in environmental K-Means."]},
                   indent=2),encoding="utf-8")
    quality = []
    for c in feature_columns:
        values=features.loc[usable,c]
        quality.append({"feature":c,"missing":int(values.isna().sum()),
                        "zero_count":int(values.eq(0).sum()),
                        "nunique":int(values.nunique(dropna=True)),
                        "median":float(values.median()) if values.notna().any() else None,
                        "max":float(values.max()) if values.notna().any() else None})
    pd.DataFrame(quality).to_csv(REPORT/"feature_quality_v2.csv",index=False,encoding="utf-8-sig")
    metadata={
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "stage":"02_build_zone_features","version":"2.1.0",
        "metric_crs":METRIC_CRS,"buffer_radii_m":list(RADII),
        "geometry_semantics":"Analytical references, not official legal vending boundaries",
         "distance_semantics":"Minimum distance from representative point to source object",
         "count_semantics":"Distinct cleaned source records intersecting fixed-radius point buffers",
         "landuse_semantics":"Union area within fixed 500m point buffer; mapped composition requires at least 10% classified coverage",
        "data_limitations":["OSM coverage is incomplete","No observed footfall or sales",
          "No live occupancy or verified vacancies","No authoritative vending polygon area",
          "No inferred residential coordinates","Reference confidence is not verified positional accuracy"],
        "total_zones":len(features),"usable_references":int(usable.sum()),
        "missing_references":int((~usable).sum()),
        "feature_columns":feature_columns,
        "missing_feature_counts":{c:int(features[c].isna().sum()) for c in feature_columns},
        "taxonomy":TAXONOMY,
        "input_manifest":manifest,
        "outputs":[str(csv_path.relative_to(ROOT)),str(gpkg_path.relative_to(ROOT))]
    }
    (REPORT/"feature_build_metrics.json").write_text(json.dumps(metadata,indent=2,default=str),encoding="utf-8")
    print(f"\nCreated {csv_path}")
    print(f"Created {gpkg_path}")
    print(f"Zones: {len(features)} | Usable references: {int(usable.sum())} | Missing: {int((~usable).sum())}")
    print(f"Environmental feature columns: {len(feature_columns)}")
    print("No imputation, scaling, clustering, or suitability scoring has been applied.")
    print("Land-use shares with insufficient coverage remain missing; reference area is audit-only.")
    return 0


if __name__=="__main__":
    try:
        sys.exit(main())
    except Exception:
        LOG.exception("Feature build failed. Check input files and taxonomy; no raw data was changed.")
        sys.exit(1)
