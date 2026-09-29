"""Unified non-PII vendor profiles across SQLite and historical research data."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .database import (
        DATABASE_PATH,
        PREFERRED_LANGUAGES,
        PRIORITY_PROFILES,
        OperationalNotFoundError,
        OperationalValidationError,
        create_operational_vendor,
        get_operational_vendor,
        save_operational_vendor_profile,
    )
    from .mcda_engine import CATEGORIES, DATA
except ImportError:
    from database import (
        DATABASE_PATH,
        PREFERRED_LANGUAGES,
        PRIORITY_PROFILES,
        OperationalNotFoundError,
        OperationalValidationError,
        create_operational_vendor,
        get_operational_vendor,
        save_operational_vendor_profile,
    )
    from mcda_engine import CATEGORIES, DATA


HISTORICAL_VENDOR_PATH = DATA / "vendor_training_registry.csv"
HISTORICAL_IDENTITY_PATH = DATA.parent / "raw" / "nmc" / "vendors.csv"
CANDIDATE_ZONE_PATH = DATA / "candidate_zone_snapshot.csv"
EDITABLE_PROFILE_FIELDS = {
    "full_name",
    "business_name",
    "business_category",
    "preferred_division",
    "preferred_locality",
    "priority_profile",
    "parking_preference",
    "transport_preference",
    "market_preference",
    "preferred_language",
}

@lru_cache(maxsize=2)
def _historical_identity_map(path: str = str(HISTORICAL_IDENTITY_PATH)) -> dict[str, dict[str, str | None]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        return {
            row["vendor_id"]: {
                "full_name": (row.get("vendor_name_english") or "").strip() or None,
                # The source has a business type, but no distinct stall/trade-name field.
                "business_name": None,
            }
            for row in csv.DictReader(source)
        }


@lru_cache(maxsize=4)
def _historical_vendor_map(path: str = str(HISTORICAL_VENDOR_PATH)) -> dict[str, dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        return {
            row["vendor_id"]: {
                "business_category": row["business_category"],
                "preferred_division": row["vendor_division"] or None,
            }
            for row in csv.DictReader(source)
        }


@lru_cache(maxsize=4)
def valid_divisions(path: str = str(CANDIDATE_ZONE_PATH)) -> frozenset[str]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        return frozenset(
            row["zone_division"]
            for row in csv.DictReader(source)
            if row.get("zone_division") and row["zone_division"] != "Citywide"
        )


def _normalize_operational(row) -> dict[str, Any]:
    return {
        "vendor_id": row["vendor_id"],
        "application_vendor_id": row["application_vendor_id"],
        "vendor_type": row["vendor_type"],
        "full_name": row["full_name"],
        "business_name": row["business_name"],
        "business_category": row["business_category"],
        "preferred_division": row["preferred_division"],
        "preferred_locality": row["preferred_locality"],
        "priority_profile": row["priority_profile"],
        "parking_preference": bool(row["parking_preference"]),
        "transport_preference": bool(row["transport_preference"]),
        "market_preference": bool(row["market_preference"]),
        "preferred_language": row["preferred_language"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _historical_profile(vendor_id: str, historical_path: str | Path) -> dict[str, Any] | None:
    source = _historical_vendor_map(str(Path(historical_path).resolve())).get(vendor_id)
    if source is None:
        return None
    identity = _historical_identity_map().get(vendor_id, {})
    return {
        "vendor_id": vendor_id,
        "application_vendor_id": None,
        "vendor_type": "EXISTING_IMPORTED",
        "full_name": identity.get("full_name"),
        "business_name": identity.get("business_name"),
        "business_category": source["business_category"],
        "preferred_division": source["preferred_division"],
        "preferred_locality": None,
        "priority_profile": "BALANCED",
        "parking_preference": False,
        "transport_preference": False,
        "market_preference": False,
        "preferred_language": "en",
        "status": "ACTIVE",
        "created_at": None,
        "updated_at": None,
    }


def validate_vendor_profile(values: dict[str, Any], *, partial: bool = False) -> None:
    for field, maximum in (("full_name", 120), ("business_name", 120)):
        if field in values and values[field] is not None:
            value = values[field].strip() if isinstance(values[field], str) else ""
            if not value:
                raise OperationalValidationError(f"{field} must not be empty")
            if len(value) > maximum:
                raise OperationalValidationError(f"{field} must be at most {maximum} characters")
            values[field] = value
    if not partial or "business_category" in values:
        category = values.get("business_category")
        if category not in CATEGORIES:
            raise OperationalValidationError(
                f"business_category must be one of: {', '.join(CATEGORIES)}"
            )
    if "preferred_division" in values and values["preferred_division"] is not None:
        if values["preferred_division"] not in valid_divisions():
            raise OperationalValidationError("Unknown preferred_division")
    if "priority_profile" in values and values["priority_profile"] not in PRIORITY_PROFILES:
        raise OperationalValidationError(
            f"priority_profile must be one of: {', '.join(PRIORITY_PROFILES)}"
        )
    if "preferred_language" in values and values["preferred_language"] not in PREFERRED_LANGUAGES:
        raise OperationalValidationError(
            f"preferred_language must be one of: {', '.join(PREFERRED_LANGUAGES)}"
        )
    for field in ("parking_preference", "transport_preference", "market_preference"):
        if field in values and not isinstance(values[field], bool):
            raise OperationalValidationError(f"{field} must be a boolean")


def get_vendor_profile(
    vendor_id: str,
    database_path: str | Path = DATABASE_PATH,
    historical_path: str | Path = HISTORICAL_VENDOR_PATH,
) -> dict[str, Any] | None:
    """Resolve an operational row first, then the immutable historical source."""
    operational = get_operational_vendor(vendor_id, database_path)
    if operational is not None:
        return _normalize_operational(operational)
    return _historical_profile(vendor_id, historical_path)


def register_vendor(
    values: dict[str, Any],
    database_path: str | Path = DATABASE_PATH,
) -> dict[str, Any]:
    validate_vendor_profile(values)
    return _normalize_operational(create_operational_vendor(values, database_path))


def update_vendor_profile(
    vendor_id: str,
    updates: dict[str, Any],
    database_path: str | Path = DATABASE_PATH,
    historical_path: str | Path = HISTORICAL_VENDOR_PATH,
) -> dict[str, Any]:
    if not updates:
        raise OperationalValidationError("At least one preference field must be supplied")
    unknown = set(updates) - EDITABLE_PROFILE_FIELDS
    if unknown:
        raise OperationalValidationError(f"Fields cannot be updated: {', '.join(sorted(unknown))}")
    validate_vendor_profile(updates, partial=True)
    current = get_vendor_profile(vendor_id, database_path, historical_path)
    if current is None:
        raise OperationalNotFoundError(f"Unknown vendor_id: {vendor_id}")
    merged = {**current, **updates}
    row = save_operational_vendor_profile(
        vendor_id,
        current["vendor_type"],
        merged,
        database_path,
    )
    return _normalize_operational(row)
