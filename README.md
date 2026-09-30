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

## Direct Meta WhatsApp Cloud API

The vendor bot uses Meta's WhatsApp Cloud API directly. It does not use Twilio, browser automation, WhatsApp Web, or an unofficial WhatsApp client. Add these values to the project-root `.env` file:

```text
WHATSAPP_ACCESS_TOKEN=<Meta system-user or temporary access token>
WHATSAPP_PHONE_NUMBER_ID=<WhatsApp phone number ID>
WHATSAPP_VERIFY_TOKEN=<private webhook verification token you choose>
META_APP_SECRET=<Meta application secret>
WHATSAPP_GRAPH_VERSION=<supported version such as vNN.N>
```

Never commit real values. The webhook endpoints are:

```text
GET  /api/whatsapp/webhook  # Meta subscription verification
POST /api/whatsapp/webhook  # signed WhatsApp notifications
```

For local deterministic testing without Meta delivery:

```powershell
python backend/whatsapp/simulator.py --mobile 9198XXXXXXXX --message "Hi"
```

The simulator invokes the same persistent conversation service as the webhook and never calls Meta. For duplicate-delivery testing, repeat a command with the same `--message-id`.

Manual Meta Developer Console setup is still required:

1. Create or select a Meta business application and add the WhatsApp product.
2. Add and verify a WhatsApp Business phone number; copy its Phone Number ID.
3. Create an appropriately scoped access token and store it only in `.env` or a deployment secret manager.
4. Expose the backend through public HTTPS and set the callback URL to `https://<host>/api/whatsapp/webhook`.
5. Enter the same private verify token configured in `WHATSAPP_VERIFY_TOKEN` and subscribe the app to message webhook events.
6. Copy the Meta App Secret into deployment secrets for `X-Hub-Signature-256` validation.

Conversation state and inbound-message deduplication are stored in SQLite. Sender numbers are normalized and HMACed using the existing authentication secret; plaintext mobile numbers are not stored in the WhatsApp tables. Historical-vendor recognition requires the privacy-restricted identity seed data to have been initialized securely.

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
