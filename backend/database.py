"""SQLite operational-state storage for the vendor management application.

This module is deliberately independent of the research CSV/ML pipeline.  The
official zone master is used only to seed missing operational status rows.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = ROOT / "data" / "operational" / "vendor_management.db"
OFFICIAL_ZONES_PATH = ROOT / "data" / "raw" / "nmc" / "official_zones.csv"

ZONE_STATUSES = ("OPEN", "FULL", "CLOSED", "SUSPENDED", "RESTRICTED", "NO_VENDING")
REQUEST_TYPES = ("NEW_ALLOCATION", "RELOCATION")
REQUEST_STATUSES = ("PENDING", "APPROVED", "REJECTED", "CANCELLED")
ALLOCATION_STATUSES = ("ACTIVE", "RELEASED")
VENDOR_TYPES = ("NEW", "EXISTING_IMPORTED")
PRIORITY_PROFILES = ("BALANCED", "COMMERCIAL", "ACCESSIBILITY", "FACILITIES")
PREFERRED_LANGUAGES = ("en", "mr", "hi")
VENDOR_STATUSES = ("ACTIVE", "INACTIVE")


SCHEMA = """
CREATE TABLE IF NOT EXISTS operational_vendors (
    vendor_id TEXT PRIMARY KEY,
    application_vendor_id TEXT NULL,
    vendor_type TEXT NOT NULL CHECK (vendor_type IN ('NEW', 'EXISTING_IMPORTED')),
    full_name TEXT NULL,
    business_name TEXT NULL,
    business_category TEXT NOT NULL,
    preferred_division TEXT NULL,
    preferred_locality TEXT NULL,
    priority_profile TEXT NOT NULL DEFAULT 'BALANCED'
        CHECK (priority_profile IN ('BALANCED', 'COMMERCIAL', 'ACCESSIBILITY', 'FACILITIES')),
    parking_preference INTEGER NOT NULL DEFAULT 0 CHECK (parking_preference IN (0, 1)),
    transport_preference INTEGER NOT NULL DEFAULT 0 CHECK (transport_preference IN (0, 1)),
    market_preference INTEGER NOT NULL DEFAULT 0 CHECK (market_preference IN (0, 1)),
    preferred_language TEXT NOT NULL DEFAULT 'en'
        CHECK (preferred_language IN ('en', 'mr', 'hi')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS application_vendor_id_counters (
    year INTEGER PRIMARY KEY,
    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0)
);

CREATE TABLE IF NOT EXISTS zone_live_status (
    zone_id TEXT PRIMARY KEY,
    official_capacity INTEGER NULL CHECK (official_capacity IS NULL OR official_capacity >= 0),
    current_vendor_count INTEGER NOT NULL DEFAULT 0 CHECK (current_vendor_count >= 0),
    available_capacity INTEGER NULL CHECK (available_capacity IS NULL OR available_capacity >= 0),
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'FULL', 'CLOSED', 'SUSPENDED', 'RESTRICTED', 'NO_VENDING')),
    verified_at TEXT NULL,
    verified_by TEXT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (official_capacity IS NULL AND available_capacity IS NULL)
        OR
        (official_capacity IS NOT NULL
         AND current_vendor_count <= official_capacity
         AND available_capacity = official_capacity - current_vendor_count)
    ),
    CHECK (official_capacity IS NULL OR current_vendor_count != official_capacity OR status = 'FULL')
);

CREATE TABLE IF NOT EXISTS allocation_requests (
    request_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    request_type TEXT NOT NULL CHECK (request_type IN ('NEW_ALLOCATION', 'RELOCATION')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')),
    business_category TEXT NULL,
    preferred_division TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT NULL,
    reviewed_by TEXT NULL,
    rejection_reason TEXT NULL,
    notes TEXT NULL,
    FOREIGN KEY (zone_id) REFERENCES zone_live_status(zone_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_pending_request_per_vendor_zone
    ON allocation_requests(vendor_id, zone_id) WHERE status = 'PENDING';

CREATE TABLE IF NOT EXISTS allocations (
    allocation_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    request_id TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED')),
    allocated_at TEXT NOT NULL,
    released_at TEXT NULL,
    approved_by TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (zone_id) REFERENCES zone_live_status(zone_id),
    FOREIGN KEY (request_id) REFERENCES allocation_requests(request_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_allocation_per_vendor
    ON allocations(vendor_id) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS admin_audit_log (
    audit_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    performed_by TEXT NULL,
    details_json TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_auth_identities (
    identity_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    phone_hash TEXT NOT NULL UNIQUE,
    vendor_source TEXT NOT NULL CHECK (vendor_source IN ('HISTORICAL', 'OPERATIONAL')),
    is_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vendor_auth_identities_vendor_id
    ON vendor_auth_identities(vendor_id);

CREATE TABLE IF NOT EXISTS auth_otp_challenges (
    challenge_id TEXT PRIMARY KEY,
    phone_hash TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('VENDOR_LOGIN', 'NEW_VENDOR_REGISTRATION')),
    otp_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
    consumed_at TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_otp_phone_created
    ON auth_otp_challenges(phone_hash, created_at);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    session_token_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('VENDOR', 'ADMIN', 'NEW_VENDOR_ONBOARDING')),
    vendor_id TEXT NULL,
    admin_id TEXT NULL,
    new_vendor_phone_hash TEXT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NULL,
    CHECK (
        (role = 'VENDOR' AND vendor_id IS NOT NULL AND admin_id IS NULL AND new_vendor_phone_hash IS NULL)
        OR (role = 'ADMIN' AND admin_id IS NOT NULL AND vendor_id IS NULL AND new_vendor_phone_hash IS NULL)
        OR (role = 'NEW_VENDOR_ONBOARDING' AND new_vendor_phone_hash IS NOT NULL AND vendor_id IS NULL AND admin_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_active
    ON auth_sessions(session_token_hash, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS whatsapp_conversations (
    conversation_key TEXT PRIMARY KEY,
    phone_hash TEXT NOT NULL UNIQUE,
    vendor_id TEXT NULL,
    language TEXT NOT NULL DEFAULT 'en'
        CHECK (language IN ('en', 'mr', 'hi')),
    flow TEXT NOT NULL DEFAULT 'START',
    step TEXT NOT NULL DEFAULT 'START',
    state_json TEXT NOT NULL DEFAULT '{}',
    invalid_count INTEGER NOT NULL DEFAULT 0 CHECK (invalid_count >= 0),
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_conversations_vendor
    ON whatsapp_conversations(vendor_id);

CREATE TABLE IF NOT EXISTS whatsapp_processed_messages (
    message_id TEXT PRIMARY KEY,
    phone_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PROCESSING'
        CHECK (status IN ('PROCESSING', 'PROCESSED', 'IGNORED', 'FAILED')),
    received_at TEXT NOT NULL,
    processed_at TEXT NULL,
    error_code TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_processed_phone_received
    ON whatsapp_processed_messages(phone_hash, received_at);
"""


def utc_now() -> str:
    """Return a sortable UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OperationalNotFoundError(ValueError):
    """Raised when an operational record does not exist."""


class OperationalConflictError(ValueError):
    """Raised when an operation conflicts with current operational state."""


class OperationalValidationError(ValueError):
    """Raised when an operational command contains an invalid value."""


def connect(database_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    """Open the operational database with row mapping and FK enforcement."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(
    database_path: str | Path = DATABASE_PATH,
    *,
    immediate: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a connection and atomically commit or roll back its work."""
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _read_official_zones(zones_path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with Path(zones_path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"zone_id", "zone_type", "capacity"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Official zone file must contain {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            zone_id = (row.get("zone_id") or "").strip()
            zone_type = (row.get("zone_type") or "").strip().upper()
            if not zone_id or zone_id in seen:
                raise ValueError(f"Missing or duplicate zone_id at line {line_number}")
            if zone_type not in {"FREE", "RESTRICTED", "NO_VENDING"}:
                raise ValueError(f"Unsupported zone_type {zone_type!r} for {zone_id}")
            raw_capacity = (row.get("capacity") or "").strip()
            capacity = None
            if raw_capacity:
                numeric_capacity = float(raw_capacity)
                if numeric_capacity < 0 or not numeric_capacity.is_integer():
                    raise ValueError(f"Invalid capacity {raw_capacity!r} for {zone_id}")
                capacity = int(numeric_capacity)
            rows.append({"zone_id": zone_id, "zone_type": zone_type, "capacity": capacity})
            seen.add(zone_id)
    return rows


APPLICATION_VENDOR_ID_PATTERN = re.compile(r"^NV-(\d{4})-(\d{6})$")


def _application_id_year(created_at: str | None, fallback_year: int) -> int:
    if created_at:
        try:
            year = datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
            if 2000 <= year <= 9999:
                return year
        except (TypeError, ValueError):
            pass
    return fallback_year


def _sync_application_id_counters(connection: sqlite3.Connection) -> None:
    maximum_by_year: dict[int, int] = {}
    rows = connection.execute(
        "SELECT application_vendor_id FROM operational_vendors "
        "WHERE application_vendor_id IS NOT NULL"
    ).fetchall()
    for row in rows:
        match = APPLICATION_VENDOR_ID_PATTERN.fullmatch(row["application_vendor_id"] or "")
        if match:
            year, sequence = map(int, match.groups())
            maximum_by_year[year] = max(maximum_by_year.get(year, 0), sequence)
    for year, sequence in maximum_by_year.items():
        connection.execute(
            """INSERT INTO application_vendor_id_counters (year, last_sequence)
               VALUES (?, ?)
               ON CONFLICT(year) DO UPDATE SET
                   last_sequence = MAX(last_sequence, excluded.last_sequence)""",
            (year, sequence),
        )


def _next_application_vendor_id(connection: sqlite3.Connection, year: int) -> str:
    """Allocate a public ID while the caller holds a BEGIN IMMEDIATE transaction."""
    connection.execute(
        "INSERT OR IGNORE INTO application_vendor_id_counters (year, last_sequence) VALUES (?, 0)",
        (year,),
    )
    connection.execute(
        "UPDATE application_vendor_id_counters SET last_sequence = last_sequence + 1 WHERE year = ?",
        (year,),
    )
    sequence = connection.execute(
        "SELECT last_sequence FROM application_vendor_id_counters WHERE year = ?", (year,)
    ).fetchone()[0]
    return f"NV-{year:04d}-{sequence:06d}"


def initialize_database(
    database_path: str | Path = DATABASE_PATH,
    zones_path: str | Path = OFFICIAL_ZONES_PATH,
) -> dict[str, int]:
    """Create the schema and seed any official zones that are not yet present."""
    zones = _read_official_zones(zones_path)
    inserted = 0
    now = utc_now()
    backfilled_application_ids = 0
    with transaction(database_path, immediate=True) as connection:
        connection.executescript(SCHEMA)
        # SQLite has no portable ADD COLUMN IF NOT EXISTS. Inspect first so this
        # remains safe for databases created before vendor identity was added.
        vendor_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(operational_vendors)")
        }
        if "full_name" not in vendor_columns:
            connection.execute("ALTER TABLE operational_vendors ADD COLUMN full_name TEXT NULL")
        if "business_name" not in vendor_columns:
            connection.execute("ALTER TABLE operational_vendors ADD COLUMN business_name TEXT NULL")
        if "application_vendor_id" not in vendor_columns:
            connection.execute(
                "ALTER TABLE operational_vendors ADD COLUMN application_vendor_id TEXT NULL"
            )
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_operational_vendors_application_vendor_id
               ON operational_vendors(application_vendor_id)
               WHERE application_vendor_id IS NOT NULL"""
        )
        _sync_application_id_counters(connection)
        fallback_year = datetime.now(timezone.utc).year
        missing_ids = connection.execute(
            """SELECT vendor_id, created_at FROM operational_vendors
               WHERE vendor_type = 'NEW'
                 AND (application_vendor_id IS NULL OR TRIM(application_vendor_id) = '')
               ORDER BY created_at, vendor_id"""
        ).fetchall()
        for vendor in missing_ids:
            year = _application_id_year(vendor["created_at"], fallback_year)
            application_vendor_id = _next_application_vendor_id(connection, year)
            connection.execute(
                "UPDATE operational_vendors SET application_vendor_id = ? WHERE vendor_id = ?",
                (application_vendor_id, vendor["vendor_id"]),
            )
            backfilled_application_ids += 1
        for zone in zones:
            initial_status = {
                "FREE": "OPEN",
                "RESTRICTED": "RESTRICTED",
                "NO_VENDING": "NO_VENDING",
            }[zone["zone_type"]]
            capacity = zone["capacity"]
            # A zero-capacity zone has already reached its known capacity.
            if capacity == 0:
                initial_status = "FULL"
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO zone_live_status (
                    zone_id, official_capacity, current_vendor_count,
                    available_capacity, status, updated_at
                ) VALUES (?, ?, 0, ?, ?, ?)
                """,
                (zone["zone_id"], capacity, capacity, initial_status, now),
            )
            inserted += cursor.rowcount
        total_rows = connection.execute("SELECT COUNT(*) FROM zone_live_status").fetchone()[0]
    return {
        "official_zones": len(zones),
        "zone_live_status_rows": total_rows,
        "inserted": inserted,
        "already_existing": len(zones) - inserted,
        "application_vendor_ids_backfilled": backfilled_application_ids,
    }


def _fetch_one(query: str, parameters: tuple[Any, ...], database_path: str | Path):
    connection = connect(database_path)
    try:
        return connection.execute(query, parameters).fetchone()
    finally:
        connection.close()


def get_zone_live_status(zone_id: str, database_path: str | Path = DATABASE_PATH):
    return _fetch_one("SELECT * FROM zone_live_status WHERE zone_id = ?", (zone_id,), database_path)


def list_zone_live_status(
    status: str | None = None,
    database_path: str | Path = DATABASE_PATH,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM zone_live_status"
    parameters: tuple[Any, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        parameters = (status.upper(),)
    query += " ORDER BY zone_id"
    connection = connect(database_path)
    try:
        return connection.execute(query, parameters).fetchall()
    finally:
        connection.close()


def get_live_zone_status_map(
    database_path: str | Path = DATABASE_PATH,
) -> dict[str, dict[str, Any]]:
    """Return every zone's live state with one database query."""
    connection = connect(database_path)
    try:
        rows = connection.execute(
            """SELECT zone_id, official_capacity, current_vendor_count,
                      available_capacity, status, verified_at, verified_by, updated_at
               FROM zone_live_status"""
        ).fetchall()
        return {row["zone_id"]: dict(row) for row in rows}
    finally:
        connection.close()


def get_admin_overview(database_path: str | Path = DATABASE_PATH) -> dict[str, Any]:
    """Aggregate operational counts only; historical associations are excluded."""
    connection = connect(database_path)
    try:
        zone_counts = {status: 0 for status in ZONE_STATUSES}
        zone_counts.update({
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(zone_id) AS count FROM zone_live_status GROUP BY status"
            )
        })
        request_counts = {status: 0 for status in REQUEST_STATUSES}
        request_counts.update({
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(request_id) AS count FROM allocation_requests GROUP BY status"
            )
        })
        allocation_counts = {status: 0 for status in ALLOCATION_STATUSES}
        allocation_counts.update({
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(allocation_id) AS count FROM allocations GROUP BY status"
            )
        })
        total_zones = connection.execute(
            "SELECT COUNT(zone_id) FROM zone_live_status"
        ).fetchone()[0]
        return {
            "total_official_zones": total_zones,
            "zone_status_counts": zone_counts,
            "request_status_counts": request_counts,
            "allocation_status_counts": allocation_counts,
        }
    finally:
        connection.close()


def get_allocation_request(request_id: str, database_path: str | Path = DATABASE_PATH):
    return _fetch_one("SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,), database_path)


def list_allocation_requests(
    status: str | None = None,
    database_path: str | Path = DATABASE_PATH,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM allocation_requests"
    parameters: tuple[Any, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        parameters = (status.upper(),)
    query += " ORDER BY created_at DESC, request_id DESC"
    connection = connect(database_path)
    try:
        return connection.execute(query, parameters).fetchall()
    finally:
        connection.close()


def get_active_allocation_for_vendor(
    vendor_id: str,
    database_path: str | Path = DATABASE_PATH,
):
    return _fetch_one(
        "SELECT * FROM allocations WHERE vendor_id = ? AND status = 'ACTIVE'",
        (vendor_id,),
        database_path,
    )


def get_vendor_dashboard_activity(
    vendor_id: str,
    database_path: str | Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Return only one vendor's allocation and request rows with live zone state."""
    connection = connect(database_path)
    try:
        active = connection.execute(
            """SELECT a.*, r.request_type AS allocation_type,
                      z.status AS live_zone_status, z.official_capacity,
                      z.current_vendor_count, z.available_capacity
               FROM allocations AS a
               LEFT JOIN allocation_requests AS r ON r.request_id = a.request_id
               LEFT JOIN zone_live_status AS z ON z.zone_id = a.zone_id
               WHERE a.vendor_id = ? AND a.status = 'ACTIVE'
               ORDER BY a.allocated_at DESC, a.allocation_id DESC
               LIMIT 1""",
            (vendor_id,),
        ).fetchone()
        requests = connection.execute(
            """SELECT r.*
               FROM allocation_requests AS r
               WHERE r.vendor_id = ?
               ORDER BY r.created_at DESC, r.request_id DESC""",
            (vendor_id,),
        ).fetchall()
        request_ids = [row["request_id"] for row in requests]
        previous_zone_by_request: dict[str, str] = {}
        if request_ids:
            placeholders = ",".join("?" for _ in request_ids)
            audits = connection.execute(
                f"""SELECT entity_id, details_json
                    FROM admin_audit_log
                    WHERE action = 'ALLOCATION_REQUEST_APPROVED'
                      AND entity_id IN ({placeholders})""",
                tuple(request_ids),
            ).fetchall()
            for audit in audits:
                try:
                    details = json.loads(audit["details_json"] or "{}")
                except json.JSONDecodeError:
                    continue
                old_zone_id = details.get("old_zone_id")
                if old_zone_id:
                    previous_zone_by_request[audit["entity_id"]] = old_zone_id
        return {
            "active_allocation": dict(active) if active is not None else None,
            "requests": [dict(row) for row in requests],
            "previous_zone_by_request": previous_zone_by_request,
        }
    finally:
        connection.close()


def get_allocation(allocation_id: str, database_path: str | Path = DATABASE_PATH):
    return _fetch_one("SELECT * FROM allocations WHERE allocation_id = ?", (allocation_id,), database_path)


def list_allocations(
    status: str | None = None,
    database_path: str | Path = DATABASE_PATH,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM allocations"
    parameters: tuple[Any, ...] = ()
    if status is not None:
        normalized_status = status.upper()
        if normalized_status not in ALLOCATION_STATUSES:
            raise OperationalValidationError(
                f"status must be one of: {', '.join(ALLOCATION_STATUSES)}"
            )
        query += " WHERE status = ?"
        parameters = (normalized_status,)
    query += " ORDER BY allocated_at DESC, allocation_id DESC"
    connection = connect(database_path)
    try:
        return connection.execute(query, parameters).fetchall()
    finally:
        connection.close()


def create_allocation_request(
    vendor_id: str,
    zone_id: str,
    request_type: str,
    business_category: str | None = None,
    preferred_division: str | None = None,
    notes: str | None = None,
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Row:
    """Create a pending request after atomically checking operational state."""
    vendor_id = vendor_id.strip()
    zone_id = zone_id.strip()
    request_type = request_type.strip().upper()
    if not vendor_id:
        raise OperationalValidationError("vendor_id must not be empty")
    if request_type not in REQUEST_TYPES:
        raise OperationalValidationError(
            f"request_type must be one of: {', '.join(REQUEST_TYPES)}"
        )

    request_id = f"REQ_{uuid.uuid4().hex}"
    audit_id = f"AUD_{uuid.uuid4().hex}"
    now = utc_now()
    with transaction(database_path) as connection:
        zone = connection.execute(
            "SELECT * FROM zone_live_status WHERE zone_id = ?", (zone_id,)
        ).fetchone()
        if zone is None:
            raise OperationalNotFoundError(f"Unknown zone_id: {zone_id}")
        if zone["official_capacity"] is not None and zone["available_capacity"] <= 0:
            raise OperationalConflictError(f"Zone {zone_id} has no available capacity")
        if zone["status"] != "OPEN":
            raise OperationalConflictError(
                f"Zone {zone_id} is not open for allocation (status: {zone['status']})"
            )

        active_allocation = connection.execute(
            "SELECT allocation_id FROM allocations WHERE vendor_id = ? AND status = 'ACTIVE'",
            (vendor_id,),
        ).fetchone()
        if request_type == "NEW_ALLOCATION" and active_allocation is not None:
            raise OperationalConflictError("Vendor already has an active allocation")
        if request_type == "RELOCATION" and active_allocation is None:
            raise OperationalConflictError("Relocation requires an active allocation")

        duplicate = connection.execute(
            """SELECT request_id FROM allocation_requests
               WHERE vendor_id = ? AND zone_id = ? AND status = 'PENDING'""",
            (vendor_id, zone_id),
        ).fetchone()
        if duplicate is not None:
            raise OperationalConflictError(
                f"Vendor already has a pending request for zone {zone_id}"
            )

        try:
            connection.execute(
                """
                INSERT INTO allocation_requests (
                    request_id, vendor_id, zone_id, request_type, status,
                    business_category, preferred_division, created_at,
                    updated_at, notes
                ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    vendor_id,
                    zone_id,
                    request_type,
                    business_category,
                    preferred_division,
                    now,
                    now,
                    notes,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # The partial unique index closes the race after the explicit,
            # user-friendly duplicate check above.
            if "allocation_requests.vendor_id, allocation_requests.zone_id" in str(exc):
                raise OperationalConflictError(
                    f"Vendor already has a pending request for zone {zone_id}"
                ) from exc
            raise
        details = json.dumps(
            {"vendor_id": vendor_id, "zone_id": zone_id, "request_type": request_type},
            sort_keys=True,
        )
        connection.execute(
            """INSERT INTO admin_audit_log
               (audit_id, action, entity_type, entity_id, performed_by, details_json, created_at)
               VALUES (?, 'ALLOCATION_REQUEST_CREATED', 'allocation_request', ?, NULL, ?, ?)""",
            (audit_id, request_id, details, now),
        )
        return connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()


def cancel_allocation_request(
    request_id: str,
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Row:
    """Cancel a pending request and record the action in the same transaction."""
    now = utc_now()
    audit_id = f"AUD_{uuid.uuid4().hex}"
    with transaction(database_path) as connection:
        request = connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if request is None:
            raise OperationalNotFoundError(f"Unknown allocation request: {request_id}")
        if request["status"] != "PENDING":
            raise OperationalConflictError(
                f"Only PENDING requests can be cancelled (current status: {request['status']})"
            )
        connection.execute(
            """UPDATE allocation_requests
               SET status = 'CANCELLED', updated_at = ?
               WHERE request_id = ?""",
            (now, request_id),
        )
        details = json.dumps(
            {
                "vendor_id": request["vendor_id"],
                "zone_id": request["zone_id"],
                "request_type": request["request_type"],
            },
            sort_keys=True,
        )
        connection.execute(
            """INSERT INTO admin_audit_log
               (audit_id, action, entity_type, entity_id, performed_by, details_json, created_at)
               VALUES (?, 'ALLOCATION_REQUEST_CANCELLED', 'allocation_request', ?, NULL, ?, ?)""",
            (audit_id, request_id, details, now),
        )
        return connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()


@lru_cache(maxsize=4)
def _official_zone_type_map(zones_path: str = str(OFFICIAL_ZONES_PATH)) -> dict[str, str]:
    """Cache immutable policy zone types from the canonical zone master."""
    return {row["zone_id"]: row["zone_type"] for row in _read_official_zones(zones_path)}


def update_zone_live_status(
    zone_id: str,
    requested_status: str,
    verified_by: str,
    database_path: str | Path = DATABASE_PATH,
    zones_path: str | Path = OFFICIAL_ZONES_PATH,
) -> sqlite3.Row:
    """Apply a guarded manual operational status transition for a FREE zone."""
    requested_status = requested_status.strip().upper()
    verified_by = verified_by.strip()
    if requested_status not in {"OPEN", "CLOSED", "SUSPENDED"}:
        raise OperationalValidationError("status must be OPEN, CLOSED, or SUSPENDED")
    if not verified_by:
        raise OperationalValidationError("verified_by must not be empty")
    policy_types = _official_zone_type_map(str(Path(zones_path).resolve()))
    now = utc_now()
    with transaction(database_path, immediate=True) as connection:
        row = connection.execute(
            "SELECT * FROM zone_live_status WHERE zone_id = ?", (zone_id,)
        ).fetchone()
        if row is None:
            raise OperationalNotFoundError(f"Unknown zone_id: {zone_id}")
        policy_type = policy_types.get(zone_id)
        if policy_type != "FREE":
            raise OperationalConflictError(
                f"Policy zone {zone_id} ({policy_type or 'UNKNOWN'}) cannot be changed operationally"
            )
        effective_status = requested_status
        if requested_status == "OPEN" and row["official_capacity"] is not None:
            if row["available_capacity"] <= 0:
                effective_status = "FULL"
        connection.execute(
            """UPDATE zone_live_status
               SET status = ?, verified_at = ?, verified_by = ?, updated_at = ?
               WHERE zone_id = ?""",
            (effective_status, now, verified_by, now, zone_id),
        )
        details = {
            "zone_id": zone_id,
            "policy_zone_type": policy_type,
            "previous_status": row["status"],
            "requested_status": requested_status,
            "effective_status": effective_status,
            "current_vendor_count": row["current_vendor_count"],
            "available_capacity": row["available_capacity"],
        }
        _audit(
            connection,
            "ZONE_LIVE_STATUS_UPDATED",
            "zone",
            zone_id,
            verified_by,
            details,
            now,
        )
        return connection.execute(
            "SELECT * FROM zone_live_status WHERE zone_id = ?", (zone_id,)
        ).fetchone()


def _audit(
    connection: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: str,
    performed_by: str | None,
    details: dict[str, Any],
    created_at: str,
) -> None:
    connection.execute(
        """INSERT INTO admin_audit_log
           (audit_id, action, entity_type, entity_id, performed_by, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            f"AUD_{uuid.uuid4().hex}",
            action,
            entity_type,
            entity_id,
            performed_by,
            json.dumps(details, sort_keys=True),
            created_at,
        ),
    )


def _increment_zone_occupancy(
    connection: sqlite3.Connection,
    zone: sqlite3.Row,
    now: str,
) -> tuple[int, int | None, str]:
    old_count = zone["current_vendor_count"]
    capacity = zone["official_capacity"]
    new_count = old_count + 1
    if capacity is None:
        new_available = None
        new_status = zone["status"]
    else:
        if zone["available_capacity"] <= 0 or new_count > capacity:
            raise OperationalConflictError(f"Zone {zone['zone_id']} has no available capacity")
        new_available = capacity - new_count
        new_status = "FULL" if new_available == 0 else zone["status"]
    connection.execute(
        """UPDATE zone_live_status
           SET current_vendor_count = ?, available_capacity = ?, status = ?, updated_at = ?
           WHERE zone_id = ?""",
        (new_count, new_available, new_status, now, zone["zone_id"]),
    )
    return new_count, new_available, new_status


def _decrement_zone_occupancy(
    connection: sqlite3.Connection,
    zone: sqlite3.Row,
    policy_zone_type: str,
    now: str,
) -> tuple[int, int | None, str]:
    old_count = zone["current_vendor_count"]
    if old_count <= 0:
        raise OperationalConflictError(
            f"Cannot release allocation: zone {zone['zone_id']} occupancy is already zero"
        )
    capacity = zone["official_capacity"]
    new_count = old_count - 1
    new_available = None if capacity is None else capacity - new_count
    new_status = zone["status"]
    if (
        new_status == "FULL"
        and policy_zone_type == "FREE"
        and (new_available is None or new_available > 0)
    ):
        new_status = "OPEN"
    connection.execute(
        """UPDATE zone_live_status
           SET current_vendor_count = ?, available_capacity = ?, status = ?, updated_at = ?
           WHERE zone_id = ?""",
        (new_count, new_available, new_status, now, zone["zone_id"]),
    )
    return new_count, new_available, new_status


def approve_allocation_request(
    request_id: str,
    approved_by: str,
    notes: str | None = None,
    database_path: str | Path = DATABASE_PATH,
    zones_path: str | Path = OFFICIAL_ZONES_PATH,
) -> dict[str, sqlite3.Row | None]:
    """Atomically approve a new allocation or complete a relocation."""
    approved_by = approved_by.strip()
    if not approved_by:
        raise OperationalValidationError("approved_by must not be empty")
    policy_types = _official_zone_type_map(str(Path(zones_path).resolve()))
    now = utc_now()
    allocation_id = f"ALLOC_{uuid.uuid4().hex}"

    # BEGIN IMMEDIATE obtains the SQLite write reservation before any capacity
    # read, serializing competing approvals for a final available slot.
    with transaction(database_path, immediate=True) as connection:
        request = connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if request is None:
            raise OperationalNotFoundError(f"Unknown allocation request: {request_id}")
        if request["status"] != "PENDING":
            raise OperationalConflictError(
                f"Only PENDING requests can be approved (current status: {request['status']})"
            )

        target_zone = connection.execute(
            "SELECT * FROM zone_live_status WHERE zone_id = ?", (request["zone_id"],)
        ).fetchone()
        if target_zone is None:
            raise OperationalNotFoundError(f"Unknown zone_id: {request['zone_id']}")
        if target_zone["official_capacity"] is not None and target_zone["available_capacity"] <= 0:
            raise OperationalConflictError(f"Zone {request['zone_id']} has no available capacity")
        if target_zone["status"] != "OPEN":
            raise OperationalConflictError(
                f"Zone {request['zone_id']} is not open for allocation (status: {target_zone['status']})"
            )

        active = connection.execute(
            "SELECT * FROM allocations WHERE vendor_id = ? AND status = 'ACTIVE'",
            (request["vendor_id"],),
        ).fetchone()
        released_allocation = None
        old_zone_id = None
        if request["request_type"] == "NEW_ALLOCATION":
            if active is not None:
                raise OperationalConflictError("Vendor already has an active allocation")
        elif request["request_type"] == "RELOCATION":
            if active is None:
                raise OperationalConflictError("Relocation requires an active allocation")
            if active["zone_id"] == request["zone_id"]:
                raise OperationalConflictError("Relocation target must differ from the active allocation zone")
            old_zone_id = active["zone_id"]
            old_zone = connection.execute(
                "SELECT * FROM zone_live_status WHERE zone_id = ?", (old_zone_id,)
            ).fetchone()
            if old_zone is None:
                raise OperationalNotFoundError(f"Unknown old allocation zone: {old_zone_id}")
            connection.execute(
                """UPDATE allocations
                   SET status = 'RELEASED', released_at = ?, updated_at = ?
                   WHERE allocation_id = ? AND status = 'ACTIVE'""",
                (now, now, active["allocation_id"]),
            )
            old_count, old_available, old_status = _decrement_zone_occupancy(
                connection,
                old_zone,
                policy_types.get(old_zone_id, ""),
                now,
            )
            released_allocation = connection.execute(
                "SELECT * FROM allocations WHERE allocation_id = ?", (active["allocation_id"],)
            ).fetchone()
            old_details = {
                "request_id": request_id,
                "vendor_id": request["vendor_id"],
                "old_zone_id": old_zone_id,
                "new_zone_id": request["zone_id"],
                "old_count": old_zone["current_vendor_count"],
                "new_count": old_count,
                "available_capacity": old_available,
                "zone_status": old_status,
                "request_type": request["request_type"],
            }
            _audit(
                connection, "ALLOCATION_RELEASED", "allocation", active["allocation_id"],
                approved_by, old_details, now,
            )
            _audit(
                connection, "ZONE_OCCUPANCY_DECREMENTED", "zone", old_zone_id,
                approved_by, old_details, now,
            )
        else:
            raise OperationalValidationError(f"Unsupported request_type: {request['request_type']}")

        connection.execute(
            """INSERT INTO allocations
               (allocation_id, vendor_id, zone_id, request_id, status, allocated_at,
                released_at, approved_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'ACTIVE', ?, NULL, ?, ?, ?)""",
            (
                allocation_id,
                request["vendor_id"],
                request["zone_id"],
                request_id,
                now,
                approved_by,
                now,
                now,
            ),
        )
        new_count, new_available, new_status = _increment_zone_occupancy(
            connection, target_zone, now
        )
        connection.execute(
            """UPDATE allocation_requests
               SET status = 'APPROVED', reviewed_at = ?, reviewed_by = ?,
                   updated_at = ?, notes = COALESCE(?, notes)
               WHERE request_id = ?""",
            (now, approved_by, now, notes, request_id),
        )

        details = {
            "request_id": request_id,
            "vendor_id": request["vendor_id"],
            "zone_id": request["zone_id"],
            "old_zone_id": old_zone_id,
            "old_count": target_zone["current_vendor_count"],
            "new_count": new_count,
            "available_capacity": new_available,
            "zone_status": new_status,
            "request_type": request["request_type"],
        }
        _audit(
            connection, "ALLOCATION_CREATED", "allocation", allocation_id,
            approved_by, details, now,
        )
        _audit(
            connection, "ZONE_OCCUPANCY_INCREMENTED", "zone", request["zone_id"],
            approved_by, details, now,
        )
        _audit(
            connection, "ALLOCATION_REQUEST_APPROVED", "allocation_request", request_id,
            approved_by, details, now,
        )
        approved_request = connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        allocation = connection.execute(
            "SELECT * FROM allocations WHERE allocation_id = ?", (allocation_id,)
        ).fetchone()
        return {
            "request": approved_request,
            "allocation": allocation,
            "released_allocation": released_allocation,
        }


def reject_allocation_request(
    request_id: str,
    reviewed_by: str,
    rejection_reason: str,
    notes: str | None = None,
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Row:
    """Atomically reject a pending allocation request without changing occupancy."""
    reviewed_by = reviewed_by.strip()
    rejection_reason = rejection_reason.strip()
    if not reviewed_by:
        raise OperationalValidationError("reviewed_by must not be empty")
    if not rejection_reason:
        raise OperationalValidationError("rejection_reason must not be empty")
    now = utc_now()
    with transaction(database_path, immediate=True) as connection:
        request = connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if request is None:
            raise OperationalNotFoundError(f"Unknown allocation request: {request_id}")
        if request["status"] != "PENDING":
            raise OperationalConflictError(
                f"Only PENDING requests can be rejected (current status: {request['status']})"
            )
        connection.execute(
            """UPDATE allocation_requests
               SET status = 'REJECTED', reviewed_at = ?, reviewed_by = ?,
                   rejection_reason = ?, updated_at = ?, notes = COALESCE(?, notes)
               WHERE request_id = ?""",
            (now, reviewed_by, rejection_reason, now, notes, request_id),
        )
        details = {
            "request_id": request_id,
            "vendor_id": request["vendor_id"],
            "zone_id": request["zone_id"],
            "request_type": request["request_type"],
        }
        _audit(
            connection, "ALLOCATION_REQUEST_REJECTED", "allocation_request", request_id,
            reviewed_by, details, now,
        )
        return connection.execute(
            "SELECT * FROM allocation_requests WHERE request_id = ?", (request_id,)
        ).fetchone()


def get_operational_vendor(vendor_id: str, database_path: str | Path = DATABASE_PATH):
    return _fetch_one(
        "SELECT * FROM operational_vendors WHERE vendor_id = ?",
        (vendor_id,),
        database_path,
    )


def create_operational_vendor(
    profile: dict[str, Any],
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Row:
    """Register a non-PII operational vendor and write its audit row atomically."""
    now = utc_now()
    vendor_id = f"NV_{uuid.uuid4().hex}"
    with transaction(database_path, immediate=True) as connection:
        application_vendor_id = _next_application_vendor_id(
            connection, _application_id_year(now, datetime.now(timezone.utc).year)
        )
        connection.execute(
            """INSERT INTO operational_vendors (
                   vendor_id, application_vendor_id, vendor_type, full_name, business_name, business_category, preferred_division,
                   preferred_locality, priority_profile, parking_preference,
                   transport_preference, market_preference, preferred_language,
                   status, created_at, updated_at
               ) VALUES (?, ?, 'NEW', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)""",
            (
                vendor_id,
                application_vendor_id,
                profile.get("full_name"),
                profile.get("business_name"),
                profile["business_category"],
                profile.get("preferred_division"),
                profile.get("preferred_locality"),
                profile.get("priority_profile", "BALANCED"),
                int(profile.get("parking_preference", False)),
                int(profile.get("transport_preference", False)),
                int(profile.get("market_preference", False)),
                profile.get("preferred_language", "en"),
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM operational_vendors WHERE vendor_id = ?", (vendor_id,)
        ).fetchone()
        details = {
            key: row[key]
            for key in (
                "vendor_type", "full_name", "business_name", "business_category", "preferred_division",
                "preferred_locality", "priority_profile", "parking_preference",
                "transport_preference", "market_preference", "preferred_language", "status",
            )
        }
        _audit(connection, "VENDOR_REGISTERED", "vendor", vendor_id, None, details, now)
        return row


def save_operational_vendor_profile(
    vendor_id: str,
    vendor_type: str,
    profile: dict[str, Any],
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Row:
    """Update an operational row or create an overlay for a historical vendor."""
    now = utc_now()
    with transaction(database_path, immediate=True) as connection:
        existing = connection.execute(
            "SELECT created_at, application_vendor_id FROM operational_vendors WHERE vendor_id = ?", (vendor_id,)
        ).fetchone()
        created_at = existing["created_at"] if existing is not None else now
        application_vendor_id = existing["application_vendor_id"] if existing is not None else None
        connection.execute(
            """INSERT INTO operational_vendors (
                   vendor_id, application_vendor_id, vendor_type, full_name, business_name, business_category, preferred_division,
                   preferred_locality, priority_profile, parking_preference,
                   transport_preference, market_preference, preferred_language,
                   status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(vendor_id) DO UPDATE SET
                   full_name = excluded.full_name,
                   business_name = excluded.business_name,
                   business_category = excluded.business_category,
                   preferred_division = excluded.preferred_division,
                   preferred_locality = excluded.preferred_locality,
                   priority_profile = excluded.priority_profile,
                   parking_preference = excluded.parking_preference,
                   transport_preference = excluded.transport_preference,
                   market_preference = excluded.market_preference,
                   preferred_language = excluded.preferred_language,
                   status = excluded.status,
                   updated_at = excluded.updated_at""",
            (
                vendor_id,
                application_vendor_id,
                vendor_type,
                profile.get("full_name"),
                profile.get("business_name"),
                profile["business_category"],
                profile.get("preferred_division"),
                profile.get("preferred_locality"),
                profile.get("priority_profile", "BALANCED"),
                int(profile.get("parking_preference", False)),
                int(profile.get("transport_preference", False)),
                int(profile.get("market_preference", False)),
                profile.get("preferred_language", "en"),
                profile.get("status", "ACTIVE"),
                created_at,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM operational_vendors WHERE vendor_id = ?", (vendor_id,)
        ).fetchone()
        details = {
            key: row[key]
            for key in (
                "vendor_type", "full_name", "business_name", "business_category", "preferred_division",
                "preferred_locality", "priority_profile", "parking_preference",
                "transport_preference", "market_preference", "preferred_language", "status",
            )
        }
        _audit(connection, "VENDOR_PROFILE_UPDATED", "vendor", vendor_id, None, details, now)
        return row
