# Nashik Street Vendor Management & Zoning Platform

React, FastAPI, and SQLite decision-support application with separate authenticated vendor and NMC officer workspaces. The research recommendation engine remains weighted MCDA with the existing K-Means environmental features.

## Authentication configuration

Copy `.env.example` to `.env` in the repository root and configure its values. Do not commit the resulting secrets. The backend resolves this file from `backend/app_config.py`, so both Uvicorn and direct scripts load the same configuration regardless of the current working directory. Values already defined in the process environment take precedence over `.env`.

```text
APP_ENV=development
AUTH_HMAC_SECRET=<long random secret>
SESSION_COOKIE_SECURE=false
OTP_PROVIDER=development
OTP_DEBUG=true
NMC_ADMIN_USERNAME=<officer username>
NMC_ADMIN_PASSWORD=<strong local password>
```

`AUTH_HMAC_SECRET` must remain stable after historical identities are seeded. Use `SESSION_COOKIE_SECURE=true` behind production HTTPS. `OTP_DEBUG=true` is strictly for local development: it prints the OTP code, but never the phone number. The API never returns an OTP.

## Initialize operational and authentication data

From the repository root, create a virtual environment and install the Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Then, after configuring the environment, initialize the local database:

```powershell
python backend/init_db.py
```

Initialization is idempotent. It preserves operational vendors, allocation requests, allocations, zone state, and audit history. When the privacy-restricted `data/raw/nmc/vendors.csv` is supplied separately, initialization normalizes valid `phone_number` and `alternate_phone` values and seeds only unambiguous HMAC mappings. The CSV is intentionally excluded from Git; plaintext phone numbers are not copied into SQLite or model files.

FastAPI runs the same ordered bootstrap at application startup as a safety check. Running `init_db.py` explicitly remains useful for a visible initialization summary.

## Run locally

Backend:

```powershell
python -m uvicorn api:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Unauthenticated visitors enter through `/login`; server sessions determine whether the application shows `/vendor` or `/admin` experiences.

## Roles and privacy

- `VENDOR`: accesses only the authenticated vendor profile, recommendations, and that vendor's requests.
- `NEW_VENDOR_ONBOARDING`: can complete one verified operational profile registration.
- `ADMIN`: accesses the NMC dashboard and administrative actions.

Sessions use an HttpOnly, SameSite=Lax cookie. SQLite stores only hashes of session tokens and OTPs. Historical and newly verified phone identities use HMAC values. Admin credentials come from environment configuration and are never stored in the database. Frontend visibility is not trusted for authorization; protected API endpoints enforce roles and ownership server-side.

## Tests and build

```powershell
pytest
cd frontend
npm test -- --run
npm run build
```

Tests use isolated temporary databases and an explicit test-only authorization bypass for legacy workflow coverage. Dedicated authentication tests run with that bypass disabled.

## Model integrity

Authentication does not modify K-Means, MCDA weights, personalization multipliers, live-capacity rules, or allocation business logic. Historical vendor associations are evidence only and are never treated as current occupancy. Map points remain analytical references, not legal zone boundaries.
