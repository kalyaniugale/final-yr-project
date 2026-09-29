import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.api as api
from backend.database import connect, initialize_database


class VendorPortalFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "portal.db"
        initialize_database(self.database_path)
        self.patch = patch.object(api, "DATABASE_PATH", self.database_path)
        self.patch.start()
        self.auth_patch = patch.object(api, "AUTH_TEST_BYPASS", True)
        self.auth_patch.start()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        self.auth_patch.stop()
        self.patch.stop()
        self.temp_directory.cleanup()

    def test_new_vendor_recommend_request_status_and_cancel_flow(self):
        registered = self.client.post("/api/vendors", json={
            "business_category": "food",
            "preferred_division": "Nashik West",
            "priority_profile": "ACCESSIBILITY",
            "transport_preference": True,
            "parking_preference": False,
            "market_preference": False,
            "preferred_language": "mr",
        })
        self.assertEqual(registered.status_code, 201, registered.text)
        vendor = registered.json()
        active = self.client.get(f"/api/vendors/{vendor['vendor_id']}/active-allocation")
        self.assertIsNone(active.json()["allocation"])
        recommendations = self.client.post("/api/recommendations", json={
            "vendor_id": vendor["vendor_id"], "top_n": 3,
        })
        self.assertEqual(recommendations.status_code, 200, recommendations.text)
        zone_id = recommendations.json()["recommendations"][0]["zone_id"]
        created = self.client.post("/api/allocation-requests", json={
            "vendor_id": vendor["vendor_id"],
            "zone_id": zone_id,
            "request_type": "NEW_ALLOCATION",
            "business_category": vendor["business_category"],
            "preferred_division": vendor["preferred_division"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        request = created.json()
        self.assertEqual(request["status"], "PENDING")
        fetched = self.client.get(f"/api/allocation-requests/{request['request_id']}")
        self.assertEqual(fetched.json()["status"], "PENDING")
        cancelled = self.client.post(
            f"/api/allocation-requests/{request['request_id']}/cancel"
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

    def test_existing_profile_personalization_and_full_zone_refresh_flow(self):
        profile = self.client.get("/api/vendors/V2024_00001")
        self.assertEqual(profile.status_code, 200)
        updated = self.client.patch("/api/vendors/V2024_00001", json={
            "priority_profile": "COMMERCIAL", "market_preference": True,
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        commercial = self.client.post("/api/recommendations", json={
            "vendor_id": "V2024_00001", "business": "food",
            "division": "Nashik West", "top_n": 3,
        })
        self.assertEqual(commercial.status_code, 200, commercial.text)
        commercial_body = commercial.json()

        access_vendor = self.client.post("/api/vendors", json={
            "business_category": "food", "preferred_division": "Nashik West",
            "priority_profile": "ACCESSIBILITY", "transport_preference": True,
            "preferred_language": "en",
        }).json()
        access = self.client.post("/api/recommendations", json={
            "vendor_id": access_vendor["vendor_id"], "top_n": 3,
        }).json()
        self.assertNotEqual(
            commercial_body["effective_factor_weights"], access["effective_factor_weights"]
        )

        full_zone = commercial_body["recommendations"][0]["zone_id"]
        with closing(connect(self.database_path)) as connection:
            cap = connection.execute(
                "SELECT official_capacity FROM zone_live_status WHERE zone_id = ?", (full_zone,)
            ).fetchone()[0]
            connection.execute(
                """UPDATE zone_live_status SET current_vendor_count = ?,
                   available_capacity = 0, status = 'FULL' WHERE zone_id = ?""",
                (cap, full_zone),
            )
            connection.commit()
        refreshed = self.client.post("/api/recommendations", json={
            "vendor_id": "V2024_00001", "business": "food",
            "division": "Nashik West", "top_n": 3,
        })
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotIn(
            full_zone,
            [zone["zone_id"] for zone in refreshed.json()["recommendations"]],
        )


if __name__ == "__main__":
    unittest.main()
