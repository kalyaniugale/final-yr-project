"""Real supplied boundary validation; synthetic shapes are test fixtures only."""
import copy
import json
import math
import os
import unittest
from unittest.mock import patch

import httpx
from shapely import affinity
from shapely.geometry import box, mapping

import test_pilot_slots as support

pilot, db, api = support.pilot, support.db, support.api

gis = pilot.gis
nav = api.pilot_navigation


class GeographicGeometryTests(unittest.TestCase):
    def test_uploaded_coordinates_and_ten_contained_metric_slots(self):
        boundaries = gis.load_boundaries()
        self.assertEqual([f["properties"]["boundary_id"] for f in boundaries["features"]], ["2974", "3577"])
        self.assertEqual(boundaries["features"][0]["geometry"]["coordinates"][0][0], [73.771665, 19.974794])
        self.assertEqual(boundaries["features"][1]["geometry"]["coordinates"][0][0], [73.771552, 19.974675])
        layout = gis.generate_geographic()
        self.assertEqual(layout["validation"]["counts"], {"Boundary A": 5, "Boundary B": 5})
        self.assertEqual(len(layout["slots"]), 10)
        self.assertEqual(len({s["slot_id"] for s in layout["slots"]}), 10)
        for slot in layout["slots"]:
            polygon = gis.metric(slot["geometry"])
            self.assertAlmostEqual(polygon.area, 4, places=5)
            points = list(polygon.exterior.coords)
            for a, b in zip(points, points[1:]):
                self.assertAlmostEqual(math.dist(a, b), 2, places=5)
            parent = next(f for f in boundaries["features"] if f["properties"]["boundary_id"] == slot["parent_boundary_id"])
            self.assertTrue(gis.metric(parent["geometry"]).covers(polygon))
        self.assertTrue(gis.validate_layout(layout)["valid"])

    def fixture_boundaries(self, narrow=False, irregular=False):
        # Explicit synthetic test geometry near Nashik, never persisted as source.
        x, y = gis.TO_METRIC.transform(73.772, 19.974)
        features = []
        for i, identifier in enumerate(gis.IDS):
            p = box(x, y + i * 20, x + 30, y + i * 20 + (3 if narrow else 6))
            if irregular:
                p = p.difference(box(x + 10, y + i * 20, x + 12, y + i * 20 + 2))
            p = affinity.rotate(p, 32, origin=(x, y))
            features.append({"type": "Feature", "properties": {"boundary_id": identifier, "name": gis.IDS[identifier]}, "geometry": gis.geographic(p)})
        return {"type": "FeatureCollection", "features": features, "source_sha256": "SYNTHETIC_TEST_ONLY"}

    def test_rotated_irregular_and_too_narrow_boundaries(self):
        for irregular in (False, True):
            b = self.fixture_boundaries(irregular=irregular)
            layout = gis.generate_geographic(boundaries=b)
            self.assertTrue(gis.validate_layout(layout, b)["valid"])
            self.assertGreater(len(layout["slots"]), 0)
            self.assertAlmostEqual(layout["corridors"][0]["angle"], 32, places=4)
        layout = gis.generate_geographic(boundaries=self.fixture_boundaries(narrow=True))
        self.assertEqual(len(layout["slots"]), 0)
        self.assertEqual(len(layout["rejections"]), 2)

    def test_invalid_dimensions_overlap_spacing_clearance_and_capacity(self):
        original = gis.generate_geographic()
        cases = []
        outside = copy.deepcopy(original); outside["slots"][0]["geometry"] = gis.pose_geometry(73.78, 19.98, 0); cases.append(outside)
        overlap = copy.deepcopy(original); overlap["slots"][1]["geometry"] = overlap["slots"][0]["geometry"]; cases.append(overlap)
        dimensions = copy.deepcopy(original); dimensions["slots"][0]["geometry"] = gis.geographic(affinity.scale(gis.metric(dimensions["slots"][0]["geometry"]), xfact=1.2)); cases.append(dimensions)
        no_corridor = copy.deepcopy(original); no_corridor["corridors"] = []; cases.append(no_corridor)
        clearance = copy.deepcopy(original); clearance["config"]["clearance_m"] = 2; cases.append(clearance)
        spacing = copy.deepcopy(original); spacing["config"]["spacing_m"] = .1; cases.append(spacing)
        capacity = copy.deepcopy(original); capacity["slots"].append(capacity["slots"][0]); cases.append(capacity)
        pedestrian = copy.deepcopy(original); pedestrian["slots"][0]["geometry"] = pedestrian["corridors"][0]["geometry"]; cases.append(pedestrian)
        for layout in cases:
            with self.assertRaises(db.OperationalValidationError):
                gis.validate_layout(layout)


class GeographicApiTests(unittest.TestCase):
    setUp = support.PilotApiTests.setUp
    tearDown = support.PilotApiTests.tearDown
    initialize = support.PilotApiTests.initialize
    approve = support.PilotApiTests.approve
    update = support.PilotApiTests.update
    snapshot = support.PilotApiTests.snapshot
    def geographic(self):
        self.initialize()
        preview = self.client.post("/api/pilot/preview", json={}).json()
        response = self.client.patch("/api/pilot/layout", json={"layout": preview, "review_confirmed": True})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def edit(self, layout):
        layout = copy.deepcopy(layout)
        layout["expected_revision"] = layout["revision"]
        layout["expected_versions"] = {s["slot_id"]: s["updated_at"] for s in layout["slots"]}
        return layout

    def test_save_reload_review_and_operational_isolation(self):
        before = self.snapshot()
        layout = self.geographic()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(layout["georeferenced"])
        self.assertEqual(self.initialize()["slots"], layout["slots"])
        proposal = self.edit(layout)
        self.assertEqual(self.client.patch("/api/pilot/layout", json={"layout": proposal}).status_code, 422)
        self.assertEqual(self.client.post("/api/pilot/validate", json={"layout": {}}).status_code, 422)

    def test_assigned_or_occupied_geometry_locked_and_stale_save(self):
        layout = self.geographic()
        proposal = self.edit(layout)
        self.approve()
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 200)
        self.assertEqual(self.client.patch("/api/pilot/layout", json={"layout": proposal, "review_confirmed": True}).status_code, 409)
        current = self.client.get("/api/pilot/layout").json()
        proposal = self.edit(current); proposal["slots"] = proposal["slots"][1:]
        self.assertEqual(self.client.patch("/api/pilot/layout", json={"layout": proposal, "review_confirmed": True}).status_code, 409)
        before = self.snapshot()
        same = self.edit(current)
        self.assertEqual(self.client.patch("/api/pilot/layout", json={"layout": same, "review_confirmed": True}).status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_delete_is_persistent_and_does_not_reseed(self):
        layout = self.geographic()
        proposal = self.edit(layout); proposal["slots"] = proposal["slots"][1:]
        response = self.client.patch("/api/pilot/layout", json={"layout": proposal, "review_confirmed": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.initialize()["slots"]), 9)
        self.assertEqual(self.client.get("/api/pilot/slots/S001").status_code, 404)

    def test_metric_move_persists_without_resizing(self):
        proposal = self.edit(self.geographic())
        slot = proposal["slots"][-1]
        point = gis.metric(slot["geometry"]).centroid
        corridor = next(c for c in proposal["corridors"] if c["boundary_id"] == slot["parent_boundary_id"])
        direction = math.radians(corridor["angle"])
        lon, lat = gis.TO_MAP.transform(point.x + 10 * math.cos(direction), point.y + 10 * math.sin(direction))
        response = self.client.post("/api/pilot/validate", json={"layout": proposal,
            "poses": {slot["slot_id"]: {"longitude": lon, "latitude": lat, "angle": slot["pose"]["angle"]}}})
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.patch("/api/pilot/layout", json={"layout": response.json(), "review_confirmed": True})
        self.assertEqual(saved.status_code, 200, saved.text)
        moved = self.client.get("/api/pilot/slots/S010").json()
        self.assertAlmostEqual(gis.metric(moved["geometry"]).centroid.distance(point), 10, places=4)
        self.assertAlmostEqual(gis.metric(moved["geometry"]).area, 4, places=5)

    def test_pose_rotation_validation_and_obstruction(self):
        proposal = self.edit(self.geographic())
        slot = proposal["slots"][0]
        bad_pose = {**slot["pose"], "longitude": 73.78}
        self.assertEqual(self.client.post("/api/pilot/validate", json={"layout": proposal, "poses": {"S001": bad_pose}}).status_code, 422)
        same_pose = {**slot["pose"], "angle": slot["pose"]["angle"] + 90}
        response = self.client.post("/api/pilot/validate", json={"layout": proposal, "poses": {"S001": same_pose}})
        self.assertEqual(response.status_code, 200, response.text)
        proposal["obstruction_request"] = {"longitude": slot["pose"]["longitude"], "latitude": slot["pose"]["latitude"], "radius_m": .5, "note": "Observed pole"}
        observed = self.client.post("/api/pilot/validate", json={"layout": proposal})
        self.assertEqual(observed.status_code, 200)
        self.assertFalse(observed.json()["validation"]["valid"])
        self.assertEqual(self.client.patch("/api/pilot/layout", json={"layout": observed.json(), "review_confirmed": True}).status_code, 422)
        regenerated = self.client.post("/api/pilot/preview", json={"obstructions": observed.json()["obstructions"]})
        self.assertEqual(regenerated.status_code, 200, regenerated.text)
        self.assertTrue(regenerated.json()["validation"]["valid"])

    def test_vendor_destination_privacy_empty_and_permissions(self):
        self.geographic(); self.approve(); self.approve("V_PILOT_2")
        self.assertEqual(self.update(vendor="V_PILOT_2").status_code, 200)
        self.session = {"role": "VENDOR", "vendor_id": "V_PILOT_1"}
        empty = self.client.get("/api/pilot/navigation").json()
        self.assertFalse(empty["assigned"])
        self.assertEqual(empty["message"], "No vending slot has been assigned yet.")
        self.assertNotIn("V_PILOT_2", self.client.get("/api/pilot/layout").text)
        for route, method, body in (("/api/pilot/preview", "post", {}), ("/api/pilot/validate", "post", {"layout": {}}), ("/api/pilot/layout", "patch", {"layout": {}})):
            self.assertEqual(getattr(self.client, method)(route, json=body).status_code, 403)
        self.session = {"role": "VENDOR", "vendor_id": "V_PILOT_2"}
        target = self.client.get("/api/pilot/navigation").json()
        self.assertEqual(target["slot_id"], "S001")
        self.assertTrue(target["navigable"])
        self.assertEqual(target["final_approach"], "APPROXIMATE_NOT_VERIFIED")
        with patch.dict(os.environ, {"ORS_API_KEY": ""}):
            response = self.client.post("/api/pilot/route", json={"longitude": 73.772, "latitude": 19.974})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])

    def test_new_assignment_requires_available_slot(self):
        self.geographic(); self.approve()
        for status in ("BLOCKED", "RESERVED", "OCCUPIED"):
            self.assertEqual(self.update(status=status).status_code, 200)
            self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 409)
        self.assertEqual(self.update(status="AVAILABLE").status_code, 200)
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 200)


class WalkingProviderTests(unittest.TestCase):
    def target(self):
        return {"navigable": True, "requested_access_point": [73.77349, 19.97319]}

    def test_actual_walking_geojson_is_preserved_and_summary_not_invented(self):
        coordinates = [[73.7734, 19.9731], [73.77345, 19.97315], [73.77349, 19.97319]]
        def handler(request):
            self.assertIn("/foot-walking/geojson", str(request.url))
            self.assertEqual(json.loads(request.content)["coordinates"][-1], self.target()["requested_access_point"])
            return httpx.Response(200, json={"features": [{"geometry": {"type": "LineString", "coordinates": coordinates}, "properties": {"summary": {"distance": 123, "duration": 95}, "segments": [{"steps": [{"instruction": "Continue on the footway"}]}]}}]})
        nav._requests.clear()
        with patch.dict(os.environ, {"ORS_API_KEY": "test-only-key", "ORS_BASE_URL": "https://api.openrouteservice.org"}):
            result = nav.walking_route([73.7734, 19.9731], self.target(), identity="TEST", client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw))
        self.assertTrue(result["available"])
        self.assertEqual(result["geometry"]["coordinates"], coordinates)
        self.assertEqual(result["distance_m"], 123)
        self.assertEqual(result["duration_s"], 95)
        self.assertNotIn("test-only-key", json.dumps(result))

    def test_routing_failure_has_map_only_fallback(self):
        nav._requests.clear()
        with patch.dict(os.environ, {"ORS_API_KEY": "test-only-key"}):
            result = nav.walking_route([73.7734, 19.9731], self.target(), identity="TEST_FAIL", client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kw))
        self.assertFalse(result["available"])
        self.assertNotIn("geometry", result)
        self.assertNotIn("distance_m", result)
