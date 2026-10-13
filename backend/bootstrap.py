"""Ordered, idempotent application database bootstrap."""
from __future__ import annotations

from pathlib import Path

import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.app_config import get_auth_settings
from backend.auth_service import HISTORICAL_VENDOR_SOURCE, seed_historical_vendor_identities
from backend.database import DATABASE_PATH, OFFICIAL_ZONES_PATH, initialize_database


def initialize_application(
    database_path: str | Path = DATABASE_PATH,
    zones_path: str | Path = OFFICIAL_ZONES_PATH,
    historical_vendor_source: str | Path = HISTORICAL_VENDOR_SOURCE,
) -> dict[str, dict]:
    """Load/validate config, upgrade schema, seed zones, then seed auth identities."""
    get_auth_settings()
    database_summary = initialize_database(database_path, zones_path)
    authentication_summary = seed_historical_vendor_identities(
        database_path, historical_vendor_source
    )
    return {
        "database": database_summary,
        "authentication": authentication_summary,
    }
