import os
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.bootstrap as bootstrap
from backend.app_config import ConfigurationError, ENV_FILE, PROJECT_ROOT, get_auth_settings


class ApplicationConfigurationTests(unittest.TestCase):
    def test_env_file_is_resolved_from_module_location(self):
        expected_root = Path(__file__).resolve().parents[1]
        self.assertEqual(PROJECT_ROOT, expected_root)
        self.assertEqual(ENV_FILE, expected_root / ".env")

    def test_missing_configuration_names_keys_without_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError) as raised:
                get_auth_settings()
        message = str(raised.exception)
        self.assertIn("AUTH_HMAC_SECRET", message)
        self.assertIn("NMC_ADMIN_PASSWORD", message)

    def test_boolean_configuration_is_strict(self):
        configured = {
            "APP_ENV": "test",
            "AUTH_HMAC_SECRET": "unit-test-secret",
            "SESSION_COOKIE_SECURE": "sometimes",
            "OTP_PROVIDER": "development",
            "OTP_DEBUG": "false",
            "NMC_ADMIN_USERNAME": "test-admin",
            "NMC_ADMIN_PASSWORD": "unit-test-password",
        }
        with patch.dict(os.environ, configured, clear=True):
            with self.assertRaisesRegex(
                ConfigurationError, "SESSION_COOKIE_SECURE must be true or false"
            ):
                get_auth_settings()

    def test_bootstrap_order_is_config_schema_then_historical_identities(self):
        calls = []
        with (
            patch.object(bootstrap, "get_auth_settings", side_effect=lambda: calls.append("config")),
            patch.object(
                bootstrap,
                "initialize_database",
                side_effect=lambda *_: calls.append("schema-and-zones") or {"inserted": 0},
            ),
            patch.object(
                bootstrap,
                "seed_historical_vendor_identities",
                side_effect=lambda *_: calls.append("historical-identities") or {"inserted": 0},
            ),
        ):
            bootstrap.initialize_application("test.db", "zones.csv", "vendors.csv")
        self.assertEqual(calls, ["config", "schema-and-zones", "historical-identities"])


if __name__ == "__main__":
    unittest.main()
