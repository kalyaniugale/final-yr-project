import csv
import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.api as api
import auth_service
from backend.database import connect, create_allocation_request, initialize_database


class AuthenticationTests(unittest.TestCase):
    OTP = "123456"

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.database_path = self.root / "auth.db"
        initialize_database(self.database_path)
        self.source_path = self.root / "vendors.csv"
        with self.source_path.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(
                target, fieldnames=["vendor_id", "phone_number", "alternate_phone"]
            )
            writer.writeheader()
            writer.writerows([
                {"vendor_id": "V2024_00001", "phone_number": "+91 98765 43210", "alternate_phone": ""},
                {"vendor_id": "V2024_00002", "phone_number": "9999999999", "alternate_phone": ""},
                {"vendor_id": "V2024_00003", "phone_number": "09999999999", "alternate_phone": ""},
                {"vendor_id": "V2024_00004", "phone_number": "invalid", "alternate_phone": ""},
                {"vendor_id": "V2024_00005", "phone_number": "", "alternate_phone": ""},
            ])
        self.env = patch.dict(os.environ, {
            "APP_ENV": "test",
            "AUTH_HMAC_SECRET": "test-secret-that-is-not-for-production",
            "SESSION_COOKIE_SECURE": "false",
            "OTP_PROVIDER": "development",
            "OTP_DEBUG": "false",
            "NMC_ADMIN_USERNAME": "officer_01",
            "NMC_ADMIN_PASSWORD": "correct-password",
        }, clear=False)
        self.env.start()
        self.database_patch = patch.object(api, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        self.auth_patch = patch.object(api, "AUTH_TEST_BYPASS", False)
        self.auth_patch.start()
        self.otp_patch = patch.object(auth_service, "generate_otp", return_value=self.OTP)
        self.otp_patch.start()
        self.seed_summary = auth_service.seed_historical_vendor_identities(
            self.database_path, self.source_path
        )
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        self.otp_patch.stop()
        self.auth_patch.stop()
        self.database_patch.stop()
        self.env.stop()
        self.temp_directory.cleanup()

    def request_otp(self, mobile="9876543210"):
        response = self.client.post("/api/auth/vendor/request-otp", json={"mobile": mobile})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("otp", response.json())
        return response.json()["challenge_id"]

    def test_development_otp_request_path_creates_challenge_without_returning_otp(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "OTP_DEBUG": "false"}):
            response = self.client.post(
                "/api/auth/vendor/request-otp", json={"mobile": "9888888888"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["next_step"], "VERIFY_OTP")
        self.assertNotIn("otp", response.json())
        with closing(connect(self.database_path)) as connection:
            challenge = connection.execute(
                "SELECT otp_hash FROM auth_otp_challenges WHERE challenge_id = ?",
                (response.json()["challenge_id"],),
            ).fetchone()
        self.assertIsNotNone(challenge)
        self.assertNotEqual(challenge["otp_hash"], self.OTP)

    def verify(self, challenge_id, otp=None):
        return self.client.post(
            "/api/auth/vendor/verify-otp",
            json={"challenge_id": challenge_id, "otp": otp or self.OTP},
        )

    def admin_login(self, password="correct-password"):
        return self.client.post(
            "/api/auth/admin/login",
            json={"username": "officer_01", "password": password},
        )

    def test_historical_seed_is_idempotent_private_and_skips_ambiguity(self):
        self.assertEqual(self.seed_summary["valid_rows"], 3)
        self.assertEqual(self.seed_summary["missing_rows"], 2)
        self.assertEqual(self.seed_summary["ambiguous_numbers"], 1)
        self.assertEqual(self.seed_summary["ambiguous_vendor_ids"], 2)
        self.assertEqual(self.seed_summary["inserted"], 1)
        second = auth_service.seed_historical_vendor_identities(self.database_path, self.source_path)
        self.assertEqual(second["inserted"], 0)
        with closing(connect(self.database_path)) as connection:
            identities = connection.execute("SELECT * FROM vendor_auth_identities").fetchall()
            serialized = " ".join(str(tuple(row)) for row in identities)
        self.assertEqual(len(identities), 1)
        self.assertNotIn("9876543210", serialized)
        self.assertNotIn("9999999999", serialized)

    def test_missing_private_historical_source_is_a_safe_noop(self):
        summary = auth_service.seed_historical_vendor_identities(
            self.database_path, self.root / "not-supplied.csv"
        )
        self.assertFalse(summary["source_available"])
        self.assertEqual(summary["inserted"], 0)
        self.assertEqual(summary["identity_rows"], 1)

    def test_existing_vendor_otp_login_me_logout_and_consumption(self):
        challenge = self.request_otp("+91-98765-43210")
        verified = self.verify(challenge)
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(verified.json()["role"], "VENDOR")
        self.assertEqual(verified.json()["vendor_id"], "V2024_00001")
        self.assertNotIn("mobile", verified.text.lower())
        reused = self.verify(challenge)
        self.assertEqual(reused.status_code, 401)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["vendor_profile"]["vendor_id"], "V2024_00001")
        logged_out = self.client.post("/api/auth/logout")
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_wrong_expired_and_max_attempt_otps_are_rejected(self):
        challenge = self.request_otp()
        wrong = self.verify(challenge, "000000")
        self.assertEqual(wrong.status_code, 401)
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT attempt_count, otp_hash FROM auth_otp_challenges WHERE challenge_id = ?",
                (challenge,),
            ).fetchone()
            self.assertEqual(row["attempt_count"], 1)
            self.assertNotEqual(row["otp_hash"], self.OTP)
            connection.execute(
                "UPDATE auth_otp_challenges SET expires_at = ? WHERE challenge_id = ?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), challenge),
            )
            connection.commit()
        self.assertEqual(self.verify(challenge).status_code, 401)

        # A separate client/database test path avoids the request cooldown.
        with closing(connect(self.database_path)) as connection:
            connection.execute("DELETE FROM auth_otp_challenges")
            connection.commit()
        locked = self.request_otp()
        for attempt in range(5):
            response = self.verify(locked, "000000")
            self.assertEqual(response.status_code, 429 if attempt == 4 else 401)
        self.assertEqual(self.verify(locked).status_code, 429)

    def test_unknown_phone_onboards_binds_and_subsequently_logs_in(self):
        mobile = "9123456780"
        challenge = self.request_otp(mobile)
        verified = self.verify(challenge)
        self.assertEqual(verified.json()["role"], "NEW_VENDOR_ONBOARDING")
        profile_body = {
            "business_category": "food",
            "preferred_division": "Nashik East",
            "priority_profile": "BALANCED",
            "preferred_language": "en",
        }
        created = self.client.post("/api/vendors", json=profile_body)
        self.assertEqual(created.status_code, 201, created.text)
        vendor_id = created.json()["vendor_id"]
        self.assertTrue(vendor_id.startswith("NV_"))
        self.assertEqual(self.client.get("/api/auth/me").json()["vendor_id"], vendor_id)
        self.client.post("/api/auth/logout")
        second_challenge = self.request_otp(mobile)
        second_login = self.verify(second_challenge)
        self.assertEqual(second_login.json()["vendor_id"], vendor_id)
        with closing(connect(self.database_path)) as connection:
            stored = connection.execute(
                "SELECT phone_hash FROM vendor_auth_identities WHERE vendor_id = ?", (vendor_id,)
            ).fetchone()[0]
            otp_rows = connection.execute("SELECT otp_hash FROM auth_otp_challenges").fetchall()
        self.assertNotEqual(stored, mobile)
        self.assertTrue(all(row[0] != self.OTP for row in otp_rows))

    def test_registration_requires_verified_onboarding(self):
        response = self.client.post("/api/vendors", json={"business_category": "food"})
        self.assertEqual(response.status_code, 401)

    def test_vendor_cannot_access_admin_or_another_vendor(self):
        self.verify(self.request_otp())
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 403)
        self.assertEqual(
            self.client.patch(
                "/api/vendors/V2024_00002", json={"priority_profile": "COMMERCIAL"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/allocation-requests/unknown/approve", json={"notes": "not allowed"}
            ).status_code,
            403,
        )

    def test_unauthenticated_admin_operations_are_blocked(self):
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/allocation-requests/unknown/approve", json={"notes": None}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/allocation-requests/unknown/reject",
                json={"rejection_reason": "No"},
            ).status_code,
            401,
        )

    def test_admin_login_and_session_identity_authorize_approval(self):
        wrong = self.admin_login("wrong-password")
        self.assertEqual(wrong.status_code, 401)
        logged_in = self.admin_login()
        self.assertEqual(logged_in.status_code, 200, logged_in.text)
        self.assertEqual(logged_in.json(), {
            "authenticated": True, "role": "ADMIN", "admin_id": "officer_01"
        })
        with closing(connect(self.database_path)) as connection:
            zone_id = connection.execute(
                "SELECT zone_id FROM zone_live_status WHERE status = 'OPEN' ORDER BY zone_id LIMIT 1"
            ).fetchone()[0]
        request = create_allocation_request(
            "V2024_00001", zone_id, "NEW_ALLOCATION", "food", "Nashik East",
            database_path=self.database_path,
        )
        approved = self.client.post(
            f"/api/allocation-requests/{request['request_id']}/approve",
            json={"approved_by": "spoofed-client-value"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["allocation"]["approved_by"], "officer_01")
        self.assertEqual(approved.json()["request"]["reviewed_by"], "officer_01")

    def test_expired_session_is_rejected(self):
        self.verify(self.request_otp())
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE auth_sessions SET expires_at = ?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
            )
            connection.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_phone_normalization_is_conservative(self):
        for value in ("9876543210", "09876543210", "919876543210", "+91 98765 43210"):
            self.assertEqual(auth_service.normalize_indian_mobile(value), "9876543210")
        for value in ("12345", "5876543210", "98765abc210", "91987654321099"):
            with self.assertRaises(auth_service.AuthError):
                auth_service.normalize_indian_mobile(value)


if __name__ == "__main__":
    unittest.main()
