"""Minimal direct client for Meta WhatsApp Cloud API message delivery."""
from __future__ import annotations

from typing import Any

import httpx

try:
    from ..app_config import WhatsAppSettings, get_whatsapp_settings
except ImportError:
    from app_config import WhatsAppSettings, get_whatsapp_settings


class WhatsAppDeliveryError(RuntimeError):
    """Safe delivery failure that never includes credentials or response bodies."""


def _endpoint(settings: WhatsAppSettings) -> str:
    return (
        f"https://graph.facebook.com/{settings.graph_version}/"
        f"{settings.phone_number_id}/messages"
    )


async def _send_payload(
    recipient: str,
    message: dict[str, Any],
    *,
    settings: WhatsAppSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    settings = settings or get_whatsapp_settings()
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient, **message}
    headers = {
        "Authorization": f"Bearer {settings.access_token}",
        "Content-Type": "application/json",
    }
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=15.0)
    try:
        response = await active_client.post(_endpoint(settings), headers=headers, json=payload)
        if response.status_code >= 400:
            raise WhatsAppDeliveryError(
                f"Meta WhatsApp delivery failed with HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppDeliveryError("Meta WhatsApp returned an invalid response") from exc
    except httpx.HTTPError as exc:
        raise WhatsAppDeliveryError("Meta WhatsApp delivery request failed") from exc
    finally:
        if owns_client:
            await active_client.aclose()


async def send_text_message(recipient: str, text: str, **kwargs) -> dict[str, Any]:
    return await _send_payload(recipient, {"type": "text", "text": {"preview_url": False, "body": text}}, **kwargs)


async def send_button_message(
    recipient: str,
    body: str,
    buttons: list[tuple[str, str]],
    **kwargs,
) -> dict[str, Any]:
    action = {"buttons": [
        {"type": "reply", "reply": {"id": button_id[:256], "title": title[:20]}}
        for button_id, title in buttons[:3]
    ]}
    return await _send_payload(recipient, {
        "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body[:1024]}, "action": action},
    }, **kwargs)


async def send_list_message(
    recipient: str,
    body: str,
    rows: list[tuple[str, str, str]],
    *,
    button_label: str = "Choose",
    **kwargs,
) -> dict[str, Any]:
    action = {
        "button": button_label[:20],
        "sections": [{"title": "Options", "rows": [
            {"id": row_id[:200], "title": title[:24], "description": description[:72]}
            for row_id, title, description in rows[:10]
        ]}],
    }
    return await _send_payload(recipient, {
        "type": "interactive",
        "interactive": {"type": "list", "body": {"text": body[:1024]}, "action": action},
    }, **kwargs)


async def send_location_message(
    recipient: str,
    latitude: float,
    longitude: float,
    *,
    name: str,
    address: str,
    **kwargs,
) -> dict[str, Any]:
    return await _send_payload(recipient, {
        "type": "location",
        "location": {
            "latitude": latitude, "longitude": longitude,
            "name": name[:1000], "address": address[:1000],
        },
    }, **kwargs)
