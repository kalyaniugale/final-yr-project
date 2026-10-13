"""On-demand pedestrian routing. No location history or credentials in responses."""
from __future__ import annotations

import math
import os
import time
import threading
from urllib.parse import urlparse

import httpx
from shapely.geometry import Point, mapping

import backend.geo.pilot_geometry as gis
from backend.repositories.database import OperationalValidationError

_requests = {}
_lock = threading.Lock()


def destination(layout):
    slot = next((s for s in layout["slots"] if s["slot_id"] == layout.get("my_slot_id")), None)
    if not slot:
        return {"assigned": False, "message": "No vending slot has been assigned yet."}
    if not slot.get("geometry"):
        return {"assigned": True, "navigable": False, "slot_id": slot["slot_id"],
                "message": "The assigned slot still uses a schematic; geographic layout review is required."}
    point = gis.metric(slot["geometry"]).representative_point()
    lon, lat = gis.TO_MAP.transform(point.x, point.y)
    access = layout.get("access_points", {}).get(slot["parent_boundary_id"])
    # Without observed approach evidence, request network snapping near the slot
    # and expose its actual returned endpoint. Never invent the final connector.
    return {"assigned": True, "navigable": True, "slot_id": slot["slot_id"],
            "zone_id": "NN_F_013", "parent_boundary_id": slot["parent_boundary_id"],
            "slot_point": [lon, lat], "requested_access_point": [access["longitude"], access["latitude"]] if access else [lon, lat],
            "approach_observed": bool(access and access.get("observed")),
            "approach_note": access.get("note", "") if access else "No observed pedestrian approach point has been recorded.",
            "final_approach": "APPROXIMATE_NOT_VERIFIED", "proximity_threshold_m": 40,
            "warning": "Provisional demonstration slot location — not a verified on-ground vending position."}


def walking_route(origin, target, *, identity, client_factory=httpx.Client):
    if not target.get("navigable"):
        return {"available": False, "reason": "No geographic assignment is available", "destination": target}
    if len(origin) != 2 or any(not math.isfinite(v) for v in origin) or not -180 <= origin[0] <= 180 or not -90 <= origin[1] <= 90:
        raise OperationalValidationError("Location must be finite WGS84 longitude, latitude")
    key = os.getenv("ORS_API_KEY", "").strip()
    base = os.getenv("ORS_BASE_URL", "https://api.openrouteservice.org").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        return {"available": False, "reason": "Routing configuration requires HTTPS or a localhost service"}
    if not key and parsed.hostname == "api.openrouteservice.org":
        return {"available": False, "reason": "Walking routing is not configured. You can still inspect your slot on this map."}
    with _lock:
        now = time.monotonic()
        if now - _requests.get(identity, -100) < 10:
            return {"available": False, "reason": "Please wait ten seconds before requesting another route."}
        if len(_requests) > 1000:
            _requests.clear()
        _requests[identity] = now
    try:
        with client_factory(timeout=15, follow_redirects=False) as client:
            response = client.post(f"{base}/v2/directions/foot-walking/geojson",
                headers={"Authorization": key, "Content-Type": "application/json"},
                json={"coordinates": [origin, target["requested_access_point"]], "instructions": True,
                      "units": "m", "radiuses": [50, 30]})
            response.raise_for_status()
            payload = response.json()
        feature = payload["features"][0]
        coordinates = feature["geometry"]["coordinates"]
        if feature["geometry"]["type"] != "LineString" or len(coordinates) < 2 or any(
                len(p) < 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p[:2])
                or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in coordinates):
            raise ValueError("Invalid route geometry")
        endpoint = coordinates[-1][:2]
        point = gis.metric(mapping(Point(*endpoint)))
        requested = gis.metric(mapping(Point(*target["requested_access_point"])))
        if point.distance(requested) > 35:
            raise ValueError("Routing endpoint is too far from the requested access point")
        summary = feature.get("properties", {}).get("summary", {})
        distance, duration = summary.get("distance"), summary.get("duration")
        for value in (distance, duration):
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("Invalid provider summary")
        steps = [step for segment in feature.get("properties", {}).get("segments", []) for step in segment.get("steps", [])]
        return {"available": True, "provider": "openrouteservice", "profile": "foot-walking",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "distance_m": distance, "duration_s": duration, "instructions": steps,
                "access_endpoint": endpoint, "final_approach": "APPROXIMATE_NOT_VERIFIED",
                "attribution": "© openrouteservice by HeiGIT | Data © OpenStreetMap contributors",
                "warning": "Route follows the provider's pedestrian network. Crossings, access and the final approach require site verification; no final straight-line route is shown."}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return {"available": False, "reason": "Walking routing is unavailable or no reliable nearby endpoint was returned. Inspect your slot on this map; no route has been estimated."}
