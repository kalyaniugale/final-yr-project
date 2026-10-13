"""Compatibility import; implementation lives in backend.geo.pilot_geometry."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.geo import pilot_geometry as implementation
sys.modules[__name__] = implementation
