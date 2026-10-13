"""Compatible ASGI entry point: uvicorn api:app --app-dir backend.

The module alias retains existing Python/test configuration hooks while all
HTTP handlers live in routers. New code imports their owning modules directly.
"""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.application import app
from backend.core import context
# Preserve legacy bare imports without selecting an engine through sys.path.
from importlib import import_module
for legacy, canonical in {
    "database": "backend.repositories.database",
    "auth_service": "backend.services.authentication",
    "app_config": "backend.core.config",
    "pilot_slots": "backend.services.pilot_slots",
    "pilot_geometry": "backend.geo.pilot_geometry",
    "pilot_navigation": "backend.services.navigation",
    "vendor_service": "backend.services.vendors",
}.items():
    sys.modules.setdefault(legacy, import_module(canonical))
sys.modules[__name__] = context
