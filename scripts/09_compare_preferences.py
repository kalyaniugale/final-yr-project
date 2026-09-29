"""Compare deterministic MCDA preference profiles without mutating application data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import DATABASE_PATH  # noqa: E402
from mcda_engine import derive_mcda_weights, recommend  # noqa: E402


PROFILES = {
    "BALANCED": {
        "priority_profile": "BALANCED",
        "market_preference": False,
        "transport_preference": False,
        "parking_preference": False,
    },
    "COMMERCIAL + market": {
        "priority_profile": "COMMERCIAL",
        "market_preference": True,
        "transport_preference": False,
        "parking_preference": False,
    },
    "ACCESSIBILITY + transport": {
        "priority_profile": "ACCESSIBILITY",
        "market_preference": False,
        "transport_preference": True,
        "parking_preference": False,
    },
    "FACILITIES + parking": {
        "priority_profile": "FACILITIES",
        "market_preference": False,
        "transport_preference": False,
        "parking_preference": True,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business", default="food")
    parser.add_argument("--division", default="Nashik West")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument(
        "--static",
        action="store_true",
        help="Skip operational live filtering while retaining profile comparison",
    )
    args = parser.parse_args()

    print(f"Business: {args.business}")
    print(f"Division: {args.division}")
    print(f"Mode: {'static research' if args.static else 'live operational (read-only)'}")
    for label, profile in PROFILES.items():
        derived = derive_mcda_weights(profile)
        result = recommend(
            args.business,
            division=args.division,
            top_n=args.top_n,
            use_live_status=not args.static,
            database_path=DATABASE_PATH,
            factor_weights=derived["final_weights"],
        )
        weights = ", ".join(
            f"{name}={value:.6f}" for name, value in derived["final_weights"].items()
        )
        ranking = ", ".join(
            f"{row.zone_id} ({row.score:.6f})" for _, row in result.iterrows()
        ) or "No eligible zones"
        print(f"\nProfile: {label}")
        print(f"Effective weights: {weights}")
        print(f"Top {args.top_n}: {ranking}")


if __name__ == "__main__":
    main()
