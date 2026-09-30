import hashlib
import hmac
import json
import os
import asyncio
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient

import backend.api as api
from backend.auth_service import bind_verified_phone_hash, phone_hmac
from backend.database import (
    approve_allocation_request,
    connect,
    create_allocation_request,
    initialize_database,
)
from backend.vendor_service import register_vendor
from backend.whatsapp import cloud_api
from backend.whatsapp import conversation_service as conversations
from backend.whatsapp import webhook


class WhatsAppBotTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "whatsapp.db"
        initialize_database(self.database_path)
        self.environment = patch.dict(os.environ, {
            "APP_ENV": "test",
            "AUTH_HMAC_SECRET": "whatsapp-unit-test-secret-not-for-production",
            "SESSION_COOKIE_SECURE": "false",
            "OTP_PROVIDER": "development",
            "OTP_DEBUG": "false",
            "NMC_ADMIN_USERNAME": "officer",
            "NMC_ADMIN_PASSWORD": "unit-test-password",
            "WHATSAPP_ACCESS_TOKEN": "test-meta-token",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789",
            "WHATSAPP_VERIFY_TOKEN": "verify-me",
            "META_APP_SECRET": "test-app-secret",
            "WHATSAPP_GRAPH_VERSION": "v23.0",
        }, clear=False)
        self.environment.start()
        self.api_db = patch.object(api, "DATABASE_PATH", self.database_path)
        self.webhook_db = patch.object(webhook, "DATABASE_PATH", self.database_path)
        self.api_db.start()
        self.webhook_db.start()
        self.client = TestClient(api.app)
        self.counter = 0

    def tearDown(self):
        self.client.close()
        self.webhook_db.stop()
        self.api_db.stop()
        self.environment.stop()
        self.temp_directory.cleanup()

    def next_id(self):
        self.counter += 1
        return f"wamid.test.{self.counter}"

    def send(self, mobile, message, message_id=None):
        return conversations.process_incoming_message(
            mobile, message, message_id or self.next_id(), database_path=self.database_path
        )

    def create_vendor(self, mobile="919876543210", language="en"):
        profile = register_vendor({
            "full_name": "Test Vendor",
            "business_category": "food",
            "preferred_division": "Nashik East",
            "preferred_locality": "Market Road",
            "priority_profile": "BALANCED",
            "parking_preference": False,
            "transport_preference": True,
            "market_preference": True,
            "preferred_language": language,
        }, self.database_path)
        bind_verified_phone_hash(
            phone_hmac("9876543210"), profile["vendor_id"], self.database_path
        )
        return profile

    def signed_payload(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
        return body, {"content-type": "application/json", "x-hub-signature-256": f"sha256={signature}"}

    def inbound_payload(self, message_type="text", message=None):
        incoming = {"from": "919876543210", "id": "wamid.webhook.1", "type": message_type}
        if message_type == "text":
            incoming["text"] = {"body": message or "Hi"}
        elif message_type == "interactive":
            incoming["interactive"] = {"type": "button_reply", "button_reply": {"id": message or "menu:1", "title": "Choice"}}
        else:
            incoming[message_type] = {"id": "media-id"}
        return {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"messages": [incoming]}}]}],
        }

    def test_webhook_verification_and_wrong_token(self):
        accepted = self.client.get("/api/whatsapp/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345",
        })
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.text, "12345")
        rejected = self.client.get("/api/whatsapp/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345",
        })
        self.assertEqual(rejected.status_code, 403)

    def test_webhook_signature_validation_and_mocked_outbound(self):
        self.create_vendor()
        payload = self.inbound_payload()
        body, headers = self.signed_payload(payload)
        with patch.object(webhook, "dispatch_bot_message", new=AsyncMock()) as dispatch:
            response = self.client.post("/api/whatsapp/webhook", content=body, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        self.assertGreaterEqual(dispatch.await_count, 1)
        bad = self.client.post(
            "/api/whatsapp/webhook", content=body,
            headers={"content-type": "application/json", "x-hub-signature-256": "sha256=" + "0" * 64},
        )
        self.assertEqual(bad.status_code, 401)

    def test_existing_vendor_lookup_uses_saved_language_and_readable_id(self):
        profile = self.create_vendor(language="mr")
        result = self.send("919876543210", "Hi")
        combined = "\n".join(reply.text for reply in result.replies)
        self.assertIn("Test Vendor", combined)
        self.assertIn(profile["application_vendor_id"], combined)
        self.assertNotIn(profile["vendor_id"], combined)
        with closing(connect(self.database_path)) as connection:
            conversation = connection.execute("SELECT * FROM whatsapp_conversations").fetchone()
        self.assertEqual(conversation["language"], "mr")
        self.assertEqual(conversation["vendor_id"], profile["vendor_id"])

    def test_new_vendor_onboarding_languages_and_confirmation(self):
        mobile = "919123456780"
        self.assertIn("English", self.send(mobile, "Hi").replies[0].text)
        marathi_prompt = self.send(mobile, "2")
        self.assertIn("पूर्ण नाव", marathi_prompt.replies[0].text)
        self.send(mobile, "नमुना विक्रेता")
        self.send(mobile, "5")  # food
        self.send(mobile, "1")  # first valid division
        self.send(mobile, "SKIP")
        self.send(mobile, "1")  # balanced
        self.send(mobile, "1")  # market yes
        self.send(mobile, "2")  # transport no
        summary = self.send(mobile, "1")  # parking yes
        self.assertIn("नमुना विक्रेता", summary.replies[0].text)
        completed = self.send(mobile, "1")
        self.assertIn("Application Vendor ID", completed.replies[0].text)
        with closing(connect(self.database_path)) as connection:
            vendor = connection.execute("SELECT * FROM operational_vendors").fetchone()
            identity = connection.execute("SELECT * FROM vendor_auth_identities").fetchone()
            conversation = connection.execute("SELECT * FROM whatsapp_conversations").fetchone()
            serialized = " ".join(str(tuple(row)) for row in (vendor, identity, conversation))
        self.assertEqual(vendor["preferred_language"], "mr")
        self.assertEqual(vendor["business_category"], "food")
        self.assertNotIn("9123456780", serialized)

    def test_hindi_language_selection_persists_across_messages(self):
        mobile = "919234567890"
        self.send(mobile, "Start")
        result = self.send(mobile, "3")
        self.assertIn("पूरा नाम", result.replies[0].text)
        with closing(connect(self.database_path)) as connection:
            language = connection.execute("SELECT language FROM whatsapp_conversations").fetchone()[0]
        self.assertEqual(language, "hi")

    def test_recommendations_reuse_mcda_and_create_request_once(self):
        profile = self.create_vendor()
        self.send("919876543210", "Hi")
        with patch.object(conversations, "recommend", wraps=conversations.recommend) as shared_engine:
            recommendations = self.send("919876543210", "2")
        self.assertEqual(shared_engine.call_count, 1)
        self.assertIn("Scores are decision-support values, not probabilities", recommendations.replies[0].text)
        selected = self.send("919876543210", "1")
        self.assertIn("Submit request to NMC", selected.replies[0].text)
        submitted = self.send("919876543210", "1")
        self.assertIn("Request submitted", submitted.replies[0].text)
        with closing(connect(self.database_path)) as connection:
            requests = connection.execute("SELECT * FROM allocation_requests").fetchall()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["vendor_id"], profile["vendor_id"])

    def test_duplicate_message_is_idempotent(self):
        self.create_vendor()
        first = self.send("919876543210", "Hi", "wamid.same")
        duplicate = self.send("919876543210", "Hi", "wamid.same")
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.replies, ())
        with closing(connect(self.database_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM whatsapp_processed_messages").fetchone()[0]
        self.assertEqual(count, 1)

    def test_pending_request_protection_and_cancellation(self):
        profile = self.create_vendor()
        self.send("919876543210", "Hi")
        self.send("919876543210", "2")
        self.send("919876543210", "1")
        self.send("919876543210", "1")
        self.send("919876543210", "menu")
        self.send("919876543210", "2")
        blocked = self.send("919876543210", "2")
        self.assertIn("already have a request", blocked.replies[0].text)
        self.send("919876543210", "cancel")
        cancelled = self.send("919876543210", "1")
        self.assertIn("cancelled", cancelled.replies[0].text)
        with closing(connect(self.database_path)) as connection:
            statuses = [row[0] for row in connection.execute(
                "SELECT status FROM allocation_requests WHERE vendor_id = ?", (profile["vendor_id"],)
            )]
        self.assertEqual(statuses, ["CANCELLED"])

    def test_active_allocation_and_relocation_flow(self):
        profile = self.create_vendor()
        with closing(connect(self.database_path)) as connection:
            zone_id = connection.execute(
                "SELECT zone_id FROM zone_live_status WHERE status='OPEN' AND available_capacity > 0 LIMIT 1"
            ).fetchone()[0]
        request = create_allocation_request(
            profile["vendor_id"], zone_id, "NEW_ALLOCATION", "food", "Nashik East",
            database_path=self.database_path,
        )
        approve_allocation_request(request["request_id"], "officer", database_path=self.database_path)
        self.send("919876543210", "Hi")
        allocation = self.send("919876543210", "1")
        self.assertIn("Current allocation", allocation.replies[0].text)
        self.send("919876543210", "2")
        selection = self.send("919876543210", "1")
        self.assertIn("relocation", selection.replies[0].text.lower())
        self.send("919876543210", "1")
        with closing(connect(self.database_path)) as connection:
            latest = connection.execute(
                "SELECT request_type FROM allocation_requests ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(latest, "RELOCATION")

    def test_location_and_short_explanation(self):
        self.create_vendor()
        self.send("919876543210", "Hi")
        self.send("919876543210", "2")
        why = self.send("919876543210", "WHY 1")
        self.assertIn("Why", why.replies[0].text)
        mapped = self.send("919876543210", "MAP 1")
        self.assertEqual(mapped.replies[-1].kind, "location")
        self.assertIn("not a legally verified", mapped.replies[0].text)

    def test_persistent_state_and_repeated_invalid_input(self):
        self.create_vendor()
        self.send("919876543210", "Hi")
        self.send("919876543210", "2")
        for _ in range(2):
            self.send("919876543210", "nonsense")
        third = self.send("919876543210", "still wrong")
        self.assertGreater(len(third.replies), 1)
        with closing(connect(self.database_path)) as connection:
            row = connection.execute("SELECT flow, step FROM whatsapp_conversations").fetchone()
        self.assertEqual(tuple(row), ("MENU", "MAIN"))

    def test_profile_preference_update_reuses_vendor_service(self):
        profile = self.create_vendor()
        self.send("919876543210", "Hi")
        self.send("919876543210", "4")
        self.send("919876543210", "3")
        with patch.object(
            conversations, "update_vendor_profile", wraps=conversations.update_vendor_profile
        ) as update_service:
            updated = self.send("919876543210", "2")
        self.assertEqual(update_service.call_count, 1)
        self.assertIn("Profile updated", updated.replies[0].text)
        with closing(connect(self.database_path)) as connection:
            priority = connection.execute(
                "SELECT priority_profile FROM operational_vendors WHERE vendor_id = ?",
                (profile["vendor_id"],),
            ).fetchone()[0]
        self.assertEqual(priority, "COMMERCIAL")

    def test_status_events_and_unsupported_media_are_ignored(self):
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.status"}]}}]}],
        }
        body, headers = self.signed_payload(status_payload)
        response = self.client.post("/api/whatsapp/webhook", content=body, headers=headers)
        self.assertEqual(response.json(), {"status": "ok", "processed": 0, "ignored": 0})
        body, headers = self.signed_payload(self.inbound_payload("image"))
        response = self.client.post("/api/whatsapp/webhook", content=body, headers=headers)
        self.assertEqual(response.json()["ignored"], 1)

    def test_cloud_api_posts_direct_meta_payload(self):
        from backend.app_config import get_whatsapp_settings
        settings = get_whatsapp_settings()
        response = Mock(status_code=200)
        response.json.return_value = {"messages": [{"id": "wamid.out"}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = response
        result = asyncio.run(cloud_api.send_text_message(
            "919876543210", "Hello", settings=settings, client=client
        ))
        self.assertEqual(result["messages"][0]["id"], "wamid.out")
        url = client.post.await_args.args[0]
        headers = client.post.await_args.kwargs["headers"]
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(url, "https://graph.facebook.com/v23.0/123456789/messages")
        self.assertEqual(headers["Authorization"], "Bearer test-meta-token")
        self.assertEqual(payload["messaging_product"], "whatsapp")


if __name__ == "__main__":
    unittest.main()
