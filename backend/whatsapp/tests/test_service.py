import asyncio
import copy
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from backend.whatsapp.config import Settings
from backend.whatsapp.conversation import Conversation
from backend.whatsapp import messages as m
from backend.whatsapp.meta_client import MetaClient, MetaError
from backend.whatsapp.recommendation_client import RecommendationClient, BackendError
from backend.whatsapp.session_store import SessionStore
from backend.whatsapp.translations import CATEGORIES, LANGUAGES, STRINGS
from backend.whatsapp.webhook import create_app, parse_events, process_one, valid_signature


def recommendation(zone="NE_F_010", rank=1):
    return {"zone_id": zone, "rank": rank, "official_description": "Market reference",
        "zone_division": "Nashik East", "score": 60.25, "score_coverage": 0.8,
        "same_business_count": 5, "evidence_count": 20, "distance_to_major_road_m": 137,
        "distance_to_bus_access_m": None, "shared_reference": True, "shared_reference_group_size": 15,
        "factors": [{"key": key, "label": key, "score": 0.5, "weight": 10,
                     "contribution": 5, "summary": "Historical map evidence", "details": "Not sales.",
                     "evidence": [{"label": "Records", "value": "20"}]}
                    for key in ("business", "commercial", "access", "facilities", "preference", "historical")]}


def settings():
    return Settings("fake-token", "123", "verify-secret", "app-secret", "v99.0")


def payload(message=None):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages",
        "value": {"metadata": {"phone_number_id": "123"}, "messages": [message] if message else [],
                  "statuses": [{"status": "delivered"}]}}]}]}


def message(value="Hi", event_id="event-1"):
    return {"from": "919999999999", "id": event_id, "type": "text", "text": {"body": value}}


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = AsyncMock()
        self.backend.options.return_value = {"categories": list(CATEGORIES), "divisions": ["Nashik East", "Satpur"]}
        self.backend.recommend.return_value = [recommendation()]
        self.backend.point.return_value = (20.1, 73.8)
        self.bot = Conversation(self.backend)

    async def flow(self, lang="en", vendor="new", division="division:any"):
        s = None
        for value in ("Hi", "lang:"+lang, "find", "vendor:"+vendor, "business:food", division):
            s, out = await self.bot.handle(s, value)
        return s, out

    async def test_new_and_existing_manual_all_languages(self):
        for lang in LANGUAGES:
            for vendor in ("new", "existing"):
                with self.subTest(lang=lang, vendor=vendor):
                    s, out = await self.flow(lang, vendor)
                    self.assertEqual(s["language"], lang)
                    self.assertEqual(s["vendor_type"], vendor)
                    self.assertEqual(s["state"], "RESULTS")
                    self.backend.recommend.assert_awaited_with("food", "")
                    self.assertTrue(out)

    async def test_categories_and_named_division(self):
        for code in CATEGORIES:
            s = None
            for value in ("hi", "lang:en", "find", "vendor:new", "business:"+code):
                s, out = await self.bot.handle(s, value)
            self.assertEqual(s["business"], code)
            key = next(key for key, name in s["divisions"].items() if name == "Satpur")
            s, out = await self.bot.handle(s, key)
            self.backend.recommend.assert_awaited_with(code, "Satpur")

    async def test_api_options_authoritative(self):
        self.backend.options.return_value["categories"] = ["food"]
        s = None
        for value in ("hi", "lang:en", "find", "vendor:new"):
            s, out = await self.bot.handle(s, value)
        rows = out[0]["interactive"]["action"]["sections"][0]["rows"]
        self.assertEqual([r["id"] for r in rows], ["business:food"])
        s, out = await self.bot.handle(s, "business:tea_beverage")
        self.assertEqual(s["state"], "BUSINESS")

    async def test_zero_one_two_three(self):
        for count in range(4):
            self.backend.recommend.return_value = [recommendation(f"Z{i}", i+1) for i in range(count)]
            s, out = await self.flow()
            self.assertEqual(len(s["recommendations"]), count)
            selections = [p for p in out if p["type"] == "interactive" and
                          any(b["reply"]["id"].startswith("zone:") for b in p["interactive"]["action"].get("buttons", []))]
            self.assertEqual(len(selections), int(count > 0))
            if count:
                self.assertEqual(len(selections[0]["interactive"]["action"]["buttons"]), count)

    async def test_snapshot_selection_views_and_restart(self):
        s, _ = await self.flow()
        snap = s["snapshot"]
        s, _ = await self.bot.handle(s, f"zone:{snap}:0")
        self.assertEqual(s["selected_zone_id"], "NE_F_010")
        for action, state in (("simple", "SIMPLE_EXPLANATION"), ("detailed", "DETAILED_ANALYSIS"), ("map", "MAP")):
            s, out = await self.bot.handle(s, f"view:{snap}:{s['selected_zone_id']}:{action}")
            self.assertEqual(s["state"], state)
            if action == "map":
                loc = next(p["location"] for p in out if p["type"] == "location")
                self.assertEqual((loc["latitude"], loc["longitude"]), (20.1, 73.8))
        self.backend.recommend.assert_awaited_once()
        s, _ = await self.bot.handle(s, "results")
        self.assertEqual(s["state"], "RESULTS")
        s, _ = await self.bot.handle(s, "zone:old:0")
        self.assertEqual(s["state"], "RESULTS")
        s, _ = await self.bot.handle(s, "menu")
        self.assertEqual(s["state"], "LANGUAGE")
        self.assertEqual(s["recommendations"], [])

    async def test_missing_geometry(self):
        self.backend.point.return_value = None
        s, _ = await self.flow()
        s, _ = await self.bot.handle(s, f"zone:{s['snapshot']}:0")
        s, out = await self.bot.handle(s, f"view:{s['snapshot']}:{s['selected_zone_id']}:map")
        self.assertFalse(any(p["type"] == "location" for p in out))
        self.assertIn("No valid map point", str(out))

    async def test_old_view_cannot_show_another_zone(self):
        self.backend.recommend.return_value = [recommendation("Z1", 1), recommendation("Z2", 2)]
        s, _ = await self.flow()
        s, _ = await self.bot.handle(s, f"zone:{s['snapshot']}:0")
        old_action = f"view:{s['snapshot']}:Z1:map"
        s, _ = await self.bot.handle(s, "results")
        s, _ = await self.bot.handle(s, f"zone:{s['snapshot']}:1")
        s, out = await self.bot.handle(s, old_action)
        self.backend.point.assert_not_awaited()
        self.assertEqual(s["selected_zone_id"], "Z2")

    async def test_errors_never_fabricate_results(self):
        for kind in ("timeout", "invalid", "unavailable", "unexpected"):
            self.backend.recommend.side_effect = BackendError(kind)
            s, out = await self.flow()
            self.assertEqual(s["recommendations"], [])
            self.assertEqual(s["state"], "DIVISION")

    async def test_paginated_divisions(self):
        self.backend.options.return_value["divisions"] = [f"Area {i}" for i in range(15)]
        s = None
        for value in ("hi", "lang:en", "find", "vendor:new", "business:food", "page:1"):
            s, out = await self.bot.handle(s, value)
        self.assertLessEqual(len(out[0]["interactive"]["action"]["sections"][0]["rows"]), 10)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_request(self):
        captured = []
        def route(req):
            captured.append(req)
            return httpx.Response(200, json={"recommendations": [recommendation()], "count": 1})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
            rows = await RecommendationClient(http, "http://backend").recommend("food", "Satpur")
        self.assertEqual(len(rows), 1)
        self.assertEqual(captured[0].url.path, "/api/recommendations")
        self.assertEqual(json.loads(captured[0].content), {"business": "food", "division": "Satpur",
                         "vendor_id": "", "exclude_zone": "", "top_n": 3, "require_verified": False})

    async def test_http_errors(self):
        for status, kind in ((422, "invalid"), (503, "unavailable")):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as http:
                with self.assertRaises(BackendError) as ctx:
                    await RecommendationClient(http, "http://backend").options()
                self.assertEqual(ctx.exception.kind, kind)
        def timeout(req):
            raise httpx.ReadTimeout("private details")
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
            with self.assertRaises(BackendError) as ctx:
                await RecommendationClient(http, "http://backend").options()
            self.assertEqual(str(ctx.exception), "timeout")

    async def test_unexpected_data(self):
        malformed = recommendation()
        malformed["factors"][0]["key"] = []
        for data in ({}, {"recommendations": [None], "count": 1}, {"recommendations": [recommendation()], "count": 3},
                     {"recommendations": [malformed], "count": 1}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as http:
                with self.assertRaises(BackendError):
                    await RecommendationClient(http, "http://backend").recommend("food", "")

    async def test_geometry_join_and_invalid_coordinates(self):
        for coordinates, expected in (([73.8, 20.1], (20.1, 73.8)), ([73, 200], None), (["73", 20], None), ([None, 20], None)):
            data = {"type": "FeatureCollection", "features": [
                {"properties": {"zone_id": "other"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"properties": {"zone_id": "Z1"}, "geometry": {"type": "Point", "coordinates": coordinates}}]}
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as http:
                client = RecommendationClient(http, "http://backend")
                self.assertEqual(await client.point("Z1"), expected)
                self.assertIsNone(await client.point("missing"))

    async def test_meta_payload_and_failure(self):
        seen = []
        def route(req):
            seen.append(req)
            return httpx.Response(200, json={"messages": [{"id": "out"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
            await MetaClient(http, settings()).send("919999999999", m.texts("hello")[0])
        body = json.loads(seen[0].content)
        self.assertEqual(body["messaging_product"], "whatsapp")
        self.assertEqual(body["to"], "919999999999")
        self.assertIn("/v99.0/123/messages", str(seen[0].url))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as http:
            with self.assertRaises(MetaError) as ctx:
                await MetaClient(http, settings()).send("123", m.texts("test")[0])
            self.assertFalse(ctx.exception.retryable)


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = SessionStore(":memory:")
        self.app = create_app(settings(), self.store, run_worker=False)
        self.life = self.app.router.lifespan_context(self.app)
        await self.life.__aenter__()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.http.aclose()
        await self.life.__aexit__(None, None, None)
        self.store.close()

    async def test_verification(self):
        params = {"hub.mode": "subscribe", "hub.verify_token": "verify-secret", "hub.challenge": "12345"}
        r = await self.http.get("/webhook", params=params)
        self.assertEqual((r.status_code, r.text), (200, "12345"))
        for key in ("hub.verify_token", "hub.mode"):
            bad = dict(params, **{key: "bad"})
            self.assertEqual((await self.http.get("/webhook", params=bad)).status_code, 403)

    async def test_signature_and_duplicate_delivery(self):
        body = json.dumps(payload(message())).encode()
        signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        for headers in ({}, {"x-hub-signature-256": "sha256=wrong"}):
            self.assertEqual((await self.http.post("/webhook", content=body, headers=headers)).status_code, 403)
        for _ in range(2):
            self.assertEqual((await self.http.post("/webhook", content=body,
                             headers={"x-hub-signature-256": signature})).status_code, 200)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0], 1)
        self.assertFalse(valid_signature(body+b" ", signature, "app-secret"))
        self.assertFalse(valid_signature(body, "अमान्य", "app-secret"))

    async def test_status_only_ignored(self):
        self.assertEqual(parse_events(payload(), "123"), [])
        self.assertEqual(parse_events(payload(message()), "wrong-phone"), [])

    async def test_text_button_list_parsing(self):
        self.assertEqual(parse_events(payload(message()), "123")[0][2], "Hi")
        for kind in ("button_reply", "list_reply"):
            msg = {**message(), "type": "interactive", "interactive": {"type": kind, kind: {"id": "business:food", "title": "Ignore label"}}}
            self.assertEqual(parse_events(payload(msg), "123")[0][2], "business:food")


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_dedup_and_resumption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp)/"sessions.sqlite3")
            store = SessionStore(path)
            conversation, meta = AsyncMock(), AsyncMock()
            conversation.handle.return_value = ({"language": "en"}, m.texts("one") + m.texts("two"))
            meta.send.side_effect = [None, MetaError(True)]
            store.enqueue([("id1", "123", "Hi"), ("id1", "123", "Hi")])
            await process_one(store, conversation, meta)
            self.assertEqual(store.db.execute("SELECT next_output FROM inbox").fetchone()[0], 1)
            store.close()
            store = SessionStore(path)
            with store.db:
                store.db.execute("UPDATE inbox SET retry_at=0")
            meta.send.side_effect = None
            await process_one(store, conversation, meta)
            conversation.handle.assert_awaited_once()
            self.assertEqual(meta.send.await_args.args[1]["text"]["body"], "two")
            self.assertEqual(store.get("123"), {"language": "en"})
            store.enqueue([("id1", "123", "Hi")])
            self.assertIsNone(store.next_event())
            store.close()

    async def test_session_expiry_and_cleanup(self):
        store = SessionStore(":memory:", ttl=10)
        store.enqueue([("id", "123", "Hi")])
        event = store.next_event()
        store.prepare(event, {"language": "mr"}, [])
        with store.db:
            store.db.execute("UPDATE sessions SET updated=?", (time.time()-11,))
            store.db.execute("UPDATE inbox SET created=?", (time.time()-11,))
        self.assertIsNone(store.get("123"))
        store.cleanup()
        self.assertIsNone(store.next_event())
        self.assertEqual(store.db.execute("SELECT sender FROM inbox").fetchone()[0], "")
        store.close()


class PresentationTests(unittest.TestCase):
    def test_missing_values_and_contribution_coverage(self):
        for lang in LANGUAGES:
            simple = str(m.simple(lang, recommendation()))
            self.assertIn(STRINGS["unknown"][LANGUAGES.index(lang)], simple)
            detail = str(m.detailed(lang, recommendation()))
            self.assertIn("0.800", detail)
            self.assertIn("50.0", detail)
            self.assertIn("5.00", detail)

    def test_translation_and_payload_limits(self):
        for values in STRINGS.values():
            self.assertEqual(len(values), 3)
            self.assertTrue(all(values))
        for lang in LANGUAGES:
            choices = [(key, STRINGS[key][LANGUAGES.index(lang)]) for key in ("simple", "detailed", "map")]
            p = m.buttons("Choose", choices)
            self.assertTrue(all(len(b["reply"]["title"]) <= 20 for b in p["interactive"]["action"]["buttons"]))
        self.assertTrue(all(len(p["text"]["body"]) <= 3500 for p in m.texts("x"*10000)))


if __name__ == "__main__":
    unittest.main()
