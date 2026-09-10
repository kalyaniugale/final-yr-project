# WhatsApp recommendation bot — Review 2

Separate FastAPI service; the existing recommendation backend remains the only
ranking authority. No LLM, registration, booking, allocation or identity checks.
English, Marathi and Hindi use fixed menus and evidence templates. Official place
descriptions and division names retain the backend's original language.

## Install and run

Prerequisites: Python 3.11+, the existing processed data/reference audit files,
internet access for Meta, a Meta developer app with WhatsApp development resources,
and an allowed test recipient. Use Meta's development number for this demo;
production business verification is not a prerequisite of this local implementation.

From the repository root:

```bash
source .venv/bin/activate
python -m pip install -r backend/whatsapp/requirements.txt
# These are needed by the existing backend if not installed already:
python -m pip install numpy pandas
```

Terminal 1 — existing backend:

```bash
source .venv/bin/activate
python -m uvicorn api:app --app-dir backend --host 127.0.0.1 --port 8000
```

Confirm `http://127.0.0.1:8000/api/options` returns categories and divisions.

Terminal 2 — bot:

1. Copy `backend/whatsapp/.env.example` to `backend/whatsapp/.env` locally.
2. Fill in your credentials; never commit this file. No real `.env` is supplied.
3. Export the variables and start **one worker**:

```bash
source .venv/bin/activate
set -a
source backend/whatsapp/.env
set +a
python -m uvicorn backend.whatsapp.webhook:app --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

The `.env` is shell-sourced, not automatically loaded. Quote values if needed;
only source a file you created. Disabling access logs prevents the webhook GET
verification token from appearing in request-query logs. Apply equivalent query
redaction to any proxy/tunnel logging. Avoid HTTP debug logging.

## Configuration

| Variable | Meaning |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Meta access token; temporary development tokens expire |
| `WHATSAPP_PHONE_NUMBER_ID` | Numeric Phone Number ID, not the display phone number or WABA ID |
| `WHATSAPP_VERIFY_TOKEN` | Private string you choose, also entered in webhook setup |
| `META_APP_SECRET` | App secret used to verify POST HMAC signatures |
| `GRAPH_API_VERSION` | Required supported version from your app dashboard, including `v`; no version is assumed |
| `RECOMMENDATION_BASE_URL` | Default `http://127.0.0.1:8000`; set an internal reachable URL for separate hosts/containers |
| `WHATSAPP_DB_PATH` | Default `backend/whatsapp/sessions.sqlite3`; relative to working directory |
| `SESSION_TTL_SECONDS` | Default 86400 seconds of session inactivity |
| `HTTP_TIMEOUT_SECONDS` | Default 15 seconds per HTTP operation |

Keep the database on a private local disk. It contains sender IDs and recommendation
snapshots. For local testing `WHATSAPP_DB_PATH=:memory:` works but resets on restart.
The service fails startup if required credentials/configuration are absent.

## Meta and tunnel setup

Use the [Meta Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api)
and your app's WhatsApp API Setup/Getting Started panel for the development token,
test number and Phone Number ID. Add and verify your intended test recipient there.
Dashboard labels may vary.

With ngrok installed and authenticated, run in another terminal:

```bash
ngrok http 8001
```

In your app's WhatsApp webhook configuration:

1. Set callback URL to `https://YOUR-TUNNEL-HOST/webhook`.
2. Set verify token to the exact `WHATSAPP_VERIFY_TOKEN` value.
3. Verify and save. The GET handler returns `hub.challenge` only for a matching
   token and `hub.mode=subscribe`.
4. Subscribe to the **messages** webhook field and ensure the app is subscribed
   to the relevant WhatsApp Business Account. A successful verification alone
   does not establish message subscription.
5. From your allowed test recipient's WhatsApp, send **Hi** to the Meta development
   number. Choose language → Find location → vendor type → category → division.
6. Select a returned result and try each explanation/map action.

The signature uses `X-Hub-Signature-256`, HMAC-SHA256 of the exact request body,
and the Meta app secret. Missing or invalid signatures return 403. Do not disable
signature checking for a public tunnel. This behavior follows
[Meta's webhook documentation](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/).

Only expose port 8001 through the tunnel; the recommendation backend can remain
local. If the tunnel hostname changes, update the callback. No tunnel or Meta
subscription is created automatically by this repository.

## Conversation and API contract

`Hi`, `hello`, `start`, `restart`, `menu`, `language`, `नमस्ते`, or `नमस्कार`
starts a fresh language menu. Buttons use canonical IDs, not translated labels.
Expired sessions restart at language selection. Unsupported input receives a menu
hint; media is not downloaded.

Both new and existing/relocation flows ask business and division manually. Existing
mode adds a notice; it does not verify registration or infer a current location.
Both send:

```json
{
  "business": "food",
  "division": "",
  "vendor_id": "",
  "exclude_zone": "",
  "top_n": 3,
  "require_verified": false
}
```

Categories and divisions come from `GET /api/options`. Category translations only
label supported canonical values. Unknown future category codes are not offered
until translations are added. Tea/snacks/beverages all map to `food`; flowers map
to `flower`. “Any division” sends the empty string. Division menus paginate if needed.

`POST /api/recommendations` records are stored unchanged in the session. Zone buttons
include a result-snapshot identifier; view buttons also bind to the selected zone.
Stale buttons cannot silently select a new snapshot or another zone. Selecting a
result never reruns ranking. Zero/fewer-than-three results and API failures have
explicit responses; no synthetic candidates are generated.

Map lookup calls `GET /api/zones/geometry`, matches `properties.zone_id`, requires a
valid Point and converts `[longitude, latitude]` to the location payload. Invalid or
missing coordinates produce text only. Shared references and approximate-location
warnings accompany map pins.

Simple views use fixed templates and real GIS/history fields. Detailed English
views also display the backend's summary, details and evidence; Marathi/Hindi use
fixed equivalents and the same numerical metrics. Null remains unknown. Factor
contributions are base weighted points: `overall = sum(contributions)/score_coverage`.
No SHAP or success-prediction claims are made.

## Modules and persistence

* `webhook.py`: signature/verification, message parsing, durable enqueue, worker.
* `conversation.py`: deterministic state transitions and snapshot selection.
* `messages.py`, `translations.py`: payloads and fixed multilingual presentation.
* `recommendation_client.py`: existing backend HTTP adapter and response checks.
* `meta_client.py`: configured Graph API transport with redacted error logging.
* `session_store.py`: SQLite sessions, deduplication and outgoing progress.
* `config.py`: environment configuration.

The webhook commits events before acknowledging them. A single background worker
processes sender events in order; backend and outgoing requests do not delay webhook
acknowledgment. Session changes and outgoing batches commit atomically. Successful
outgoing messages are checkpointed so ordinary retries resume the remaining batch.
Duplicate incoming message IDs are ignored for seven days, including after restart.
Sessions expire after the configured inactivity period. Pending batches older than
that period are discarded, and completed events retain only deduplication metadata.
SQLite deletion is logical cleanup, not a secure-erasure guarantee for disk backups.

Transient transport/429/5xx failures retry with bounded backoff, up to five failures
per unsent message. Permanent Meta errors mark the batch failed and log only HTTP
status; the user can send `menu` again after configuration is corrected. Status-only
webhooks are acknowledged but do not change conversation state.

## Tests

```bash
.venv/bin/python -B -m unittest discover -s backend/whatsapp/tests -v
```

Tests use HTTP mocks, in-process ASGI and temporary SQLite databases. They never send
real WhatsApp messages and require no Meta credentials. Coverage includes verification,
HMAC, text/interactive parsing, all languages, both vendor modes, category/division
mapping, exact request payload, 0–3 results, snapshot views, map order/missing points,
errors/timeouts, persistence, expiry and duplicate/retry handling.

## Limitations and troubleshooting

* **One process / one worker only.** SQLite persists data, but this worker design is
  not safe for multiple concurrent service instances. Throughput is suitable for a
  local demo, not a production multi-worker deployment.
* Outgoing delivery is not exactly-once: a network timeout or crash after Meta accepts
  a message but before its checkpoint can cause a duplicate on retry. Inbound dedup
  does not eliminate this external-delivery ambiguity.
* This is a user-initiated demo; it does not send proactive templates or manage
  messaging-window reopening. Send a fresh `Hi` when testing after a long pause.
* API success means accepted for sending, not proven handset delivery. Status events
  are safely ignored; delivery analytics are not implemented.
* There is no phone-to-registry linkage, secure vendor-ID lookup, allocation or live
  vacancy guarantee. Historical counts are not occupancy. Map points are not official
  boundaries or exact stalls. Existing data restrictions remain in the backend.
* Fixed Marathi/Hindi wording needs a native-speaker usability review before wider
  deployment; official descriptions remain in their original language.
* If Meta returns 401/403, check token expiry and permissions locally. If webhook GET
  fails, compare verify tokens. If POST returns 403, check the app secret and ensure
  proxies preserve the raw body. Never paste credentials into logs or issue reports.
* Backend unavailable: verify port 8000 and `/api/options`; root `requirements.txt`
  remains empty, so use the explicit installation commands above.
* Live Meta connectivity, tunnel callback verification and handset rendering require
  your real development setup and are not established by passing mocked tests.
