# Migration checklist and review

- [x] Read repository and preserve pre-existing uncommitted work.
- [x] Record startup paths, complete OpenAPI and protected asset hashes.
- [x] Capture reversible original source snapshot before extracting modules.
- [x] Baseline: 98 backend tests, 32 frontend tests and Vite build passed.
- [x] Extract routers/schemas/helpers, then move domain/database/GIS modules.
- [x] Keep old Python imports and ASGI startup working through wrappers.
- [x] Distinguish historical MCDA from operational MCDA explicitly.
- [x] Organize frontend features and extract state/maps/tab sections.
- [x] Consolidate authenticated API calls and verify cookie/payload contracts.
- [x] Consolidate CSS in preserved order and verify desktop/mobile screens.
- [x] Remove only reference-checked placeholders, duplicate asset and replaced CSS.
- [x] Separate dependencies and document configuration/startup/deployment.
- [x] Protect original data, databases, GIS, models and reports with hash checks.

Changes were validated incrementally with backend tests, frontend tests, build,
contract comparisons and browser checks. Extraction regressions involving an
import alias, a JSX export and map icon imports were fixed before continuing.
The initial final algorithm guard ran before its baseline file was available;
the baseline was then captured from the original backup and the suite rerun.
The existing Starlette TestClient/httpx deprecation warning is retained rather
than changing working dependencies during the structural cleanup.

The browser fixture mismatch is fixed: the registry uses `/api/catalog`, and
tests now assert a populated table containing `NN_F_013` and absence of its
loading error. Screenshots are review fixtures, not operational evidence.

## Reversibility

No commits or destructive Git operations were performed. Existing uncommitted
work was incorporated rather than reset. The original source snapshot is at
`C:\Users\Darshan\AppData\Local\Temp\nmc-refactor-baseline-sdr7sy_a`.
Move/removal manifests identify changed source paths; no dataset rollback or
database migration is required. Review each logical phase before committing.
Do not blindly restore the whole snapshot over subsequent user work.

Next small phases, only if requested: replace legacy test patch points with
explicit dependency overrides; simplify proven redundant CSS overrides one
screen at a time; add live provider/deployment integration checks; evaluate
URL restoration separately. No framework migration is needed.
