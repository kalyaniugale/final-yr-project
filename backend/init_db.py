"""Initialize and seed the operational SQLite database."""
try:
    from .bootstrap import initialize_application
    from .database import DATABASE_PATH
except ImportError:
    from bootstrap import initialize_application
    from database import DATABASE_PATH


def main() -> None:
    bootstrap_summary = initialize_application(DATABASE_PATH)
    summary = bootstrap_summary["database"]
    print("Database initialized")
    print(f"Database: {DATABASE_PATH}")
    print(f"Official zones found: {summary['official_zones']}")
    print(f"Zone live-status rows: {summary['zone_live_status_rows']}")
    print(f"Inserted: {summary['inserted']}")
    print(f"Already existing: {summary['already_existing']}")
    print(f"Application Vendor IDs backfilled: {summary['application_vendor_ids_backfilled']}")
    auth_summary = bootstrap_summary["authentication"]
    if auth_summary["source_available"]:
        print("Historical authentication identities seeded")
    else:
        print("Historical authentication identity seeding skipped: private source not supplied")
    print(f"Seedable mobile mappings: {auth_summary['seedable_numbers']}")
    print(f"Ambiguous mobile mappings skipped: {auth_summary['ambiguous_numbers']}")
    print(f"Identity rows inserted: {auth_summary['inserted']}")
    print(f"Identity rows already existing: {auth_summary['already_existing']}")
    print(f"Total authentication identity rows: {auth_summary['identity_rows']}")


if __name__ == "__main__":
    main()
