"""Compatibility import; implementation lives in backend.services.navigation."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.services import navigation as implementation
sys.modules[__name__] = implementation
