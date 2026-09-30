"""FastAPI routes for verified direct Meta WhatsApp Cloud API webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

try:
    from ..app_config import ConfigurationError, WhatsAppSettings, get_whatsapp_settings
    from ..database import DATABASE_PATH
except ImportError:
    from app_config import ConfigurationError, WhatsAppSettings, get_whatsapp_settings
    from database import DATABASE_PATH

from .cloud_api import (
    send_button_message, send_list_message, send_location_message, send_text_message,
)
from .conversation_service import process_incoming_message, record_ignored_message
from .message_templates import BotMessage


LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=").strip().lower()
    if len(supplied) != 64:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def extract_messages(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    """Flatten message notifications; status/read/delivery events yield no messages."""
    result: list[dict[str, str | None]] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return result
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                sender = message.get("from")
                message_id = message.get("id")
                message_type = message.get("type")
                content = None
                if message_type == "text":
                    content = (message.get("text") or {}).get("body")
                elif message_type == "interactive":
                    interactive = message.get("interactive") or {}
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    content = reply.get("id") or reply.get("title")
                if sender and message_id:
                    result.append({
                        "sender": str(sender), "message_id": str(message_id),
                        "content": str(content) if content is not None else None,
                        "type": str(message_type or "unknown"),
                    })
    return result


async def dispatch_bot_message(
    recipient: str,
    message: BotMessage,
    *,
    settings: WhatsAppSettings,
    client: httpx.AsyncClient,
) -> None:
    kwargs = {"settings": settings, "client": client}
    if message.kind == "text":
        await send_text_message(recipient, message.text, **kwargs)
    elif message.kind == "buttons":
        await send_button_message(recipient, message.text, list(message.buttons), **kwargs)
    elif message.kind == "list":
        await send_list_message(recipient, message.text, list(message.rows), **kwargs)
    elif message.kind == "location" and message.latitude is not None and message.longitude is not None:
        await send_location_message(
            recipient, message.latitude, message.longitude,
            name=message.name or "Analytical reference",
            address=message.address or message.text,
            **kwargs,
        )


@router.get("/webhook", response_class=PlainTextResponse)
def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    try:
        settings = get_whatsapp_settings()
    except ConfigurationError as exc:
        raise HTTPException(503, "WhatsApp integration is not configured") from exc
    if mode != "subscribe" or not hmac.compare_digest(verify_token, settings.verify_token):
        raise HTTPException(403, "Webhook verification failed")
    return challenge


@router.post("/webhook")
async def receive_webhook(request: Request):
    try:
        settings = get_whatsapp_settings()
    except ConfigurationError as exc:
        raise HTTPException(503, "WhatsApp integration is not configured") from exc
    raw_body = await request.body()
    if not verify_meta_signature(
        raw_body, request.headers.get("x-hub-signature-256"), settings.meta_app_secret
    ):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid webhook payload")
    messages = extract_messages(payload)
    processed = 0
    ignored = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        for incoming in messages:
            try:
                if incoming["content"] is None:
                    if record_ignored_message(
                        incoming["sender"], incoming["message_id"], database_path=DATABASE_PATH
                    ):
                        ignored += 1
                    continue
                result = process_incoming_message(
                    incoming["sender"], incoming["content"], incoming["message_id"],
                    database_path=DATABASE_PATH,
                )
            except ValueError:
                LOGGER.warning("Ignored WhatsApp message with invalid sender metadata")
                ignored += 1
                continue
            if result.duplicate:
                continue
            processed += 1
            for reply in result.replies:
                await dispatch_bot_message(
                    incoming["sender"], reply, settings=settings, client=client
                )
    return {"status": "ok", "processed": processed, "ignored": ignored}
