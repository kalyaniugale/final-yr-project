"""Run: python -m uvicorn backend.whatsapp.webhook:app --port 8001 --workers 1."""
import asyncio
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .config import Settings
from .conversation import Conversation
from .meta_client import MetaClient, MetaError
from .recommendation_client import RecommendationClient
from .session_store import SessionStore

log = logging.getLogger(__name__)


def valid_signature(body, signature, secret):
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected.encode(), signature.encode())


def parse_events(payload, phone_number_id):
    """Discard contacts, profile names and status events; retain only needed fields."""
    events = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return events
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            if value.get("metadata", {}).get("phone_number_id") != phone_number_id:
                continue
            for msg in value.get("messages", []):
                sender, event_id = msg.get("from"), msg.get("id")
                if not isinstance(sender, str) or not sender.isdigit() or not isinstance(event_id, str) or not event_id:
                    continue
                kind = msg.get("type")
                text = ""
                if kind == "text":
                    text = msg.get("text", {}).get("body", "")
                elif kind == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") in ("button_reply", "list_reply"):
                        text = interactive.get(interactive["type"], {}).get("id", "")
                elif kind == "button":
                    text = msg.get("button", {}).get("payload", "")
                # Unsupported incoming media gets a menu hint, never downloaded.
                if isinstance(text, str):
                    events.append((event_id[:512], sender[:32], text[:4096]))
    return events


async def process_one(store, conversation, meta):
    event = store.next_event()
    if not event:
        return False
    try:
        if event["state"] == "pending":
            session, outputs = await conversation.handle(store.get(event["sender"]), event["value"])
            store.prepare(event, session, outputs)
        else:
            outputs = json.loads(event["outputs"])
        for output in outputs[event["next_output"]:]:
            await meta.send(event["sender"], output)
            store.advance(event["id"])
        store.finish(event["id"])
    except MetaError as exc:
        if exc.retryable:
            store.retry(event)
        else:
            store.finish(event["id"], "failed")
    except Exception:
        # Exception strings/tracebacks can contain sender IDs or response bodies.
        log.error("Message processing failed; retry scheduled")
        store.retry(event)
    return True


async def worker(store, conversation, meta):
    while True:
        store.cleanup()
        if not await process_one(store, conversation, meta):
            await asyncio.sleep(0.25)


def create_app(settings=None, store=None, backend=None, meta=None, run_worker=True):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        database = store or SessionStore(config.db_path, config.session_ttl)
        # Suppress HTTP client's URL logs (Meta URLs contain account identifiers).
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False) as http:
            app.state.settings, app.state.store = config, database
            conversation = Conversation(backend or RecommendationClient(http, config.backend_url))
            task = asyncio.create_task(worker(database, conversation, meta or MetaClient(http, config))) if run_worker else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if store is None:
                    database.close()

    app = FastAPI(title="WhatsApp recommendation adapter", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "exploratory"}

    @app.get("/webhook")
    async def verify(request: Request):
        query = request.query_params
        token = query.get("hub.verify_token", "")
        if query.get("hub.mode") != "subscribe" or not hmac.compare_digest(
                token.encode(), app.state.settings.verify_token.encode()) or not query.get("hub.challenge"):
            raise HTTPException(403, "Verification failed")
        return PlainTextResponse(query["hub.challenge"])

    @app.post("/webhook")
    async def receive(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise HTTPException(413, "Payload too large")
        if not valid_signature(bytes(body), request.headers.get("x-hub-signature-256", ""), app.state.settings.app_secret):
            raise HTTPException(403, "Invalid signature")
        try:
            events = parse_events(json.loads(body), app.state.settings.phone_number_id)
        except (ValueError, TypeError, AttributeError, KeyError):
            raise HTTPException(400, "Invalid event payload") from None
        # Persist before acknowledging. Slow backend/Meta calls happen in the worker.
        app.state.store.enqueue(events)
        return {"status": "accepted"}

    return app


app = create_app()
