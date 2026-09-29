import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import backend.api as api
from backend.database import connect, initialize_database, utc_now
from backend.mcda_engine import DATA, WEIGHTS, recommend


class LiveRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "operational" / "test.db"
        initialize_database(self.database_path)
        self.database_patch = patch.object(api, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        self.auth_patch = patch.object(api, "AUTH_TEST_BYPASS", True)
        self.auth_patch.start()
        self.client = TestClient(api.app)
        candidates = pd.read_csv(DATA / "candidate_zone_snapshot.csv", dtype={"zone_id": str})
        candidates = candidates.loc[
            candidates.zone_type.eq("FREE")
            & candidates.geometry_usable_for_reference_model.astype(str)
            .str.lower()
            .isin(["true", "1", "yes"])
        ].copy()
        self.candidates = candidates.sort_values("zone_id").reset_index(drop=True)
        self.assertGreaterEqual(len(self.candidates), 4)

    def tearDown(self):
        self.client.close()
        self.auth_patch.stop()
        self.database_patch.stop()
        self.temp_directory.cleanup()

    def close_all_candidates(self):
        ids = self.candidates.zone_id.tolist()
        placeholders = ",".join("?" for _ in ids)
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                f"UPDATE zone_live_status SET status = 'CLOSED' WHERE zone_id IN ({placeholders})",
                ids,
            )
            connection.commit()

    def set_live(self, zone_id, status="OPEN", capacity=None, count=0):
        with closing(connect(self.database_path)) as connection:
            if capacity is None:
                connection.execute(
                    """UPDATE zone_live_status
                       SET official_capacity = NULL, current_vendor_count = ?,
                           available_capacity = NULL, status = ?
                       WHERE zone_id = ?""",
                    (count, status, zone_id),
                )
            else:
                connection.execute(
                    """UPDATE zone_live_status
                       SET official_capacity = ?, current_vendor_count = ?,
                           available_capacity = ?, status = ?
                       WHERE zone_id = ?""",
                    (capacity, count, capacity - count, status, zone_id),
                )
            connection.commit()

    def live_recommend(self, **kwargs):
        return recommend(
            kwargs.pop("business", "food"),
            top_n=kwargs.pop("top_n", 20),
            use_live_status=True,
            database_path=self.database_path,
            **kwargs,
        )

    def test_live_status_and_capacity_eligibility_rules(self):
        zone_id = self.candidates.iloc[0].zone_id
        for status in ("FULL", "CLOSED", "SUSPENDED", "RESTRICTED", "NO_VENDING"):
            with self.subTest(status=status):
                self.close_all_candidates()
                self.set_live(zone_id, status=status, capacity=5, count=0)
                self.assertTrue(self.live_recommend().empty)

        self.close_all_candidates()
        self.set_live(zone_id, status="OPEN", capacity=5, count=1)
        eligible = self.live_recommend()
        self.assertEqual(eligible.zone_id.tolist(), [zone_id])
        self.assertEqual(eligible.iloc[0].live_status, "OPEN")
        self.assertEqual(eligible.iloc[0].current_vendor_count, 1)
        self.assertEqual(eligible.iloc[0].available_capacity, 4)

        self.close_all_candidates()
        self.set_live(zone_id, status="OPEN", capacity=None)
        unknown_capacity = self.live_recommend()
        self.assertEqual(unknown_capacity.zone_id.tolist(), [zone_id])
        self.assertTrue(pd.isna(unknown_capacity.iloc[0].available_capacity))

    def test_missing_live_row_is_conservatively_excluded(self):
        zone_id = self.candidates.iloc[0].zone_id
        self.close_all_candidates()
        with closing(connect(self.database_path)) as connection:
            connection.execute("DELETE FROM zone_live_status WHERE zone_id = ?", (zone_id,))
            connection.commit()
        self.assertTrue(self.live_recommend().empty)

    def test_final_slot_approval_removes_zone_from_next_api_result(self):
        zone_id = self.candidates.iloc[0].zone_id
        self.close_all_candidates()
        self.set_live(zone_id, status="OPEN", capacity=1, count=0)
        before = self.client.post(
            "/api/recommendations", json={"business": "food", "top_n": 3}
        )
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual([item["zone_id"] for item in before.json()["recommendations"]], [zone_id])
        self.assertTrue(before.json()["live_filter_applied"])
        self.assertIn("current_vendor_count", before.json()["recommendations"][0])
        self.assertIn("available_capacity", before.json()["recommendations"][0])

        request = self.client.post(
            "/api/allocation-requests",
            json={
                "vendor_id": "V2024_00201",
                "zone_id": zone_id,
                "request_type": "NEW_ALLOCATION",
                "business_category": "food",
            },
        ).json()
        approved = self.client.post(
            f"/api/allocation-requests/{request['request_id']}/approve",
            json={"approved_by": "admin_live"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        after = self.client.post(
            "/api/recommendations", json={"business": "food", "top_n": 3}
        )
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json()["recommendations"], [])
        self.assertEqual(after.json()["candidate_count_after_live_filter"], 0)

    def test_relocation_reopens_old_free_zone_for_recommendations(self):
        old_zone = self.candidates.iloc[0].zone_id
        new_zone = self.candidates.iloc[1].zone_id
        vendor_id = "V2024_00202"
        self.close_all_candidates()
        self.set_live(old_zone, status="FULL", capacity=1, count=1)
        self.set_live(new_zone, status="OPEN", capacity=10, count=0)
        now = utc_now()
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """INSERT INTO allocations
                   (allocation_id, vendor_id, zone_id, status, allocated_at,
                    approved_by, created_at, updated_at)
                   VALUES ('ALLOC_LIVE_OLD', ?, ?, 'ACTIVE', ?, 'admin_seed', ?, ?)""",
                (vendor_id, old_zone, now, now, now),
            )
            connection.commit()
        before_ids = set(self.live_recommend().zone_id)
        self.assertNotIn(old_zone, before_ids)

        request = self.client.post(
            "/api/allocation-requests",
            json={
                "vendor_id": vendor_id,
                "zone_id": new_zone,
                "request_type": "RELOCATION",
                "business_category": "food",
            },
        ).json()
        approved = self.client.post(
            f"/api/allocation-requests/{request['request_id']}/approve",
            json={"approved_by": "admin_live"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        after_ids = set(self.live_recommend().zone_id)
        self.assertIn(old_zone, after_ids)

    def test_exclusion_existing_vendor_and_preferred_division_fallback(self):
        zone = self.candidates.iloc[0]
        self.close_all_candidates()
        self.set_live(zone.zone_id, status="OPEN", capacity=10, count=0)
        excluded = self.live_recommend(exclude_zone=zone.zone_id)
        self.assertTrue(excluded.empty)

        existing = self.live_recommend(business="", vendor_id="V2024_00001")
        self.assertEqual(existing.zone_id.tolist(), [zone.zone_id])

        other_divisions = [
            division
            for division in self.candidates.zone_division.dropna().unique()
            if division != zone.zone_division and division != "Citywide"
        ]
        self.assertTrue(other_divisions)
        fallback = self.live_recommend(division=other_divisions[0])
        self.assertEqual(fallback.zone_id.tolist(), [zone.zone_id])
        self.assertTrue(bool(fallback.iloc[0].fallback_used))

    def test_surviving_zone_scores_and_weights_are_unchanged(self):
        self.assertEqual(
            WEIGHTS,
            {"business": .25, "commercial": .20, "access": .20,
             "facilities": .15, "preference": .10, "historical": .10},
        )
        static = recommend("food", top_n=1)
        zone_id = static.iloc[0].zone_id
        self.close_all_candidates()
        self.set_live(zone_id, status="OPEN", capacity=10, count=0)
        live = self.live_recommend(top_n=1)
        self.assertEqual(live.iloc[0].zone_id, zone_id)
        for field in ["score"] + [f"{name}_score" for name in WEIGHTS]:
            self.assertAlmostEqual(float(live.iloc[0][field]), float(static.iloc[0][field]), places=12)
        self.assertGreater(live.attrs["candidate_count_before_live_filter"], 1)
        self.assertEqual(live.attrs["candidate_count_after_live_filter"], 1)
        self.assertTrue(live.attrs["live_filter_applied"])


if __name__ == "__main__":
    unittest.main()
