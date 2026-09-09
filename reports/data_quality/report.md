# Nashik ML — Data quality report

Generated: 2026-09-09T13:52:54.821777+00:00

Blocking errors: 0
Warnings: 1

## Summary
- official_zones.csv: 308 records
- vendors.csv: 7,259 records
- vendor_zone_assignments.csv: 7,259 records
- zone_vendor_evidence.csv: 308 records
- location_zone_crosswalk.csv: 528 records
- business_translation_audit.csv: 599 records
- Usable reference geometries: 258

## Issues
- **WARNING — BUSINESS_REVIEW**: Unresolved English business categories (174)
- **INFO — HISTORICAL_LEGAL_STATUS**: 1517 historical proposals reference RESTRICTED zones; do not treat as eligible allocation. (1517)
- **INFO — DATA_SEMANTICS**: Historical proposed associations are not verified allocations, demand, sales, or live occupancy.
- **INFO — GEOMETRY_SEMANTICS**: Reference geometry is not an authoritative legal boundary or measured vending area.
- **INFO — LABEL_REQUIREMENT**: Supervised accuracy and ranking metrics require independent outcomes or expert relevance labels.

## Interpretation
No source files were modified. Errors block dependable feature engineering.
Warnings require investigation but do not automatically block exploratory work.
Counts are computed from the present files, not hard-coded historical totals.
The full input SHA-256 manifest makes this run reproducible.
Reference geometry and historical associations must not be presented as legally verified or current occupancy.
Training labels, model performance and suitability accuracy are not established by this audit.
