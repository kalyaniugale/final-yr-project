import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from shapely.geometry import shape

import backend.api as api
import database as db

pilot = api.pilot_slots


class PilotGeometryTests(unittest.TestCase):
    def test_official_association_and_shared_unverified_geometry(self):
        evidence = pilot.pilot_evidence()
        records = {r["zone_id"]: r for r in evidence["official_records"]}
        self.assertEqual(records["NN_F_013"]["capacity"], "10")
        self.assertEqual(records["NN_F_013"]["zone_type"], "FREE")
        self.assertEqual(records["NN_F_013"]["division"], "New Nashik")
        self.assertEqual(records["NV_064"]["zone_type"], "NO_VENDING")
        self.assertEqual(records["NV_069"]["zone_type"], "NO_VENDING")
        geometries = evidence["analytical_references"]
        self.assertEqual(len(geometries), 3)
        self.assertTrue(all(f["geometry"] == geometries[0]["geometry"] for f in geometries))
        self.assertTrue(all(not f["properties"]["official_boundary_verified"] for f in geometries))
        self.assertIsNone(evidence["verified_boundary"])
        self.assertEqual(evidence["spatial_match"], "UNVERIFIED")
        self.assertTrue(all(not p["inside_analytical_reference"] for p in evidence["survey_points"]))
        self.assertAlmostEqual(evidence["survey_points"][0]["distance_to_reference_m"], 275.7, places=1)

    def test_ten_numbered_valid_non_overlapping_metric_rectangles(self):
        layout = pilot.generate_layout()
        self.assertFalse(layout["georeferenced"])
        self.assertEqual(layout["length_m"], 24.5)
        self.assertEqual([s["slot_id"] for s in layout["slots"]], [f"S{i:03d}" for i in range(1, 11)])
        geometries = [shape(s["schematic_geometry"]) for s in layout["slots"]]
        for index, geometry in enumerate(geometries):
            self.assertTrue(geometry.is_valid)
            self.assertEqual(geometry.area, 4)
            self.assertEqual(geometry.bounds[1], 1.2)
            self.assertEqual(layout["slots"][index]["zone_id"], "NN_F_013")
            for other in geometries[index + 1:]:
                self.assertFalse(geometry.intersects(other))

    def test_configurable_dimensions_and_capacity(self):
        layout = pilot.generate_layout(width=3, depth=1.5, spacing=.8, clearance=2, count=4, capacity=4)
        self.assertEqual(len(layout["slots"]), 4)
        self.assertEqual(shape(layout["slots"][0]["schematic_geometry"]).area, 4.5)
        self.assertEqual(layout["slots"][1]["x_m"], 3.8)

    def test_invalid_configuration_rejected(self):
        for options in ({"count": 60}, {"count": 11}, {"count": 3, "capacity": 2},
                        {"count": 0}, {"count": 1.5}, {"width": 0}, {"depth": -1},
                        {"spacing": -.5}, {"clearance": 0}, {"width": float("nan")},
                        {"depth": float("inf")}, {"count": True}):
            with self.subTest(options=options), self.assertRaises(db.OperationalValidationError):
                pilot.generate_layout(**options)

    def test_missing_reference_geometry_preserves_honest_schematic(self):
        with patch.object(pilot.Path, "exists", return_value=False):
            evidence = pilot.pilot_evidence()
        self.assertEqual(evidence["analytical_references"], [])
        self.assertIsNone(evidence["verified_boundary"])
        self.assertEqual(len(evidence["survey_points"]), 3)
        self.assertFalse(pilot.generate_layout()["georeferenced"])


class PilotApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "pilot.db"
        db.initialize_database(self.path)
        self.db_patch = patch.object(api, "DATABASE_PATH", self.path)
        self.db_patch.start()
        self.bypass_patch = patch.object(api, "AUTH_TEST_BYPASS", False)
        self.bypass_patch.start()
        self.session = {"role": "ADMIN", "admin_id": "test-officer", "vendor_id": None}
        self.auth_patch = patch.object(api, "get_session", side_effect=lambda *a, **kw: self.session)
        self.auth_patch.start()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        self.auth_patch.stop()
        self.bypass_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def initialize(self):
        response = self.client.post("/api/pilot/initialize")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve(self, vendor="V_PILOT_1", zone="NN_F_013"):
        request = db.create_allocation_request(vendor, zone, "NEW_ALLOCATION", database_path=self.path)
        db.approve_allocation_request(request["request_id"], "test-officer", database_path=self.path)

    def update(self, slot="S001", status="RESERVED", vendor=None, timestamp=None):
        if timestamp is None:
            timestamp = self.client.get(f"/api/pilot/slots/{slot}").json()["updated_at"]
        return self.client.patch(f"/api/pilot/slots/{slot}", json={"status": status,
            "assigned_vendor_id": vendor, "expected_updated_at": timestamp})

    def snapshot(self):
        with closing(db.connect(self.path)) as connection:
            return {table: [tuple(r) for r in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
                    for table in ("zone_live_status", "allocation_requests", "allocations", "admin_audit_log")}

    def test_initialization_is_idempotent_preserves_changes_and_operational_data(self):
        before = self.snapshot()
        layout = self.initialize()
        self.assertEqual(len(layout["slots"]), 10)
        self.assertEqual(self.update(status="BLOCKED").status_code, 200)
        self.assertEqual(self.initialize()["slots"][0]["status"], "BLOCKED")
        self.assertEqual(self.snapshot(), before)

    def test_all_status_changes_and_audit(self):
        self.initialize()
        for status in pilot.STATUSES:
            response = self.update(status=status)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], status)
        with closing(db.connect(self.path)) as connection:
            events = connection.execute("SELECT * FROM pilot_slot_events").fetchall()
        self.assertEqual(len(events), 4)
        self.assertTrue(all(r["actor"] == "test-officer" for r in events))

    def test_assignment_requires_approved_current_zone_allocation(self):
        self.initialize()
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 422)
        request = db.create_allocation_request("V_PILOT_1", "NN_F_013", "NEW_ALLOCATION", database_path=self.path)
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 422)
        db.approve_allocation_request(request["request_id"], "test-officer", database_path=self.path)
        before = self.snapshot()
        response = self.update(vendor="V_PILOT_1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_zone_allocation_and_unapproved_active_allocation_rejected(self):
        self.initialize()
        self.approve(zone="NN_F_001")
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 422)
        with db.transaction(self.path) as connection:
            connection.execute("UPDATE allocations SET zone_id = 'NN_F_013', request_id = NULL")
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 422)

    def test_unique_vendor_and_release_without_changing_operational_allocation(self):
        self.initialize()
        self.approve()
        before = self.snapshot()
        self.assertEqual(self.update(vendor="V_PILOT_1", status="OCCUPIED").status_code, 200)
        self.assertEqual(self.update(slot="S002", vendor="V_PILOT_1").status_code, 409)
        self.assertEqual(self.update(status="AVAILABLE").status_code, 200)
        self.assertEqual(self.update(slot="S002", vendor="V_PILOT_1").status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_replacing_vendor_requires_release(self):
        self.initialize()
        self.approve()
        self.approve("V_PILOT_2")
        self.assertEqual(self.update(vendor="V_PILOT_1").status_code, 200)
        self.assertEqual(self.update(vendor="V_PILOT_2").status_code, 409)

    def test_invalid_status_assignment_unknown_slot_and_required_version(self):
        self.initialize()
        self.assertEqual(self.update(status="INVALID").status_code, 422)
        self.assertEqual(self.update(status="BLOCKED", vendor="V_PILOT_1").status_code, 422)
        self.assertEqual(self.update(vendor=" ").status_code, 422)
        self.assertEqual(self.client.get("/api/pilot/slots/S999").status_code, 404)
        self.assertEqual(self.update(slot="S999", timestamp="unknown").status_code, 404)
        self.assertEqual(self.client.patch("/api/pilot/slots/S001", json={"status": "AVAILABLE"}).status_code, 422)

    def test_stale_update_conflict(self):
        layout = self.initialize()
        old_version = layout["slots"][0]["updated_at"]
        self.assertEqual(self.update(status="BLOCKED", timestamp=old_version).status_code, 200)
        self.assertEqual(self.update(status="AVAILABLE", timestamp=old_version).status_code, 409)
        self.assertEqual(self.client.get("/api/pilot/slots/S001").json()["status"], "BLOCKED")

    def test_concurrent_vendor_assignment_only_one_succeeds(self):
        layout = self.initialize()
        self.approve()
        def assign(slot):
            try:
                pilot.update_slot(slot["slot_id"], "RESERVED", "V_PILOT_1", actor="officer",
                                  expected_updated_at=slot["updated_at"], database_path=self.path)
                return "OK"
            except db.OperationalConflictError:
                return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(assign, layout["slots"][:2]))
        self.assertCountEqual(results, ["OK", "CONFLICT"])

    def test_unauthenticated_and_vendor_write_permissions(self):
        self.session = None
        self.assertEqual(self.client.get("/api/pilot/layout").status_code, 401)
        self.assertEqual(self.client.post("/api/pilot/initialize").status_code, 401)
        self.assertEqual(self.update(timestamp="unknown").status_code, 401)
        self.session = {"role": "VENDOR", "vendor_id": "V_PILOT_1"}
        self.assertEqual(self.client.post("/api/pilot/initialize").status_code, 403)
        self.assertEqual(self.update(timestamp="unknown").status_code, 403)
        self.assertEqual(self.client.get("/api/pilot/layout").status_code, 403)
        self.session = {"role": "NEW_VENDOR_ONBOARDING"}
        self.assertEqual(self.client.get("/api/pilot/layout").status_code, 403)

    def test_vendor_empty_state_privacy_highlight_and_revoked_allocation(self):
        self.initialize()
        self.approve()
        self.approve("V_PILOT_2")
        self.assertEqual(self.update(vendor="V_PILOT_2").status_code, 200)
        self.session = {"role": "VENDOR", "vendor_id": "V_PILOT_1"}
        layout = self.client.get("/api/pilot/layout").json()
        self.assertIsNone(layout["my_slot_id"])
        self.assertNotIn("V_PILOT_2", json.dumps(layout))
        self.assertIsNone(self.client.get("/api/pilot/slots/S001").json()["assigned_vendor_id"])
        self.session = {"role": "ADMIN", "admin_id": "test-officer"}
        self.assertEqual(self.update(slot="S002", vendor="V_PILOT_1").status_code, 200)
        self.session = {"role": "VENDOR", "vendor_id": "V_PILOT_1"}
        self.assertEqual(self.client.get("/api/pilot/layout").json()["my_slot_id"], "S002")
        with db.transaction(self.path) as connection:
            connection.execute("UPDATE allocations SET status = 'RELEASED' WHERE vendor_id = 'V_PILOT_1'")
        self.assertEqual(self.client.get("/api/pilot/layout").status_code, 403)

    def test_not_initialized_layout_is_explicit(self):
        self.assertEqual(self.client.get("/api/pilot/layout").status_code, 404)
