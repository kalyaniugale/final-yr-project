# Production readiness audit

Audit date: 10 October 2026. Scope: the actual working tree after architecture
cleanup and the darker palette change. This is a source review and safe local
verification, not a penetration test, municipal certification or deployed-system
assessment. Only this requested report was added; no application fixes,
configuration changes, dependency installations or operational writes were made.
Tests/build regenerated disposable caches/build output. No startup lifespan was
run against the real database, OTP sent, routing provider contacted or deployment
performed. No secret values or vendor records are included here.

**Decision:** suitable for a supervised local demonstration; not ready for a
public launch or actual municipal operations. A controlled internal software
pilot is feasible after the security, backup and deployment gates below. Current
NN_F_013 polygons remain provisional, not authorized ground allocations.

## A. Readiness scorecard

PASS means the stated local check passed, not universal production assurance.

| Area | Status | Evidence and limit |
|---|---|---|
| Architecture | PARTIAL | Feature folders and nine routers exist; compatibility context creates circular import coupling and large legacy modules remain. |
| Security | FAIL | Production configuration can accept development OTP/insecure cookies; officer login lacks throttling. Core ownership and session regressions pass. |
| Database | PARTIAL | Read-only integrity is `ok`, zero FK violations, concurrency/constraint tests pass. No demonstrated backup restoration or versioned migration/rollback process. |
| Backend APIs | PARTIAL | 46 operations across 41 OpenAPI paths; contract guard passes. Public research access, incomplete response schemas and coverage gaps need review. |
| Frontend | PARTIAL | 38 unit tests, Vite build and Edge desktop/mobile smoke pass. Deep-link/back behavior and accessibility remain incomplete. |
| GIS and models | PARTIAL | Metric projection, containment/spacing, deterministic MCDA and protected algorithm checks pass. Ground truth and municipal authorization are unverified. |
| Navigation | PARTIAL | Route normalization/GPS cleanup/error fixtures pass. No server ORS key configured; live GPS/provider/site access NOT VERIFIED. |
| Performance | PARTIAL | Small sequential GET checks and bundle sizes measured; no deployment concurrency, mobile-device or large-data benchmark. |
| Deployment | FAIL | Instructions exist; no executable reverse-proxy/service/deployment/CI setup or verified target environment. |
| Monitoring | FAIL | No application structured logger, readiness dependencies, error tracking or alert configuration found. |
| Privacy and operational compliance | NOT VERIFIED | HMAC/hash storage protects authentication data; no complete consent, retention, privacy or municipal approval evidence found. |

## Verification actually executed

| Check | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **106 passed**, 59.45 seconds; existing Starlette/httpx deprecation warning |
| `npm test` | **38 passed**, including cookie/payload/error tests |
| `npm run build` | Passed, 6.69 seconds |
| `node tests/pilot-browser-smoke.mjs` | Passed: real component desktop/mobile views, registry data, auth/shell menus, slots/edit/save, one-map navigation and error fixtures |
| `python -m pip check` | No broken requirements |
| `npm audit --omit=dev --json` | Zero reported vulnerabilities |
| `npm audit --json` | Zero reported vulnerabilities, including development dependency graph |
| Backend AST parsing | Passed; import and complete OpenAPI checks also exercised by tests |
| SQLite `mode=ro`, `query_only=ON` | `integrity_check=ok`, `foreign_key_check` returned zero rows; journal mode `delete` |
| Original data/model/report hash comparison | All baseline files unchanged |
| Anonymous GET probes, no lifespan | Health/research/status/overview/catalog/geometry: 200; admin overview/vendor dashboard: 401 |

No Python vulnerability scanner result is available: `bandit` and `pip_audit`
are not installed and were not installed for this audit. Manual static searches
covered auth guards, SQL construction, risky execution/deserialization, logging,
timeouts and frontend HTML injection. This is not equivalent to those scanners.
No axe/Lighthouse accessibility scan or Firefox/Safari/device test was performed.
Browser fixtures establish component behavior, not live backend/provider E2E.

Production bundle: entry JS **486.15 kB / 136.01 kB gzip**, shared CSS
**124.39 kB / 28.75 kB gzip**, lazy pilot-map JS **24.58 kB / 8.24 kB gzip**.
Five sequential in-process GET timings, milliseconds:

| Endpoint | Samples | Response size from initial probe |
|---|---|---|
| `/api/catalog` | 130.6, 28.5, 27.7, 29.9, 26.9 | 55,738 bytes |
| `/api/zones/geometry` | 8.3, 6.8, 6.8, 7.1, 7.1 | 53,416 bytes |
| `/api/overview` | 76.5, 71.6, 69.3, 70.2, 73.1 | 429 bytes |

These include TestClient overhead, use local files and are not production latency
targets. No write/load stress test or external API benchmark was run.

## B. Findings by priority

### P0-1 — Production configuration is not fail-closed (confirmed)

**Reference:** [config.py](../../backend/core/config.py:58),
[authentication.py](../../backend/services/authentication.py:181),
[bootstrap.py](../../backend/bootstrap.py:17).
Required presence/boolean checks do not enforce environment names, secret
strength, rejection of example placeholders, secure cookies or development-only
provider restrictions. Local flags are development, insecure cookie, OTP debug
enabled and development provider; these are legitimate local settings but unsafe
to copy into deployment. `APP_ENV=production` does not prohibit insecure cookies
or the development provider. No real SMS provider exists: with production flags
the development provider can accept requests without delivering the OTP.
OTP printing only happens when both development mode and debug are enabled;
there is no confirmed production-mode OTP print leak.

**Impact:** accidental unsafe deployment or vendor authentication unavailable.
**Fix:** production startup validation and a tested delivery adapter; reject
development provider/example secrets in production and require HTTPS cookies.
**Complexity:** low for validation, medium for delivery integration.
**Verify:** isolated configuration matrix tests and sandbox-provider delivery,
failure/retry checks; never send real OTPs without authorization.

### P0-2 — Officer login has no abuse control (confirmed release blocker)

**Reference:** [authentication.py](../../backend/services/authentication.py:315),
[auth.py](../../backend/routers/auth.py:110).
Officer credentials are compared against environment values with `compare_digest`;
there is no attempt limit, backoff or per-IP/account budget. The repository has
no proxy limiter configuration. No password value was examined or disclosed.
No credential compromise was demonstrated.

**Impact:** unrestricted password guessing and login resource abuse if public.
**Fix:** bounded account/IP attempts, generic responses, retry-after handling and
security events; optionally proxy rate limits as a second layer. Keep the single
admin model for a demo; distinct officer identities are needed for accountability.
**Complexity:** low/medium. **Verify:** temporary-db failed-login bursts trigger
429/backoff, successful/recovery paths work and logs omit credentials.

### P0-3 — Geographic authority and production recovery are absent

**Reference:** [pilot_geometry.py](../../backend/geo/pilot_geometry.py:202),
[navigation.py](../../backend/services/navigation.py:21),
[deployment.md](../../docs/deployment.md).
Geometry explicitly says `PROVISIONAL_NOT_SURVEYED`; destination warns that ground
position is unverified. Deployment documentation advises backups, but there is no
implemented backup schedule or demonstrated restore. These are confirmed missing
release evidence, not evidence of bad projection or database corruption.

**Impact:** municipal allocation/navigation cannot safely be treated as physical
permission; loss of the single SQLite file could lose operational history.
**Fix:** restrict software pilot claims, obtain approved/surveyed boundaries and
pedestrian-access review before operational use; implement persistent storage,
consistent backup and restoration rehearsal before storing production records.
**Complexity:** low engineering for backups; external dependency for official review.
**Verify:** independent restored copy matches records/audits; signed site approval
and measured clearance/position checks. Municipal operation remains blocked until
both engineering and official gates are satisfied.

### P1-1 — Onboarding registration and identity binding are separate commits (confirmed)

**Reference:** [vendors router](../../backend/routers/vendors.py:47),
[vendor service](../../backend/services/vendors.py:839),
[authentication.py](../../backend/services/authentication.py:357).
The route commits `register_vendor` before a separate `bind_onboarding_session`
transaction. A bind failure or concurrent use of the same onboarding session can
leave an orphan registration; the happy-path tests do not establish rollback
across both operations.
**Fix:** one domain transaction covering registration, identity and session
conversion, with idempotency/concurrency guard. **Complexity:** medium.
**Verify:** forced binding failure leaves no orphan; two concurrent submissions
for one session produce exactly one registered/bound vendor.

### P1-2 — OTP abuse protection is only per challenge/phone (confirmed)

**Reference:** [authentication.py](../../backend/services/authentication.py:192).
Five-minute expiry, five attempts and 45-second per-phone cooldown exist; consumed
challenges are excluded from cooldown lookup. No rolling daily/global/IP budget
or expired-record purge is implemented. Provider send occurs after challenge
commit. **Impact:** rotating numbers/challenges can consume SMS budgets and grow
storage once real delivery exists. **Fix:** bounded rolling quotas, retention and
explicit delivery failure handling. **Complexity:** medium. **Verify:** quotas,
retries, send failures and cleanup with temporary records/provider mocks.
Existing request responses do not disclose whether a phone belongs to a vendor;
no direct account-enumeration vulnerability was established.

### P1-3 — Anonymous research APIs need a documented exposure policy (confirmed access; privacy risk)

**Reference:** [vendors.py](../../backend/routers/vendors.py:875),
[research.py](../../backend/routers/research.py:24),
[recommendation context](../../backend/services/recommendation_context.py:13).
`/api/vendor/{vendor_id}` returns historical category/division/proposed-zone and
verification fields without a session. This is different from protected
`/api/vendors/{vendor_id}`. Research/status, overview, review-summary and catalog
are also public; recommendations without a vendor ID permit anonymous research
work. Public status can contain model/policy diagnostic details. This may be
intentional research access, but no explicit public data policy was found.
**Impact:** linkable historical vendor information or research diagnostics may be
exposed contrary to operational expectations; anonymous computation can be abused.
**Fix:** classify public aggregate data versus private identifiers, guard/redact
private research routes and bound expensive public work. **Complexity:** low/medium.
**Verify:** anonymous and each-role access matrix, response-field privacy assertions
and generic errors. No names/phones were returned in the report.

### P1-4 — CSRF and browser security posture need deployment-specific validation (confirmed missing controls; exploit not proven)

**Reference:** [security.py](../../backend/core/security.py:206),
[config.py](../../backend/core/config.py:76),
[application.py](../../backend/application.py).
HttpOnly, SameSite=Lax, 12-hour session cookies are present; CORS uses explicit
origins and credentials, rejecting wildcard/path origins. No CSRF token or Origin
validation is implemented on mutations. SameSite and JSON payloads mitigate common
cross-site requests, but CORS is not a standalone CSRF guarantee and same-site
host assumptions matter. No configured CSP/HSTS/security-header proxy exists.
**Fix:** adopt a same-origin deployment and explicit mutation Origin policy or CSRF
tokens; configure HTTPS/security headers at proxy. **Complexity:** low/medium.
**Verify:** hostile-origin, missing-origin and legitimate browser mutation cases,
login/logout behavior and HTTPS cookie/header inspection. Do not call this a
demonstrated CSRF exploit without those tests.

### P1-5 — Startup migration/recovery process is incomplete (confirmed)

**Reference:** [database.py](../../backend/repositories/database.py:340),
[lifecycle.py](../../backend/core/lifecycle.py:8).
Initialization uses additive schema checks and `INSERT OR IGNORE` seeding; tests
show existing vendors/status/slots survive repeated initialization. No DROP/reset
path was found. Restart still writes schema/backfills/seeds and may create an
empty DB when the intended volume is missing. `executescript` can commit a pending
SQLite transaction; the entire schema-upgrade sequence is not proven atomic.
There is no schema-version/release migration ledger or practiced rollback.
**Fix:** explicit production migration/backup step and required-volume validation;
record schema version and migration outcome. **Complexity:** medium.
**Verify:** populated DB upgrade/restart, interrupted upgrade, missing-volume
fail-fast and restore/rollback tests using copies. Live restart was deliberately
not run; safe tests/source review support preservation, not unconditional guarantee.

### P1-6 — Missing deployment, monitoring and Python security verification (confirmed)

**Reference:** [deployment.md](../../docs/deployment.md),
[health.py](../../backend/routers/health.py:10),
[requirements.txt](../../requirements.txt).
No CI pipeline, service supervisor/proxy config, readiness endpoint, structured
application/security logger, error tracking or alert setup was found. Health always
returns ok/research without checking DB/evidence/provider readiness. Requirements
constraints reflect the existing Windows environment; a clean target installation
and Python CVE scan have not been established. Uvicorn access logs alone are not
authentication/error monitoring.
**Fix:** minimal CI tests/build/scans, one supervised service, health/readiness,
redacted logs, disk/backup/uptime alerts and target-environment install check.
**Complexity:** medium. **Verify:** clean deployment, crash restart, dependency scan,
disk/readiness failure and backup alerts without disclosing secrets.

### P1-7 — Access/navigation/privacy review remains incomplete

**Reference:** [pilot map](../../frontend/src/features/pilot-slots/PilotSlotMap.jsx:65),
[navigation hook](../../frontend/src/features/navigation/usePilotNavigation.js:13),
[routing service](../../backend/services/navigation.py:41).
Map slot selection is attached to click handlers; equivalent keyboard-only slot
selection was not demonstrated. Native disclosures and dialog-focus utilities are
present, but no screen-reader/contrast/axe audit exists. Pilot/navigation strings
are largely English despite multilingual portal support. GPS accuracy over 50 m
pauses close-up guidance, but the first fix still initiates a route; the 35 m
endpoint tolerance cannot establish safe access to a 2 m stall. No ORS key is
configured locally. GPS origin is sent to the routing provider on request; no
complete consent/retention/privacy documentation was found.
**Fix:** keyboard/list alternative, translated critical guidance, GPS/provider
consent, documented handling and site-reviewed pedestrian approaches.
**Complexity:** medium plus site verification. **Verify:** keyboard/screen-reader
flows, all languages, actual mobile GPS and sandbox/live routing only when approved.

### P2-1 — Navigation history and session failure recovery

**Reference:** [ImplementationApp.jsx](../../frontend/src/app/ImplementationApp.jsx:42),
[api.js](../../frontend/src/services/api.js).
The shell replaces history for every selection and resets to the role homepage
when checking the session; it does not restore deep links or listen to popstate.
API errors are displayed, but there is no centralized expired-session transition
or fetch timeout/AbortController. **Impact:** refresh/back does not reproduce the
selected page; an unavailable service may hang until browser/network timeout.
**Fix:** small URL-state synchronization and typed status/timeout handling.
**Complexity:** low/medium. **Verify:** refresh/back/forward and expired-session/
offline/slow-response tests with existing tooling.

### P2-2 — Remaining coupling and inconsistent validation

**Reference:** [context.py](../../backend/core/context.py:67),
[api.py](../../backend/api.py), [schemas](../../backend/schemas/api.py).
Context imports security/lifecycle/services which import context back; it works
through deferred bindings but is order-sensitive. Module aliases intentionally
retain patchable test compatibility; bypass defaults false, is not enabled by an
environment variable, and no remotely switchable bypass was found. It still lacks
a production invariant preventing accidental in-process activation. Most auth
strings have no length/format bounds. Several research/pilot handlers lack response
models. Admin `compare_digest` on non-ASCII Python strings can raise TypeError;
schemas allow those strings, so malformed Unicode input can yield 500 instead of
a controlled rejection. Legacy large files/ordered CSS overrides remain.
**Fix:** narrow compatibility bindings gradually, fail if bypass is enabled in
production, bound input and complete important response models/error handling.
**Complexity:** medium. **Verify:** import permutations, configuration/bypass guard,
malformed/oversized/Unicode payloads and complete contract regression.

### P2-3 — Unbounded lists, repeated file work and process-local routing budget

**Reference:** [database.py](../../backend/repositories/database.py:510),
[vendors.py](../../backend/routers/vendors.py:875),
[navigation.py](../../backend/services/navigation.py:55).
Request/allocation lists lack pagination; some endpoints read CSV/JSON per request.
Routing uses a 15-second timeout and a ten-second per-identity limiter, but the
limiter is process-local and clears after 1,000 keys. No global provider quota or
measured large-data budget exists. **Fix:** bounded pagination, measured caching
with evidence invalidation and durable quotas if multiple workers are required.
**Complexity:** low/medium. **Verify:** large synthetic fixture responsiveness,
query plans, bounded responses and quota/failure tests without live-provider stress.

### P3 — Optional later improvements

Add separate officer identities, broader browser/device coverage, richer operator
tools and bundle splitting after measuring need. No evidence requires Next.js,
PostgreSQL, an ORM, Tailwind or a framework migration for this small pilot.

## C. API inventory and test gaps

All 46 operations were inspected through router source and the OpenAPI contract.
Permissions below describe current behavior, not an approved public-access policy.

| Group | Operations and access | Verification/gaps |
|---|---|---|
| Auth (5) | OTP request/verify and officer login public; me session; logout token revoke | Dedicated expiry, attempts, onboarding, role/ownership/login/logout tests. Missing login rate limits, CSRF, delivery failure/production config gates. |
| Vendors (6) | POST vendors onboarding; me dashboard/eligible-zones vendor; GET/PATCH vendors/{id} owner/admin; active-allocation owner/admin | Registry/dashboard/portal/auth tests; missing atomic onboarding failure/concurrency test. |
| Legacy vendor (1) | GET vendor/{id} anonymous historical lookup | No dedicated endpoint privacy/auth regression found. |
| Allocation requests (4) | create owner/admin; list admin; detail/cancel owner/admin | Workflow/invalid status/duplicate/cancellation tests present. |
| Allocation administration (5) | approve/reject admin; allocations list/detail admin; admin overview admin | Approval/rejection/relocation/final-slot concurrency tests present. |
| Allocation plan (1) | POST admin/allocation-plan admin | Optimizer unit guard present; no dedicated route integration/authorization/failure suite found. |
| Pilot (7) | layout/slot read authorized; initialize/slot patch/preview/validate/layout save admin | Isolation, stale edits, locks, geometry and assignment tests present. |
| Navigation (2) | destination/route vendor only | Ownership/provider geometry/failure fixtures present; live provider/GPS unavailable. |
| Recommendations (2) | recommend/sensitivity public when no vendor ID, owner/admin with vendor ID | Recommendation/personalization/capacity tests present; no dedicated sensitivity route suite found. |
| Research (4) | research/status, implementation/summary, overview, review-summary anonymous | Contract/fixture views; no dedicated HTTP response/error/privacy suite found. |
| Zones (8) | live-status read/options/geometry/zone/{id}/official-zones/catalog public; status patch/admin zones admin | Operational status/catalog tests; direct public-zone error/data contracts incompletely tested. |
| Health (1) | public liveness only | GET manually checked; no dependency readiness test. |

Templated URLs are used in existing workflow tests; absence of a literal
`{request_id}` string alone was not treated as missing coverage. Specific gaps
above follow test-function/source searches, not measured line coverage.
HTTP 401/403/404/409/422 are consistently used for common domain errors. Some
unexpected file/provider/config errors can still become 500; no general response
redaction/validation layer exists. Public docs describe schemas but do not encode
cookie security requirements as a full OpenAPI security scheme.

## D. Data, GIS, privacy and deployment assessment

Parameterized SQL is used for supplied values. Dynamic schema SQL uses fixed
internal column definitions; no confirmed SQL injection was found. Foreign keys
are enabled by repository connections. `BEGIN IMMEDIATE`, occupancy checks and
partial unique indexes protect active allocation and demo slot assignments; tests
exercise concurrent final-slot approvals and competing demo assignment. Audit
records exist for workflow/status/slot actions, but login/security audit events,
retention policy and tamper-resistant export are missing.

Projection is WGS84 to UTM 43N with `always_xy=True`; source boundaries are hashed
and invalid shapes rejected instead of silently repaired. Validation covers
containment, spacing, obstruction/corridor intersection, capacity and stale source.
K-Means uses fixed seeds/scaling and retained artifacts. MCDA personalization,
contributions and capacity-aware filtering have regression coverage. Goal
Programming is advisory; approval transactions are authoritative. Original
scientific AST guards pass, but do not establish prediction validity or fairness.
Historical MCDA, operational recommendations, synthetic experiments and municipal
authorization must remain separately described. No model regeneration was run.
Only trusted local joblib artifacts should be loaded; no untrusted upload execution
path was found. Missing evidence flags/coverage remain important decision context.

The browser uses React escaping; no `dangerouslySetInnerHTML` use was found in the
reviewed app. This is not comprehensive XSS assurance. Phone/session/OTP hashes
are stored; privacy risks remain in linkable research data, profile fields,
backups, logs and GPS transmission. No legal compliance determination is made.
Obtain responsible organizational review for consent, privacy, retention, grievance
handling, official data provenance and officer accountability before real use.

| Deployment use | Verdict |
|---|---|
| Supervised local demonstration | **Ready with limits:** development OTP, provisional map and fixture/live distinctions must be explicit. |
| Limited internal software pilot | **Not yet:** close production configuration/rate-limit/backup/atomic onboarding gates and verify restricted deployment. Field allocation remains prohibited without approval. |
| Public internet service | **Not ready:** P0/P1 controls, delivery, privacy, target install/security scans and deployment evidence missing. |
| Actual municipal operations | **Not ready:** all engineering gates plus official geographic, pedestrian and operational authorization required. |

## E. Simple deployment and implementation roadmap

Recommended target: one small VM, a static HTTPS reverse proxy serving Vite `dist`
and forwarding `/api` to one supervised Uvicorn process on loopback, SQLite on a
persistent local disk, restricted file permissions and consistent encrypted off-host
backups. Build with same-origin API configuration; restrict proxy-header trust.
Do not use Vite dev/preview as the production server. This fits a small user base
without new frameworks or enterprise orchestration. Actual sizing/cost is not
measured. SQLite remains suitable for this single-host, low-write-concurrency
design; reconsider only if measured concurrent writes/availability needs require
multiple application hosts. See [SQLite deployment guidance](https://www.sqlite.org/whentouse.html),
[Vite static deployment](https://vite.dev/guide/static-deploy.html), and
[FastAPI HTTPS guidance](https://fastapi.tiangolo.com/deployment/https/).

1. **Release guardrails (small):** enforce production config, disabled bypass/debug,
   secret validation, login/OTP budgets; define approved public/private API matrix.
2. **Identity integrity (medium):** atomic onboarding/idempotency; tested provider
   adapter and quota/delivery failure handling. Add missing route security tests.
3. **Deployment/recovery (medium):** proxy/service config, persistent-volume checks,
   versioned migration step, consistent scheduled backup and restored-copy rehearsal.
4. **Observability/reproducibility (small/medium):** redacted event/error logs,
   readiness/disk/backup alerts, CI tests/build and Python/npm scans; clean install.
5. **Browser/operational safety (medium):** URL restoration/session timeouts,
   keyboard/translation/consent review and authorized live mobile/provider checks.
6. **Municipal gate (external):** approve source boundaries, survey positions and
   pedestrian clearance, assign officers and approve data governance. Until then,
   keep slots and research recommendations explicitly advisory/provisional.
7. **Measured optimization (later):** pagination/caching/bundle changes only after
   representative synthetic-data and deployment measurements.

The audit stops here. No fixes are authorized by this report; implementation
requires the user's approval.
