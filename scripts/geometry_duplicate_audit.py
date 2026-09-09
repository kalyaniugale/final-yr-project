"""Audit shared analytical reference geometry without changing official zone identities.

Run: python scripts/geometry_duplicate_audit.py
Optional: --near-overlap 0.90 --near-distance-m 25

Exact duplicates are based on topological equality in EPSG:32643. Near matches
are review candidates only. No legal boundaries, allocations, or models change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/nmc/official_zones_geometries.geojson"
MASTER = ROOT / "data/raw/nmc/official_zones.csv"
OUT = ROOT / "reports/data_quality/geometry_duplicates"
METRIC_CRS = "EPSG:32643"
LOG = logging.getLogger("geometry_duplicate_audit")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_master():
    m = pd.read_csv(MASTER, dtype="string", keep_default_na=False,
                    encoding="utf-8-sig")
    required = {"zone_id", "division", "zone_type", "official_description"}
    if not required.issubset(m.columns):
        raise ValueError(f"Master missing columns: {sorted(required-set(m.columns))}")
    m["zone_id"] = m.zone_id.str.strip()
    if m.zone_id.eq("").any() or m.zone_id.duplicated().any():
        raise ValueError("Master zone IDs must be unique and nonempty.")
    return m


def geometry_key(geom):
    """Canonical topological key: insensitive to vertex start/order/orientation."""
    return hashlib.sha256(geom.normalize().wkb).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--near-overlap", type=float, default=0.90,
                        help="Minimum intersection-over-union for a near-duplicate candidate.")
    parser.add_argument("--near-distance-m", type=float, default=25.0,
                        help="Maximum representative-point distance for a near-duplicate candidate.")
    args = parser.parse_args()
    if not 0 < args.near_overlap <= 1 or args.near_distance_m < 0:
        raise ValueError("Invalid near-duplicate thresholds.")

    OUT.mkdir(parents=True, exist_ok=True)
    m = read_master()
    g = gpd.read_file(SOURCE)
    if g.crs is None:
        raise ValueError("Source geometry CRS is missing.")
    if "zone_id" not in g:
        raise ValueError("Geometry source has no zone_id.")
    g["zone_id"] = g.zone_id.astype("string").str.strip()
    if g.zone_id.eq("").any() or g.zone_id.duplicated().any():
        raise ValueError("Geometry zone IDs must be unique and nonempty.")
    if set(g.zone_id) != set(m.zone_id):
        raise ValueError("Master and geometry IDs differ; resolve this before auditing.")
    g = g.to_crs(METRIC_CRS).set_index("zone_id").loc[m.zone_id].reset_index()
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=METRIC_CRS)

    usable = []
    for _, row in g.iterrows():
        geom = row.geometry
        # Honor the existing source's usability flag when present.
        flag = row.get("geometry_usable_for_reference_model", True)
        allowed = str(flag).strip().lower() in ("true", "1", "yes")
        good = (allowed and geom is not None and not geom.is_empty
                and geom.is_valid and geom.geom_type in ("Polygon", "MultiPolygon")
                and geom.area > 0)
        usable.append(bool(good))
    g["_usable"] = usable
    good = g.loc[g._usable].copy().reset_index(drop=True)
    bad = g.loc[~g._usable, "zone_id"].tolist()

    # First hash normalized geometry; then verify actual topological equality.
    # Hashes are an acceleration, not the only definition of a duplicate.
    hash_groups = defaultdict(list)
    for i, geom in enumerate(good.geometry):
        hash_groups[geometry_key(geom)].append(i)

    exact_groups = []
    assigned = set()
    for indices in hash_groups.values():
        pending = list(indices)
        while pending:
            i = pending.pop(0)
            members = [i]
            rest = []
            for j in pending:
                if good.geometry.iloc[i].equals(good.geometry.iloc[j]):
                    members.append(j)
                else:
                    rest.append(j)
            pending = rest
            exact_groups.append(members)
            assigned.update(members)
    # Rare normalization differences may have identical topology. Check remaining
    # spatial-index candidates to make equality grouping independent of WKB ordering.
    parent = list(range(len(good)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a,b)] = min(a,b)

    for members in exact_groups:
        for j in members[1:]:
            union(members[0], j)

    for i, geom in enumerate(good.geometry):
        for j in good.sindex.query(geom, predicate="intersects"):
            j = int(j)
            if j <= i or find(i) == find(j):
                continue
            other = good.geometry.iloc[j]
            if abs(geom.area-other.area) <= max(1e-6, 1e-10*geom.area) and geom.equals(other):
                union(i,j)

    groups = defaultdict(list)
    for i in range(len(good)):
        groups[find(i)].append(i)
    ordered = sorted(groups.values(),
                     key=lambda indices: sorted(good.zone_id.iloc[indices].tolist())[0])
    ref_ids = {}
    group_rows = []
    for members in ordered:
        ids = sorted(good.zone_id.iloc[members].tolist())
        rid = "REF_" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:12].upper()
        geom = good.geometry.iloc[members[0]]
        for i in members:
            ref_ids[good.zone_id.iloc[i]] = rid
        group_rows.append({
            "reference_group_id":rid, "member_count":len(ids),
            "zone_ids":"|".join(ids), "geometry_area_sqm":float(geom.area),
            "shared_reference":len(ids)>1,
            "review_status":"UNVERIFIED_ANALYTICAL_REFERENCE",
            "note":"Identical analytical geometry does not establish identical legal vending areas."
        })

    # Near-duplicate candidates use one representative geometry per exact group.
    # Full pairwise comparison within bounding-box/centroid search range is bounded
    # by the number of exact groups, not the number of vendor records.
    representatives = [members[0] for members in ordered]
    rep = good.iloc[representatives].copy().reset_index(drop=True)
    rep["_rid"] = [ref_ids[z] for z in rep.zone_id]
    near_rows = []
    for i, geom in enumerate(rep.geometry):
        candidates = rep.sindex.query(geom.buffer(args.near_distance_m).envelope)
        for j in candidates:
            j=int(j)
            if j<=i:
                continue
            other=rep.geometry.iloc[j]
            # IoU measures geographic overlap, not legal identity.
            if not geom.intersects(other):
                continue
            intersection=geom.intersection(other).area
            union_area=geom.area+other.area-intersection
            iou=intersection/union_area if union_area>0 else 0
            if iou<args.near_overlap:
                continue
            distance=geom.representative_point().distance(other.representative_point())
            if distance>args.near_distance_m:
                continue
            near_rows.append({
                "reference_group_id_a":rep._rid.iloc[i],
                "reference_group_id_b":rep._rid.iloc[j],
                "zone_ids_a":"|".join(sorted(good.zone_id.iloc[ordered[i]].tolist())),
                "zone_ids_b":"|".join(sorted(good.zone_id.iloc[ordered[j]].tolist())),
                "intersection_over_union":float(iou),
                "representative_point_distance_m":float(distance),
                "review_status":"POTENTIAL_NEAR_DUPLICATE_NOT_MERGED"
            })

    metadata = m[["zone_id","division","zone_type","official_description"]].copy()
    geometry_meta = g[["zone_id","_usable"]].copy()
    for col in ["geometry_method","source_confidence","geometry_status",
                "geometry_review_status","official_boundary_verified"]:
        if col in g:
            geometry_meta[col]=g[col].values
    metadata=metadata.merge(geometry_meta,on="zone_id",validate="one_to_one")
    metadata["reference_group_id"]=metadata.zone_id.map(ref_ids)
    sizes={r["reference_group_id"]:r["member_count"] for r in group_rows}
    metadata["shared_reference_group_size"]=metadata.reference_group_id.map(sizes).fillna(0).astype(int)
    metadata["shared_reference"]=metadata.shared_reference_group_size.gt(1)
    metadata["reference_audit_status"]=np.where(metadata._usable,
        "REFERENCE_READY_SHARED" ,"NO_USABLE_REFERENCE")
    metadata.loc[metadata._usable & ~metadata.shared_reference,"reference_audit_status"]="REFERENCE_READY_UNIQUE"
    metadata["exact_site_verified"]=False
    metadata["reference_warning"]=np.where(metadata.shared_reference,
        "Environmental context is shared with other official zones; exact site-level distinction requires geometry verification.",
        np.where(metadata._usable,
          "Analytical reference only; official site-level boundary not independently verified.",
          "No usable analytical reference geometry."))
    metadata=metadata.drop(columns="_usable")
    pd.DataFrame(group_rows).to_csv(OUT/"reference_groups.csv",index=False,encoding="utf-8-sig")
    metadata.to_csv(OUT/"zone_reference_audit.csv",index=False,encoding="utf-8-sig")
    near_cols=["reference_group_id_a","reference_group_id_b","zone_ids_a","zone_ids_b",
               "intersection_over_union","representative_point_distance_m","review_status"]
    pd.DataFrame(near_rows,columns=near_cols).to_csv(
        OUT/"near_duplicate_candidates.csv",index=False,encoding="utf-8-sig")

    # Audit-only geometry layer for inspection; use representative points, not
    # artificially unioned legal vending polygons.
    points = good[["zone_id","geometry"]].copy()
    points["reference_group_id"]=points.zone_id.map(ref_ids)
    points["shared_reference_group_size"]=points.reference_group_id.map(sizes)
    points["geometry"]=points.geometry.representative_point()
    points=points.to_crs("EPSG:4326")
    points.to_file(OUT/"reference_points.geojson",driver="GeoJSON",index=False)

    shared=[r for r in group_rows if r["member_count"]>1]
    metrics={
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "source_sha256":digest(SOURCE),"master_sha256":digest(MASTER),
        "zone_count":len(m),"usable_reference_count":len(good),
        "unusable_reference_count":len(bad),"unique_reference_groups":len(ordered),
        "shared_reference_groups":len(shared),
        "zones_in_shared_reference_groups":sum(r["member_count"] for r in shared),
        "near_duplicate_candidate_pairs":len(near_rows),
        "near_overlap_threshold":args.near_overlap,
        "near_distance_threshold_m":args.near_distance_m,
        "limitations":["Topological equality of analytical references does not establish legal identity.",
                       "Near-duplicate candidates are not automatically merged.",
                       "No official zone IDs, raw geometries, features, or trained models were modified.",
                       "This audit does not resolve unknown legal boundaries or live capacity."]
    }
    (OUT/"audit_summary.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    print(f"Official zones: {len(m)} | Usable references: {len(good)} | Missing/unusable: {len(bad)}")
    print(f"Unique reference groups: {len(ordered)}")
    print(f"Shared reference groups: {len(shared)} | Zones sharing references: {metrics['zones_in_shared_reference_groups']}")
    print(f"Near-duplicate candidates for review: {len(near_rows)}")
    print(f"Reports: {OUT}")
    print("No raw geometry, official zone IDs, feature tables, or models were changed.")


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(levelname)s: %(message)s")
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
