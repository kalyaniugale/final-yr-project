# Setup and deployment

## Windows development

Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For a new setup only, copy `.env.example` to `.env` and supply real local
configuration. Preserve an existing `.env`. Process environment values take
precedence. Configuration lives in `backend/core/config.py`; compatibility
`backend/app_config.py` remains available. Never expose secrets through Vite
variables or commit `.env`.

Database initialization writes seed/bootstrap state and should be run only when
setting up the application, with backups appropriate to an existing database:

```powershell
python backend/init_db.py
```

The unchanged backend command is:

```powershell
python -m uvicorn api:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In another PowerShell terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Use the same hostname for browser and backend
cookies. Login and role-aware `/admin` and `/vendor` navigation remain unchanged.

## Dependencies and verification

`requirements.txt` remains the compatible complete installation entry point.
It includes app, research and development requirements with constraints captured
from the verified Windows Python 3.13 environment. To install only app packages:

```powershell
python -m pip install -c requirements/constraints.txt -r requirements/app.txt
```

Research packages include scikit-learn, joblib, GeoPandas, matplotlib and
Streamlit. XGBoost remains optional. SciPy and PyProj are now direct declarations.
The constraints snapshot is not proof of a fresh installation on every OS;
validate a clean environment on the deployment target. `npm ci` uses the existing
lockfile. No new frontend dependencies were introduced.

```powershell
python -m pytest -q
python -m pip check
cd frontend
npm test
npm run build
node tests/pilot-browser-smoke.mjs --screenshots
```

The browser smoke runner requires installed Edge (or `EDGE_PATH`) and uses
browser-only API/GPS fixtures. Tests use isolated databases; do not run production
startup or research regeneration as a harmless verification command.

## Deployment requirements

Build frontend static assets with `npm run build`. Serve `frontend/dist` with
HTTPS and SPA fallback. Configure `VITE_API_BASE` at build time to the API origin,
or an empty-path same-origin base such as `/` behind a reverse proxy; without it,
the existing local hostname/port-8000 behavior remains. Set server
`CORS_ORIGINS` to explicit frontend HTTPS origins when cross-origin deployment
is required. Credentials are enabled; wildcard origins are rejected.

Run Uvicorn without `--reload`, initially with one worker, and a persistent
SQLite/data volume. Preserve the existing database path and all GIS/evidence
files. Coordinate writers and make consistent SQLite backups (SQLite backup API
or a stopped application), including any journal files when relevant. Test
restoration before relying on backups.

Set `APP_ENV=production`, stable strong `AUTH_HMAC_SECRET`, strong officer
credentials, `SESSION_COOKIE_SECURE=true`, and `OTP_DEBUG=false` behind HTTPS.
Stable HMAC configuration matters for historical identities. Existing code only
supports the development OTP provider; real delivery requires separate tested
provider integration. Changing environment labels alone does not implement SMS.

`ORS_API_KEY` stays server-side. Browser location requires HTTPS or localhost
and permission. Missing/unavailable routing must retain map-only guidance;
fixtures do not verify live routing. Restrict access to private source vendor
data and operational storage. `/api/health` retains its existing response and
is a liveness endpoint, not a comprehensive dependency readiness probe.

No deployment, live OTP delivery, live GPS/provider availability, load capacity,
external security assessment or disaster recovery exercise was validated by this
cleanup. Those remain release requirements before claiming production readiness.
