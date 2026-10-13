"""Provisional map geometry. Original boundaries are never repaired or replaced."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import affinity
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import transform
from shapely.validation import explain_validity
from shapely.errors import ShapelyError

from backend.repositories.database import ROOT, OperationalValidationError

BOUNDARY_PATH = ROOT / "data/pilot/lekha_nagar_boundaries.geojson"
IDS = {"2974": "Boundary A", "3577": "Boundary B"}
TO_METRIC = Transformer.from_crs(4326, 32643, always_xy=True)
TO_MAP = Transformer.from_crs(32643, 4326, always_xy=True)
TOL = 0.002


def metric(geometry):
    try:
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise OperationalValidationError("Invalid or empty map geometry")
        projected = transform(TO_METRIC.transform, polygon)
        if projected.is_empty or not projected.is_valid:
            raise OperationalValidationError("Geometry cannot be projected to UTM 43N")
        return projected
    except (ShapelyError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise OperationalValidationError("Invalid WGS84 map geometry") from exc


def geographic(geometry):
    return mapping(transform(TO_MAP.transform, geometry))


def load_boundaries(path=BOUNDARY_PATH):
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise OperationalValidationError("The proposed boundary GeoJSON is missing or unreadable") from exc
    if data.get("type") != "FeatureCollection" or len(data.get("features", [])) != 2:
        raise OperationalValidationError("Exactly two proposed polygon features are required")
    found = {}
    for feature in data["features"]:
        identifier = str(feature.get("properties", {}).get("id"))
        if identifier not in IDS or identifier in found:
            raise OperationalValidationError("Expected unique property IDs 2974 and 3577")
        geometry = feature.get("geometry", {})
        try:
            polygon = shape(geometry)
        except (ShapelyError, ValueError, TypeError, KeyError) as exc:
            raise OperationalValidationError("Invalid boundary coordinates") from exc
        if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.is_empty:
            raise OperationalValidationError(f"{IDS[identifier]}: {explain_validity(polygon)}")
        # Pilot-local extent catches swapped coordinates or a wrong CRS.
        if not box(73.6, 19.8, 74.0, 20.2).covers(polygon):
            raise OperationalValidationError("Boundary coordinates must be Nashik WGS84 longitude, latitude")
        found[identifier] = {"type": "Feature", "geometry": geometry,
            "properties": {**feature.get("properties", {}), "boundary_id": identifier,
                           "name": IDS[identifier], "zone_id": "NN_F_013",
                           "provenance": "USER_DRAWN_GEOMAN", "verification": "PROVISIONAL_NOT_SURVEYED"}}
    return {"features": [found[k] for k in IDS], "type": "FeatureCollection",
            "source_sha256": hashlib.sha256(raw).hexdigest()}


def heading(polygon):
    corners = list(polygon.minimum_rotated_rectangle.exterior.coords)
    edges = [(math.dist(a, b), math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180)
             for a, b in zip(corners, corners[1:])]
    return max(edges)[1]


def pose_geometry(longitude, latitude, angle):
    if not all(math.isfinite(v) for v in (longitude, latitude, angle)):
        raise OperationalValidationError("Slot pose must contain finite coordinates")
    if not 73.6 <= longitude <= 74 or not 19.8 <= latitude <= 20.2:
        raise OperationalValidationError("Slot position must be in the pilot locality")
    x, y = TO_METRIC.transform(longitude, latitude)
    return geographic(affinity.rotate(box(x - 1, y - 1, x + 1, y + 1), angle, origin=(x, y)))


def slot_pose(geometry):
    polygon = metric(geometry)
    coords = list(polygon.exterior.coords)
    angle = math.degrees(math.atan2(coords[1][1] - coords[0][1], coords[1][0] - coords[0][0]))
    lon, lat = TO_MAP.transform(polygon.centroid.x, polygon.centroid.y)
    return {"longitude": lon, "latitude": lat, "angle": angle}


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise OperationalValidationError(f"{label} must be between {low} and {high}")
    return float(value)


def normalize_config(config=None):
    config = config or {}
    if not isinstance(config, dict) or not isinstance(config.get("boundaries", {}), dict):
        raise OperationalValidationError("Invalid alignment configuration")
    result = {"spacing_m": _number(config.get("spacing_m", .5), .5, 5, "Spacing"),
              "clearance_m": _number(config.get("clearance_m", 1.2), 1.2, 5, "Clearance"),
              "boundaries": {}}
    for identifier in IDS:
        options = config.get("boundaries", {}).get(identifier, {})
        if not isinstance(options, dict):
            raise OperationalValidationError("Invalid boundary alignment options")
        side = options.get("side", "left")
        if side not in ("left", "right"):
            raise OperationalValidationError("Corridor side must be left or right in the chosen alignment frame")
        angle = options.get("angle")
        if angle is not None:
            angle = _number(angle, 0, 180, "Alignment angle")
        result["boundaries"][identifier] = {"side": side, "angle": angle}
    return result


def obstruction_geometry(longitude, latitude, radius_m=0.5):
    radius = _number(radius_m, .1, 10, "Obstruction radius")
    _ = pose_geometry(longitude, latitude, 0)
    x, y = TO_METRIC.transform(longitude, latitude)
    return geographic(Point(x, y).buffer(radius))


def validate_layout(layout, boundaries=None):
    boundaries = boundaries or load_boundaries()
    parents = {f["properties"]["boundary_id"]: metric(f["geometry"]) for f in boundaries["features"]}
    config = normalize_config(layout.get("config"))
    slots = layout.get("slots", [])
    if not isinstance(slots, list) or any(not isinstance(s, dict) for s in slots):
        raise OperationalValidationError("Slots must be an array of geometry records")
    if len(slots) > 10:
        raise OperationalValidationError("Pilot maximum is ten slots across both boundaries")
    corridors = {}
    for corridor in layout.get("corridors", []):
        identifier = corridor.get("boundary_id")
        if identifier not in parents or identifier in corridors:
            raise OperationalValidationError("Invalid or duplicate corridor parent")
        polygon = metric(corridor["geometry"])
        if polygon.geom_type != "Polygon" or not polygon.is_valid or not parents[identifier].buffer(TOL).covers(polygon):
            raise OperationalValidationError("Corridor must be a continuous contained polygon")
        lengths = [math.dist(a, b) for a, b in zip(polygon.minimum_rotated_rectangle.exterior.coords,
                                                  list(polygon.minimum_rotated_rectangle.exterior.coords)[1:])]
        if min(lengths) + TOL < config["clearance_m"] or polygon.minimum_rotated_rectangle.area - polygon.area > .01:
            raise OperationalValidationError("Corridor must be a rectangular continuous strip with the configured width")
        corridors[identifier] = polygon
    obstacles = []
    for obstruction in layout.get("obstructions", []):
        polygon = metric(obstruction["geometry"])
        if not polygon.is_valid or polygon.is_empty or polygon.geom_type != "Polygon":
            raise OperationalValidationError("Invalid observed obstruction")
        if not any(p.buffer(TOL).covers(polygon) for p in parents.values()):
            raise OperationalValidationError("Observed obstruction must be inside a proposed boundary")
        obstacles.append(polygon)
    seen, footprints = set(), []
    for slot in slots:
        sid, parent = slot.get("slot_id"), slot.get("parent_boundary_id")
        if sid not in {f"S{i:03d}" for i in range(1, 11)} or sid in seen or parent not in parents:
            raise OperationalValidationError("Slots require unique S001–S010 IDs and a valid parent boundary")
        seen.add(sid)
        polygon = metric(slot["geometry"])
        if polygon.geom_type != "Polygon" or not polygon.is_valid or len(polygon.interiors) or len(polygon.exterior.coords) != 5:
            raise OperationalValidationError(f"{sid}: expected a valid four-corner rectangle")
        vertices = list(polygon.exterior.coords)
        lengths = [math.dist(a, b) for a, b in zip(vertices, vertices[1:])]
        if any(abs(length - 2) > TOL for length in lengths) or abs(polygon.area - 4) > .005:
            raise OperationalValidationError(f"{sid}: dimensions must remain 2 m × 2 m")
        if not parents[parent].buffer(TOL).covers(polygon):
            raise OperationalValidationError(f"{sid}: outside {IDS[parent]}")
        if parent not in corridors:
            raise OperationalValidationError(f"{sid}: a pedestrian corridor is required")
        corridor = corridors[parent]
        if polygon.intersection(corridor).area > .0001:
            raise OperationalValidationError(f"{sid}: overlaps the pedestrian corridor")
        if polygon.distance(corridor) > .05:
            raise OperationalValidationError(f"{sid}: must adjoin its continuous pedestrian corridor")
        for other_id, other in footprints:
            if polygon.intersection(other).area > .0001 or polygon.distance(other) + TOL < config["spacing_m"]:
                raise OperationalValidationError(f"{sid}: overlaps or violates spacing with {other_id}")
        if any(polygon.intersects(o) for o in obstacles):
            raise OperationalValidationError(f"{sid}: intersects a recorded obstruction")
        footprints.append((sid, polygon))
    if any(c.intersects(o) for c in corridors.values() for o in obstacles):
        raise OperationalValidationError("Recorded obstruction blocks the continuous pedestrian corridor")
    return {"valid": True, "slot_count": len(slots), "metric_crs": "EPSG:32643",
            "dimension_tolerance_m": TOL, "containment": "PASS", "spacing": "PASS",
            "pedestrian_clearance": "PASS", "unknown_obstructions_assessed": False,
            "counts": {IDS[k]: sum(s["parent_boundary_id"] == k for s in slots) for k in IDS}}


def generate_geographic(config=None, boundaries=None, obstructions=None):
    boundaries = boundaries or load_boundaries()
    config = normalize_config(config)
    obstructions = obstructions or []
    obstacles = [metric(o["geometry"]) for o in obstructions]
    layout = {"zone_id": "NN_F_013", "georeferenced": True, "coordinate_system": "EPSG:4326",
              "metric_crs": "EPSG:32643", "geometry_verification_status": "PROVISIONAL_NOT_SURVEYED",
              "boundaries": boundaries, "source_sha256": boundaries["source_sha256"],
              "config": config, "slots": [], "corridors": [], "obstructions": obstructions,
              "rejections": [], "width_m": 2, "depth_m": 2,
              "spacing_m": config["spacing_m"], "clearance_m": config["clearance_m"]}
    for boundary_index, feature in enumerate(boundaries["features"]):
        identifier = feature["properties"]["boundary_id"]
        polygon = metric(feature["geometry"])
        origin = (polygon.centroid.x, polygon.centroid.y)
        angle = config["boundaries"][identifier]["angle"]
        angle = heading(polygon) if angle is None else angle
        rotated = affinity.rotate(polygon, -angle, origin=origin)
        low_x, low_y, high_x, high_y = rotated.bounds
        clearance, spacing = config["clearance_m"], config["spacing_m"]
        side = config["boundaries"][identifier]["side"]
        best, best_corridor = [], None
        # Deterministic 0.25 m search, conservative feasible rectangles. Not a
        # global packing optimizer or a claim of measured pavement orientation.
        for yi in range(max(0, int((high_y - low_y - 2 - clearance) / .25)) + 1):
            y = low_y + .005 + yi * .25
            if y + 2 + clearance > high_y:
                continue
            run, corridor = [], None
            for xi in range(max(0, int((high_x - low_x - 2) / .25)) + 1):
                x = low_x + .005 + xi * .25
                stall_y = y + clearance if side == "left" else y
                corridor_y = y if side == "left" else y + 2
                candidate = box(x, stall_y, x + 2, stall_y + 2)
                start = run[0].bounds[0] if run else x
                strip = box(start, corridor_y, x + 2, corridor_y + clearance)
                ground = affinity.rotate(candidate, angle, origin=origin)
                ground_strip = affinity.rotate(strip, angle, origin=origin)
                if run and candidate.distance(run[-1]) + TOL < spacing:
                    continue
                if not rotated.covers(candidate) or not rotated.covers(strip) or any(
                        ground.intersects(o) or ground_strip.intersects(o) for o in obstacles):
                    # Keep the best continuous run, then try a later stretch.
                    if len(run) > len(best):
                        best, best_corridor = run[:], corridor
                    run, corridor = [], None
                    continue
                run.append(candidate)
                corridor = strip
                if len(run) > len(best):
                    best, best_corridor = run[:], corridor
                if len(best) == 5:
                    break
            if len(best) == 5:
                break
        for index, candidate in enumerate(best):
            geometry = geographic(affinity.rotate(candidate, angle, origin=origin))
            layout["slots"].append({"slot_id": f"S{boundary_index * 5 + index + 1:03d}",
                "zone_id": "NN_F_013", "parent_boundary_id": identifier, "geometry": geometry,
                "width_m": 2, "depth_m": 2, "pose": slot_pose(geometry),
                "status": "AVAILABLE", "assigned_vendor_id": None,
                "geometry_verification_status": "PROVISIONAL_NOT_SURVEYED"})
        if best_corridor is not None:
            # Extend the reserved continuous corridor as far as valid at this
            # alignment. This allows later moves while preserving its width.
            x0, y0, x1, y1 = best_corridor.bounds
            while x1 + .25 <= high_x and rotated.covers(box(x0, y0, x1 + .25, y1)) and not any(
                    affinity.rotate(box(x0, y0, x1 + .25, y1), angle, origin=origin).intersects(o) for o in obstacles):
                x1 += .25
            layout["corridors"].append({"boundary_id": identifier, "assumed_side": side,
                "angle": angle, "width_m": clearance,
                "geometry": geographic(affinity.rotate(box(x0, y0, x1, y1), angle, origin=origin))})
        if len(best) < 5:
            layout["rejections"].append({"boundary_id": identifier, "requested": 5, "generated": len(best),
                "reason": "No additional valid 2 m stall plus continuous clearance found in the 0.25 m alignment search; boundary width, shape, spacing or observed obstructions constrain placement."})
    layout["validation"] = validate_layout(layout, boundaries)
    return layout
