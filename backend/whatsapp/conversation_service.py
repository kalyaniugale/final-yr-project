"""Persistent deterministic conversation state for the WhatsApp vendor channel."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from ..auth_service import (
        bind_verified_phone_hash,
        find_vendor_by_phone_hash,
        normalize_indian_mobile,
        phone_hmac,
    )
    from ..database import (
        DATABASE_PATH,
        OperationalConflictError,
        OperationalNotFoundError,
        OperationalValidationError,
        cancel_allocation_request,
        connect,
        create_allocation_request,
        get_vendor_dashboard_activity,
        transaction,
        utc_now,
    )
    from ..mcda_engine import CATEGORIES, derive_mcda_weights, recommend
    from ..recommendation_explanations import explain
    from ..vendor_service import get_vendor_profile, register_vendor, update_vendor_profile, valid_divisions
except ImportError:
    from auth_service import bind_verified_phone_hash, find_vendor_by_phone_hash, normalize_indian_mobile, phone_hmac
    from database import (
        DATABASE_PATH, OperationalConflictError, OperationalNotFoundError,
        OperationalValidationError, cancel_allocation_request, connect,
        create_allocation_request, get_vendor_dashboard_activity, transaction, utc_now,
    )
    from mcda_engine import CATEGORIES, derive_mcda_weights, recommend
    from recommendation_explanations import explain
    from vendor_service import get_vendor_profile, register_vendor, update_vendor_profile, valid_divisions

from .message_templates import (
    BotMessage, CATEGORY_LABELS, STATUS_LABELS, button_message, list_message,
    location_message, text_message, tr,
)


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_PATH = ROOT / "reports" / "data_quality" / "geometry_duplicates" / "reference_points.geojson"
CONVERSATION_TTL = timedelta(hours=24)
LANGUAGE_CHOICES = {"1": "en", "2": "mr", "3": "hi", "english": "en", "मराठी": "mr", "हिन्दी": "hi", "हिंदी": "hi"}
WHATSAPP_CATEGORY_ORDER = (
    "vegetable_fruit", "flower", "clothing", "general_goods", "food", "other",
)
if set(WHATSAPP_CATEGORY_ORDER) != set(CATEGORIES):
    raise RuntimeError("WhatsApp category menu must match the canonical recommendation categories")
CATEGORY_CHOICES = {
    str(index): value for index, value in enumerate(WHATSAPP_CATEGORY_ORDER, start=1)
}
PRIORITY_CHOICES = {"1": "BALANCED", "2": "COMMERCIAL", "3": "ACCESSIBILITY", "4": "FACILITIES"}
YES_VALUES = {"1", "yes", "y", "हो", "हाँ", "हां"}
NO_VALUES = {"2", "no", "n", "नाही", "नहीं"}
MENU_WORDS = {"menu", "मेनू", "मेन्यु"}
BACK_WORDS = {"back", "मागे", "वापस"}
HELP_WORDS = {"help", "मदत", "मदद"}
CANCEL_WORDS = {"cancel", "रद्द"}
START_WORDS = {"hi", "hello", "start", "नमस्कार", "हॅलो", "हैलो", "नमस्ते"} | MENU_WORDS


@dataclass(frozen=True)
class ConversationResult:
    duplicate: bool
    replies: tuple[BotMessage, ...]
    flow: str
    step: str
    vendor_id: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mask_mobile(normalized: str) -> str:
    return f"********{normalized[-2:]}"


def _choice(raw: str) -> str:
    value = (raw or "").strip().lower()
    if ":" in value:
        prefix, suffix = value.rsplit(":", 1)
        if prefix in {"menu", "lang", "category", "division", "priority", "boolean", "profile", "confirm", "recommendation", "request"}:
            value = suffix
    return value


def _state(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("state_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _row_dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _claim_message(message_id: str, hashed_phone: str, database_path: str | Path) -> bool:
    if not message_id or len(message_id) > 512:
        raise ValueError("A valid WhatsApp message ID is required")
    try:
        with transaction(database_path, immediate=True) as connection:
            connection.execute(
                """INSERT INTO whatsapp_processed_messages
                   (message_id, phone_hash, status, received_at)
                   VALUES (?, ?, 'PROCESSING', ?)""",
                (message_id, hashed_phone, utc_now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def _finish_message(message_id: str, status: str, database_path: str | Path, error_code: str | None = None) -> None:
    with transaction(database_path, immediate=True) as connection:
        connection.execute(
            """UPDATE whatsapp_processed_messages
               SET status = ?, processed_at = ?, error_code = ? WHERE message_id = ?""",
            (status, utc_now(), error_code, message_id),
        )


def _load_conversation(hashed_phone: str, database_path: str | Path) -> dict[str, Any]:
    connection = connect(database_path)
    try:
        row = connection.execute(
            "SELECT * FROM whatsapp_conversations WHERE phone_hash = ?", (hashed_phone,)
        ).fetchone()
    finally:
        connection.close()
    vendor_id = find_vendor_by_phone_hash(hashed_phone, database_path)
    now = _now()
    if row is None:
        preferred_language = "en"
        if vendor_id:
            profile = get_vendor_profile(vendor_id, database_path=database_path)
            preferred_language = (profile or {}).get("preferred_language") or "en"
        return {
            "conversation_key": f"wa_{hashed_phone}", "phone_hash": hashed_phone,
            "vendor_id": vendor_id, "language": preferred_language, "flow": "START", "step": "START",
            "state_json": "{}", "invalid_count": 0,
            "updated_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + CONVERSATION_TTL).isoformat(timespec="seconds"),
        }
    conversation = dict(row)
    conversation["vendor_id"] = vendor_id or conversation.get("vendor_id")
    if conversation["vendor_id"]:
        profile = get_vendor_profile(conversation["vendor_id"], database_path=database_path)
        if profile:
            conversation["language"] = profile.get("preferred_language") or conversation["language"]
    try:
        expired = datetime.fromisoformat(conversation["expires_at"]) <= now
    except (TypeError, ValueError):
        expired = True
    if expired:
        conversation.update({"flow": "START", "step": "START", "state_json": "{}", "invalid_count": 0})
    return conversation


def _save_conversation(conversation: dict[str, Any], state: dict[str, Any], database_path: str | Path) -> None:
    now = _now()
    conversation["state_json"] = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    conversation["updated_at"] = now.isoformat(timespec="seconds")
    conversation["expires_at"] = (now + CONVERSATION_TTL).isoformat(timespec="seconds")
    with transaction(database_path, immediate=True) as connection:
        connection.execute(
            """INSERT INTO whatsapp_conversations
               (conversation_key, phone_hash, vendor_id, language, flow, step, state_json,
                invalid_count, updated_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conversation_key) DO UPDATE SET
                   vendor_id=excluded.vendor_id, language=excluded.language,
                   flow=excluded.flow, step=excluded.step, state_json=excluded.state_json,
                   invalid_count=excluded.invalid_count, updated_at=excluded.updated_at,
                   expires_at=excluded.expires_at""",
            (
                conversation["conversation_key"], conversation["phone_hash"],
                conversation.get("vendor_id"), conversation["language"],
                conversation["flow"], conversation["step"], conversation["state_json"],
                conversation.get("invalid_count", 0), conversation["updated_at"],
                conversation["expires_at"],
            ),
        )


def _set(conversation: dict[str, Any], flow: str, step: str, *, invalid_count: int = 0) -> None:
    conversation.update({"flow": flow, "step": step, "invalid_count": invalid_count})


def _profile(vendor_id: str, database_path: str | Path) -> dict[str, Any]:
    profile = get_vendor_profile(vendor_id, database_path=database_path)
    if profile is None:
        raise OperationalNotFoundError("Vendor profile not found")
    return profile


def _public_vendor_id(profile: dict[str, Any]) -> str:
    return profile.get("application_vendor_id") or profile["vendor_id"]


def _menu(profile: dict[str, Any], language: str) -> list[BotMessage]:
    name = profile.get("full_name") or "Vendor"
    heading = f"Hello, {name}\nID: {_public_vendor_id(profile)}\nCategory: {CATEGORY_LABELS[language].get(profile['business_category'], profile['business_category'])}"
    rows = [
        ("menu:1", "1. Current allocation", "Active allocation and live zone status"),
        ("menu:2", "2. Recommendations", "Personalized Top 3 zones"),
        ("menu:3", "3. My requests", "Allocation request history"),
        ("menu:4", "4. Profile", "Profile and preferences"),
        ("menu:5", "5. Language", "English / मराठी / हिन्दी"),
    ]
    return [text_message(heading), list_message(tr("main_menu", language), rows)]


def _ask_language(language: str = "en") -> list[BotMessage]:
    return [button_message(tr("choose_language", language), [("lang:1", "English"), ("lang:2", "मराठी"), ("lang:3", "हिन्दी")])]


def _invalid(conversation: dict[str, Any], language: str) -> list[BotMessage]:
    count = int(conversation.get("invalid_count", 0)) + 1
    conversation["invalid_count"] = count
    messages = [text_message(tr("unknown", language))]
    if count >= 3 and conversation.get("vendor_id"):
        _set(conversation, "MENU", "MAIN")
        messages.extend(_menu(
            _profile(conversation["vendor_id"], conversation.get("_database_path", DATABASE_PATH)),
            language,
        ))
    return messages


@lru_cache(maxsize=1)
def _geometry() -> dict[str, tuple[float, float]]:
    if not GEOMETRY_PATH.exists():
        return {}
    payload = json.loads(GEOMETRY_PATH.read_text(encoding="utf-8"))
    result: dict[str, tuple[float, float]] = {}
    for feature in payload.get("features", []):
        coordinates = (feature.get("geometry") or {}).get("coordinates")
        zone_id = (feature.get("properties") or {}).get("zone_id")
        if zone_id and isinstance(coordinates, list) and len(coordinates) >= 2:
            try:
                result[str(zone_id)] = (float(coordinates[1]), float(coordinates[0]))
            except (TypeError, ValueError):
                continue
    return result


def _recommendations(profile: dict[str, Any], database_path: str | Path) -> list[dict[str, Any]]:
    weights = derive_mcda_weights(profile)["final_weights"]
    engine_vendor_id = "" if profile["vendor_type"] == "NEW" else profile["vendor_id"]
    frame = recommend(
        profile["business_category"], profile.get("preferred_division") or "",
        engine_vendor_id, 3, "", False, use_live_status=True,
        database_path=database_path, factor_weights=weights,
    )
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        raw = row.to_dict()
        factors = sorted(
            explain(raw, weights),
            key=lambda item: float(item.get("contribution") or 0), reverse=True,
        )[:3]
        available = raw.get("available_capacity")
        records.append({
            "rank": int(raw["rank"]), "zone_id": str(raw["zone_id"]),
            "score": round(float(raw["score"]), 1),
            "available_capacity": None if available is None or str(available) == "nan" else int(available),
            "live_status": str(raw.get("live_status") or "UNKNOWN"),
            "factors": [{"label": factor["label"], "summary": factor["summary"]} for factor in factors],
        })
    return records


def _recommendation_messages(records: list[dict[str, Any]], language: str) -> list[BotMessage]:
    if not records:
        empty = {
            "en": "No operationally available zones currently meet your profile.",
            "mr": "सध्या तुमच्या प्रोफाइलशी जुळणारी उपलब्ध क्षेत्रे नाहीत.",
            "hi": "अभी आपकी प्रोफाइल से मेल खाने वाला उपलब्ध क्षेत्र नहीं है।",
        }
        return [text_message(empty[language])]
    lines = [tr("recommendations", language), tr("score_notice", language)]
    rows = []
    for item in records:
        capacity = "unknown" if item["available_capacity"] is None else str(item["available_capacity"])
        lines.append(f"\n{item['rank']}. {item['zone_id']}\nScore: {item['score']:.1f}\nAvailable spaces: {capacity}")
        rows.append((f"recommendation:{item['rank']}", f"{item['rank']}. {item['zone_id']}", f"Score {item['score']:.1f}; available {capacity}"))
    lines.append("\n" + tr("choose_recommendation", language))
    return [list_message("\n".join(lines), rows)]


def _show_allocation(vendor_id: str, language: str, database_path: str | Path) -> list[BotMessage]:
    active = get_vendor_dashboard_activity(vendor_id, database_path)["active_allocation"]
    if not active:
        return [text_message(tr("no_allocation", language))]
    return [text_message(
        "Current allocation\n"
        f"Zone: {active['zone_id']}\nStatus: {active['status']}\n"
        f"Allocated: {active['allocated_at']}\nLive zone status: {active.get('live_zone_status') or 'unknown'}"
    )]


def _show_requests(vendor_id: str, language: str, database_path: str | Path) -> tuple[list[BotMessage], str | None]:
    requests = get_vendor_dashboard_activity(vendor_id, database_path)["requests"][:5]
    if not requests:
        return [text_message(tr("no_requests", language))], None
    lines = ["Latest allocation requests"]
    pending_id = None
    for item in requests:
        status = STATUS_LABELS[language].get(item["status"], item["status"])
        lines.append(
            f"\n{item['zone_id']} — {item['request_type']}\n"
            f"Status: {status}\nSubmitted: {item['created_at'][:10]}"
        )
        if pending_id is None and item["status"] == "PENDING":
            pending_id = item["request_id"]
    if pending_id:
        lines.append("\nReply CANCEL to review cancellation of the pending request.")
    return [text_message("\n".join(lines))], pending_id


def _onboarding_prompt(step: str, language: str) -> list[BotMessage]:
    if step == "LANGUAGE":
        return _ask_language(language)
    if step == "FULL_NAME":
        return [text_message(tr("full_name", language))]
    if step == "CATEGORY":
        rows = [(f"category:{index}", f"{index}. {CATEGORY_LABELS[language][category]}", category) for index, category in CATEGORY_CHOICES.items()]
        return [list_message(tr("category", language), rows)]
    if step == "DIVISION":
        rows = [(f"division:{index}", f"{index}. {division}", "Preferred municipal division") for index, division in enumerate(sorted(valid_divisions()), 1)]
        return [list_message(tr("division", language), rows)]
    if step == "LOCALITY":
        return [text_message(tr("locality", language))]
    if step == "PRIORITY":
        rows = [(f"priority:{index}", f"{index}. {value.title()}", "Recommendation priority") for index, value in PRIORITY_CHOICES.items()]
        return [list_message(tr("priority", language), rows)]
    labels = {"MARKET": "market", "TRANSPORT": "transport", "PARKING": "parking"}
    if step in labels:
        return [button_message(
            tr(labels[step], language),
            [("boolean:1", tr("yes", language)), ("boolean:2", tr("no", language))],
        )]
    return []


def _onboarding_summary(state: dict[str, Any], language: str) -> list[BotMessage]:
    body = (
        "Review your details\n"
        f"Name: {state['full_name']}\n"
        f"Business: {CATEGORY_LABELS[language][state['business_category']]}\n"
        f"Division: {state['preferred_division']}\n"
        f"Locality: {state.get('preferred_locality') or 'Not specified'}\n"
        f"Priority: {state['priority_profile']}\n"
        f"Market / Transport / Parking: {'Yes' if state['market_preference'] else 'No'} / "
        f"{'Yes' if state['transport_preference'] else 'No'} / {'Yes' if state['parking_preference'] else 'No'}"
    )
    return [button_message(body, [("confirm:1", "Confirm"), ("confirm:2", "Edit"), ("confirm:3", "Cancel")])]


def _handle_onboarding(
    conversation: dict[str, Any], state: dict[str, Any], value: str,
    database_path: str | Path,
) -> list[BotMessage]:
    step = conversation["step"]
    language = conversation["language"]
    if step == "LANGUAGE":
        selected = LANGUAGE_CHOICES.get(value)
        if not selected:
            return _invalid(conversation, language)
        conversation["language"] = selected
        state["preferred_language"] = selected
        _set(conversation, "ONBOARDING", "FULL_NAME")
        return _onboarding_prompt("FULL_NAME", selected)
    if step == "FULL_NAME":
        name = value.strip()
        if len(name) < 2 or len(name) > 120 or name.isdigit():
            return [text_message("Enter a valid full name (2–120 characters).")]
        state["full_name"] = name
        _set(conversation, "ONBOARDING", "CATEGORY")
        return _onboarding_prompt("CATEGORY", language)
    if step == "CATEGORY":
        category = CATEGORY_CHOICES.get(value)
        if not category:
            return _invalid(conversation, language)
        state["business_category"] = category
        _set(conversation, "ONBOARDING", "DIVISION")
        return _onboarding_prompt("DIVISION", language)
    if step == "DIVISION":
        divisions = sorted(valid_divisions())
        try:
            division = divisions[int(value) - 1]
        except (ValueError, IndexError):
            return _invalid(conversation, language)
        state["preferred_division"] = division
        _set(conversation, "ONBOARDING", "LOCALITY")
        return _onboarding_prompt("LOCALITY", language)
    if step == "LOCALITY":
        locality = None if value in {"skip", "वगळा", "छोड़ें"} else value.strip()
        if locality and len(locality) > 120:
            return [text_message("Locality must be at most 120 characters.")]
        state["preferred_locality"] = locality
        _set(conversation, "ONBOARDING", "PRIORITY")
        return _onboarding_prompt("PRIORITY", language)
    if step == "PRIORITY":
        priority = PRIORITY_CHOICES.get(value)
        if not priority:
            return _invalid(conversation, language)
        state["priority_profile"] = priority
        _set(conversation, "ONBOARDING", "MARKET")
        return _onboarding_prompt("MARKET", language)
    if step in {"MARKET", "TRANSPORT", "PARKING"}:
        if value not in YES_VALUES | NO_VALUES:
            return _invalid(conversation, language)
        state[f"{step.lower()}_preference"] = value in YES_VALUES
        next_step = {"MARKET": "TRANSPORT", "TRANSPORT": "PARKING", "PARKING": "CONFIRM"}[step]
        _set(conversation, "ONBOARDING", next_step)
        return _onboarding_summary(state, language) if next_step == "CONFIRM" else _onboarding_prompt(next_step, language)
    if step == "CONFIRM":
        if value == "2":
            _set(conversation, "ONBOARDING", "FULL_NAME")
            return [text_message("Let's edit your details from the beginning."), *_onboarding_prompt("FULL_NAME", language)]
        if value == "3":
            state.clear()
            _set(conversation, "ONBOARDING", "LANGUAGE")
            return [text_message(tr("onboarding_cancelled", language)), *_ask_language(language)]
        if value != "1":
            return _invalid(conversation, language)
        profile = register_vendor(state, database_path=database_path)
        bind_verified_phone_hash(conversation["phone_hash"], profile["vendor_id"], database_path)
        conversation["vendor_id"] = profile["vendor_id"]
        conversation["language"] = profile["preferred_language"]
        state.clear()
        _set(conversation, "MENU", "MAIN")
        return [text_message(f"Registration complete. Your Application Vendor ID is {profile['application_vendor_id']}."), *_menu(profile, conversation["language"])]
    return _invalid(conversation, language)


def _profile_menu(profile: dict[str, Any], language: str) -> list[BotMessage]:
    body = (
        f"Profile / preferences\nID: {_public_vendor_id(profile)}\n"
        f"Division: {profile.get('preferred_division') or 'Not set'}\n"
        f"Locality: {profile.get('preferred_locality') or 'Not set'}\n"
        f"Priority: {profile['priority_profile']}\n"
        f"Market / Transport / Parking: {'Yes' if profile['market_preference'] else 'No'} / "
        f"{'Yes' if profile['transport_preference'] else 'No'} / {'Yes' if profile['parking_preference'] else 'No'}"
    )
    rows = [
        ("profile:1", "1. Division", "Change preferred division"),
        ("profile:2", "2. Locality", "Change preferred locality"),
        ("profile:3", "3. Priority", "Change priority profile"),
        ("profile:4", "4. Market", "Toggle market preference"),
        ("profile:5", "5. Transport", "Toggle transport preference"),
        ("profile:6", "6. Parking", "Toggle parking preference"),
        ("profile:7", "7. Language", "Change interface language"),
        ("profile:8", "8. Main menu", "Return"),
    ]
    return [list_message(body, rows)]


def _handle_profile(conversation: dict[str, Any], state: dict[str, Any], value: str, database_path: str | Path) -> list[BotMessage]:
    vendor_id = conversation["vendor_id"]
    language = conversation["language"]
    step = conversation["step"]
    if step == "CHOOSE":
        fields = {"1": "DIVISION", "2": "LOCALITY", "3": "PRIORITY", "4": "MARKET", "5": "TRANSPORT", "6": "PARKING", "7": "LANGUAGE"}
        if value == "8":
            _set(conversation, "MENU", "MAIN")
            return _menu(_profile(vendor_id, database_path), language)
        selected = fields.get(value)
        if not selected:
            return _invalid(conversation, language)
        _set(conversation, "PROFILE", selected)
        if selected == "DIVISION":
            return _onboarding_prompt("DIVISION", language)
        if selected == "LOCALITY":
            return [text_message("Enter the preferred locality, or reply CLEAR.")]
        if selected == "PRIORITY":
            return _onboarding_prompt("PRIORITY", language)
        if selected == "LANGUAGE":
            return _ask_language(language)
        return _onboarding_prompt(selected, language)
    updates: dict[str, Any] = {}
    if step == "DIVISION":
        divisions = sorted(valid_divisions())
        try:
            updates["preferred_division"] = divisions[int(value) - 1]
        except (ValueError, IndexError):
            return _invalid(conversation, language)
    elif step == "LOCALITY":
        updates["preferred_locality"] = None if value == "clear" else value.strip()
    elif step == "PRIORITY":
        if value not in PRIORITY_CHOICES:
            return _invalid(conversation, language)
        updates["priority_profile"] = PRIORITY_CHOICES[value]
    elif step in {"MARKET", "TRANSPORT", "PARKING"}:
        if value not in YES_VALUES | NO_VALUES:
            return _invalid(conversation, language)
        updates[f"{step.lower()}_preference"] = value in YES_VALUES
    elif step == "LANGUAGE":
        selected = LANGUAGE_CHOICES.get(value)
        if not selected:
            return _invalid(conversation, language)
        updates["preferred_language"] = selected
        conversation["language"] = selected
    else:
        return _invalid(conversation, language)
    profile = update_vendor_profile(vendor_id, updates, database_path=database_path)
    _set(conversation, "PROFILE", "CHOOSE")
    return [text_message(tr("profile_updated", conversation["language"])), *_profile_menu(profile, conversation["language"])]


def _handle_known(conversation: dict[str, Any], state: dict[str, Any], value: str, database_path: str | Path) -> list[BotMessage]:
    vendor_id = conversation["vendor_id"]
    language = conversation["language"]
    profile = _profile(vendor_id, database_path)
    flow, step = conversation["flow"], conversation["step"]
    if flow in {"START", "MENU"}:
        if value in START_WORDS:
            _set(conversation, "MENU", "MAIN")
            return _menu(profile, language)
        if value == "1":
            _set(conversation, "MENU", "MAIN")
            return [*_show_allocation(vendor_id, language, database_path), *_menu(profile, language)]
        if value == "2":
            records = _recommendations(profile, database_path)
            state["recommendations"] = records
            _set(conversation, "RECOMMENDATIONS", "CHOOSE")
            return _recommendation_messages(records, language)
        if value == "3":
            messages, pending_id = _show_requests(vendor_id, language, database_path)
            state["pending_request_id"] = pending_id
            _set(conversation, "REQUESTS", "VIEW")
            return messages
        if value == "4":
            _set(conversation, "PROFILE", "CHOOSE")
            return _profile_menu(profile, language)
        if value == "5":
            _set(conversation, "PROFILE", "LANGUAGE")
            return _ask_language(language)
        return _invalid(conversation, language)
    if flow == "PROFILE":
        return _handle_profile(conversation, state, value, database_path)
    if flow == "REQUESTS":
        if step == "VIEW" and value in CANCEL_WORDS and state.get("pending_request_id"):
            _set(conversation, "REQUESTS", "CANCEL_CONFIRM")
            return [button_message("Cancel this pending allocation request?", [("request:1", "Yes, cancel"), ("request:2", "No, keep it")])]
        if step == "CANCEL_CONFIRM":
            if value == "1":
                cancel_allocation_request(state["pending_request_id"], database_path)
                state.pop("pending_request_id", None)
                _set(conversation, "MENU", "MAIN")
                return [text_message(tr("request_cancelled", language)), *_menu(profile, language)]
            if value == "2":
                _set(conversation, "MENU", "MAIN")
                return _menu(profile, language)
        return _invalid(conversation, language)
    if flow == "RECOMMENDATIONS":
        records = state.get("recommendations") or []
        if step == "CHOOSE":
            command = value.split()
            if len(command) == 2 and command[0] in {"why", "map"} and command[1].isdigit():
                item = next((record for record in records if record["rank"] == int(command[1])), None)
                if not item:
                    return _invalid(conversation, language)
                if command[0] == "why":
                    bullets = "\n".join(f"• {factor['label']}: {factor['summary']}" for factor in item["factors"])
                    return [text_message(f"Why {item['zone_id']}?\n{bullets}")]
                coordinates = _geometry().get(item["zone_id"])
                if not coordinates:
                    return [text_message(tr("map_unavailable", language))]
                note = tr("analytical_reference", language)
                return [text_message(note), location_message(coordinates[0], coordinates[1], item["zone_id"], note)]
            try:
                rank = int(value)
            except ValueError:
                return _invalid(conversation, language)
            item = next((record for record in records if record["rank"] == rank), None)
            if not item:
                return _invalid(conversation, language)
            activity = get_vendor_dashboard_activity(vendor_id, database_path)
            pending = next((request for request in activity["requests"] if request["status"] == "PENDING"), None)
            if pending:
                state["pending_request_id"] = pending["request_id"]
                _set(conversation, "REQUESTS", "VIEW")
                return [text_message("You already have a request waiting for NMC review."), text_message("Reply CANCEL to review cancellation, or MENU for the main menu.")]
            state["selected_zone"] = item["zone_id"]
            state["request_type"] = "RELOCATION" if activity["active_allocation"] else "NEW_ALLOCATION"
            _set(conversation, "RECOMMENDATIONS", "CONFIRM_REQUEST")
            notice = "\nYou currently have an active allocation. This will be treated as a relocation request." if state["request_type"] == "RELOCATION" else ""
            return [button_message(f"Selected zone: {item['zone_id']}{notice}\nSubmit request to NMC?", [("confirm:1", "Confirm"), ("confirm:2", "Back")])]
        if step == "CONFIRM_REQUEST":
            if value == "2":
                _set(conversation, "RECOMMENDATIONS", "CHOOSE")
                return _recommendation_messages(records, language)
            if value != "1":
                return _invalid(conversation, language)
            row = create_allocation_request(
                vendor_id, state["selected_zone"], state["request_type"],
                profile["business_category"], profile.get("preferred_division"),
                "Submitted through WhatsApp", database_path,
            )
            _set(conversation, "MENU", "MAIN")
            return [text_message(f"Request submitted for {row['zone_id']}. Status: {row['status']}."), *_menu(profile, language)]
    return _invalid(conversation, language)


def process_incoming_message(
    mobile: str,
    message: str,
    message_id: str,
    *,
    database_path: str | Path = DATABASE_PATH,
) -> ConversationResult:
    """Process one text/interactive input using persistent, idempotent state."""
    normalized = normalize_indian_mobile(mobile)
    hashed_phone = phone_hmac(normalized)
    if not _claim_message(message_id, hashed_phone, database_path):
        return ConversationResult(True, (), "DUPLICATE", "DUPLICATE", None)
    conversation = _load_conversation(hashed_phone, database_path)
    conversation["_database_path"] = database_path
    state = _state(conversation)
    raw_value = (message or "").strip()
    value = _choice(raw_value)
    try:
        language = conversation["language"]
        if value in HELP_WORDS:
            replies = [text_message(tr("help", language))]
        elif value in START_WORDS and conversation.get("vendor_id"):
            _set(conversation, "MENU", "MAIN")
            replies = _menu(_profile(conversation["vendor_id"], database_path), language)
        elif value in MENU_WORDS and not conversation.get("vendor_id"):
            state.clear()
            _set(conversation, "ONBOARDING", "LANGUAGE")
            replies = _ask_language(language)
        elif value in BACK_WORDS and conversation.get("vendor_id"):
            _set(conversation, "MENU", "MAIN")
            replies = _menu(_profile(conversation["vendor_id"], database_path), language)
        elif (
            value in CANCEL_WORDS and conversation.get("vendor_id")
            and conversation["flow"] != "REQUESTS"
        ):
            _set(conversation, "MENU", "MAIN")
            replies = _menu(_profile(conversation["vendor_id"], database_path), language)
        elif value in CANCEL_WORDS and conversation["flow"] == "ONBOARDING":
            state.clear()
            _set(conversation, "ONBOARDING", "LANGUAGE")
            replies = [text_message(tr("onboarding_cancelled", language)), *_ask_language(language)]
        elif conversation.get("vendor_id"):
            if conversation["flow"] == "START" and value not in START_WORDS:
                _set(conversation, "MENU", "MAIN")
            replies = _handle_known(conversation, state, value, database_path)
        else:
            if conversation["flow"] == "START":
                _set(conversation, "ONBOARDING", "LANGUAGE")
                replies = _ask_language(language)
            else:
                replies = _handle_onboarding(conversation, state, raw_value.strip() if conversation["step"] in {"FULL_NAME", "LOCALITY"} else value, database_path)
        _save_conversation(conversation, state, database_path)
        _finish_message(message_id, "PROCESSED", database_path)
        LOGGER.info(
            "WhatsApp processed sender=%s message_id=%s flow=%s step=%s vendor_id=%s",
            _mask_mobile(normalized), message_id, conversation["flow"], conversation["step"],
            conversation.get("vendor_id") or "none",
        )
        return ConversationResult(
            False, tuple(replies), conversation["flow"], conversation["step"],
            conversation.get("vendor_id"),
        )
    except (OperationalConflictError, OperationalNotFoundError, OperationalValidationError) as exc:
        _finish_message(message_id, "PROCESSED", database_path, exc.__class__.__name__)
        safe = str(exc)
        return ConversationResult(False, (text_message(safe),), conversation["flow"], conversation["step"], conversation.get("vendor_id"))
    except Exception as exc:
        _finish_message(message_id, "FAILED", database_path, exc.__class__.__name__)
        LOGGER.exception(
            "WhatsApp processing failed sender=%s message_id=%s flow=%s",
            _mask_mobile(normalized), message_id, conversation.get("flow"),
        )
        raise


def record_ignored_message(
    mobile: str,
    message_id: str,
    *,
    database_path: str | Path = DATABASE_PATH,
) -> bool:
    """Deduplicate and safely acknowledge an unsupported inbound message."""
    normalized = normalize_indian_mobile(mobile)
    hashed_phone = phone_hmac(normalized)
    if not _claim_message(message_id, hashed_phone, database_path):
        return False
    _finish_message(message_id, "IGNORED", database_path)
    LOGGER.info(
        "WhatsApp ignored unsupported message sender=%s message_id=%s",
        _mask_mobile(normalized), message_id,
    )
    return True
