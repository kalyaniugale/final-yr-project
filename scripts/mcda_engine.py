"""Compatibility module for the preserved historical MCDA baseline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import mcda_baseline as implementation
sys.modules[__name__] = implementation
if __name__ == "__main__":
    implementation.main()
