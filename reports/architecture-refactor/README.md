# Refactor verification

Final local validation:

- Backend: 106 tests passed; one pre-existing Starlette/httpx deprecation warning.
- Frontend: 38 tests passed, including shared API credentials/payload/error checks.
- Vite production build passed.
- `pip check`: no broken requirements.
- Original Uvicorn ASGI import passed: 41 paths; complete OpenAPI unchanged.
- Operational/research recommendation and preference CLI `--help` imports passed.
- Python source parsing and `git diff --check` passed.
- Original data/models/reports SHA-256 guard passed, including SQLite and GIS.
- Scientific function/class AST guard passed, including Goal Programming,
  operational MCDA, preprocessing and clustering. Historical MCDA is separately
  guarded against its original implementation.

The browser runner exercises generation/edit/save, selected-slot persistence,
independent drawers, one-map navigation and drawn provider-route geometry, GPS
stopping/denial, unavailable routing and no assignment. It also checks desktop
1440px and mobile 390px research, registry, portal, login and full officer/vendor
shells. Registry validation asserts populated catalog data rather than merely a
rendered page. Authenticated fixture requests enforce cookie credentials; mobile
shell menu opening/closing is checked. No horizontal page overflow was found.

The 25 PNGs here are captured from real components with browser-only API/GPS
fixtures. Login screenshots show the officer tab; research empty summaries do
not fabricate statistics. Mobile login and full officer shell were visually
inspected, alongside earlier map/profile screenshots during the CSS phase.
Fixtures are never imported by the production entry point. Existing report
artifacts were preserved.

Live OTP delivery, GPS/provider integration and deployment/security/load testing
remain unverified. There is no production-readiness claim.
