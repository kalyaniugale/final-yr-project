import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.database import connect, create_operational_vendor, initialize_database


class ApplicationVendorIdTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "vendor.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temp_directory.cleanup()

    @staticmethod
    def profile():
        return {"business_category": "food", "preferred_language": "en"}

    def test_new_vendor_ids_are_readable_unique_and_concurrency_safe(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            rows = list(executor.map(
                lambda _: dict(create_operational_vendor(self.profile(), self.database_path)),
                range(8),
            ))
        public_ids = [row["application_vendor_id"] for row in rows]
        self.assertEqual(len(public_ids), len(set(public_ids)))
        self.assertTrue(all(re.fullmatch(r"NV-\d{4}-\d{6}", value) for value in public_ids))
        self.assertTrue(all(row["vendor_id"].startswith("NV_") for row in rows))

    def test_existing_new_vendor_is_backfilled_once_and_historical_overlay_is_not(self):
        new_vendor = dict(create_operational_vendor(self.profile(), self.database_path))
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE operational_vendors SET application_vendor_id = NULL, created_at = ? WHERE vendor_id = ?",
                ("2024-05-01T10:00:00+00:00", new_vendor["vendor_id"]),
            )
            connection.execute(
                """INSERT INTO operational_vendors (
                       vendor_id, application_vendor_id, vendor_type, business_category,
                       preferred_division, preferred_locality, priority_profile,
                       parking_preference, transport_preference, market_preference,
                       preferred_language, status, created_at, updated_at
                   ) VALUES ('V2024_TEST', NULL, 'EXISTING_IMPORTED', 'food', NULL, NULL,
                             'BALANCED', 0, 0, 0, 'en', 'ACTIVE', ?, ?)""",
                ("2024-05-01T10:00:00+00:00", "2024-05-01T10:00:00+00:00"),
            )
            connection.commit()

        first = initialize_database(self.database_path)
        with closing(connect(self.database_path)) as connection:
            assigned = connection.execute(
                "SELECT application_vendor_id FROM operational_vendors WHERE vendor_id = ?",
                (new_vendor["vendor_id"],),
            ).fetchone()[0]
            historical = connection.execute(
                "SELECT application_vendor_id FROM operational_vendors WHERE vendor_id = 'V2024_TEST'"
            ).fetchone()[0]
        second = initialize_database(self.database_path)

        self.assertEqual(first["application_vendor_ids_backfilled"], 1)
        self.assertRegex(assigned, r"^NV-2024-\d{6}$")
        self.assertIsNone(historical)
        self.assertEqual(second["application_vendor_ids_backfilled"], 0)
        with closing(connect(self.database_path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT application_vendor_id FROM operational_vendors WHERE vendor_id = ?",
                (new_vendor["vendor_id"],),
            ).fetchone()[0], assigned)


if __name__ == "__main__":
    unittest.main()
