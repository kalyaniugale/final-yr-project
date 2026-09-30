"""Local WhatsApp conversation simulator; never calls Meta APIs."""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from bootstrap import initialize_application  # noqa: E402
from database import DATABASE_PATH  # noqa: E402
from whatsapp.conversation_service import process_incoming_message  # noqa: E402


def render(reply) -> str:
    if reply.kind == "location":
        return f"[LOCATION] {reply.name}: {reply.latitude}, {reply.longitude}\n{reply.address}"
    if reply.kind == "buttons":
        choices = " | ".join(f"{button_id}={title}" for button_id, title in reply.buttons)
        return f"{reply.text}\n[BUTTONS] {choices}"
    if reply.kind == "list":
        choices = "\n".join(f"  {row_id}: {title} — {description}" for row_id, title, description in reply.rows)
        return f"{reply.text}\n[LIST]\n{choices}"
    return reply.text


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the WhatsApp bot without Meta delivery")
    parser.add_argument("--mobile", required=True, help="Test mobile in a supported Indian format")
    parser.add_argument("--message", required=True, help="Inbound text or interactive reply ID")
    parser.add_argument("--message-id", default="", help="Optional stable ID for deduplication tests")
    args = parser.parse_args()
    initialize_application(DATABASE_PATH)
    result = process_incoming_message(
        args.mobile, args.message, args.message_id or f"sim_{uuid.uuid4().hex}",
        database_path=DATABASE_PATH,
    )
    if result.duplicate:
        print("Duplicate message ignored.")
        return
    for reply in result.replies:
        print(render(reply))
        print("---")


if __name__ == "__main__":
    main()
