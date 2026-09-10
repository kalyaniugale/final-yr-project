# Nashik Vendor Management — Implementation UI

A five-screen React + FastAPI research demonstration using the actual processed project data. This release changes presentation and adds read-only endpoints; it does not retrain or replace any ML model.

## Screens

1. Overview — live registry counts, project workflow and model status.
2. Zone registry — all 308 official records, searchable by ID, description, division and zone type, with a record-details panel.
3. Recommendations — vendor input, Top 3, real Leaflet reference map, selected-zone reasons and expandable factor evidence.
4. GIS & model insights — feature groups, processing workflow, K-Means evaluation and reference coverage.
5. Expert review — review progress and instructions for opening the existing independent Streamlit labeling tool.

The recommendation list no longer displays the repeated availability-unverified text, and the verified-only checkbox is removed. The normal request uses exploratory candidates. The backend continues to enforce zone-type and explicit closure restrictions, and it does not invent vacancy or municipal approval. A concise footer and contextual details preserve the distinction between official records and unverified analytical boundaries.

## Install the backend

Keep your existing project structure and your original training scripts. Copy the files from this ZIP's backend/ folder into:

C:\Users\kalya\vendor-map\backend\

Replace api.py and mcda_engine.py. Keep 05_recommend.py, or replace it with the included matching version. Do not copy these into scripts/ or app/; run from the project root with --app-dir backend.

In PowerShell:

cd C:\Users\kalya\vendor-map
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn
python -m uvicorn api:app --app-dir backend --reload --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000/docs to check the API. Keep this terminal running.

The backend reads existing data/processed files, official_zones.csv, and reports/data_quality/geometry_duplicates. Run the earlier geometry_duplicate_audit.py if those reports are missing.

## Install the frontend

The included frontend/ directory is a complete standalone Vite app with its own sidebar and five-page navigation. To avoid damaging your existing dashboard, first run it separately:

1. Rename your existing frontend folder if needed, or extract this ZIP into another folder such as vendor-map/implementation-demo.
2. Open a second terminal in the extracted frontend/ directory.
3. npm install
4. npm run dev
5. Open the local Vite address, normally http://127.0.0.1:5173.

The API allows localhost and 127.0.0.1 at port 5173. If your current Vite app uses another port, update the local CORS origins in backend/api.py. The frontend uses VITE_API_BASE, defaulting to http://127.0.0.1:8000.

To integrate into your existing React dashboard rather than run a second shell, copy:
- frontend/src/components/RecommendationPage.jsx
- frontend/src/components/RecommendationPage.css
- frontend/src/pages/ImplementationPages.jsx
- frontend/src/ImplementationApp.css

Mount individual pages in your existing routes and keep your existing sidebar. ImplementationApp.jsx is optional: use it only if you want the complete supplied demo navigation. The package uses React 18, react-leaflet@4, Leaflet and lucide-react. Do not create a second BrowserRouter inside an existing router.

## Run the WhatsApp Bot Locally

For **Windows Git Bash**. Prerequisites: a Python virtual environment at `.venv` with project dependencies installed, ngrok installed and authenticated, and `backend/whatsapp/.env` configured.

Open three Git Bash terminals at the **project root** and keep them running.

**Terminal 1 — Recommendation backend:**

```bash
source .venv/Scripts/activate
python -m uvicorn api:app --app-dir backend --port 8000
```

**Terminal 2 — WhatsApp service:**

```bash
source .venv/Scripts/activate
set -a
source backend/whatsapp/.env
set +a
python -m uvicorn backend.whatsapp.webhook:app --port 8001 --workers 1
```

**Terminal 3 — ngrok:**

```bash
ngrok http 8001
```

ngrok outputs a public HTTPS URL, such as `https://xxxx.ngrok-free.app`. Set the Meta webhook callback to that URL followed by `/webhook`: `https://xxxx.ngrok-free.app/webhook`. If the ngrok URL changes, update the Meta webhook callback.

### Quick verification

1. Open [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health).
2. Send **Hi** to the configured WhatsApp test number.
3. Confirm `POST /webhook` appears in the port 8001 terminal.
4. Confirm the bot replies with the language menu.

The recommendation backend must be running before testing recommendations.

## Data and model integrity

The current ranking is weighted MCDA, not XGBoost, Random Forest or a supervised predictor. K-Means K=2 is the environmental baseline; K=4 is an alternative experiment. SHAP is not used. Factor explanations are deterministic and derived from each recommendation's actual GIS/evidence fields.

Listed capacity is not live available capacity. No live-status data is supplied. Existing-vendor IDs return only non-identifying model fields and do not establish identity. Historical proposed zones are not automatically considered verified current locations. The map uses analytical reference points, not official legal polygons. Shared-reference details remain visible when relevant.

The overview and zone registry read the actual source tables. The GIS screen includes the already-reported K-Means evaluation results; these are clustering metrics, not recommendation accuracy. The expert-review screen reads local queue and label counts but does not fabricate completed judgments. The separate Streamlit tool remains the actual labeling workflow.

## Testing and limitations

The Python API was syntax-checked and exercised using the project reference-zone structure and synthetic OSM fixtures. Catalogue, overview, review summary and recommendation explanation endpoints returned successfully. All JSX files passed syntax parsing. A full npm/browser build was not completed in the execution environment; run npm install and npm run build locally.

The API is for local research use. Public deployment requires authenticated vendor lookup, access controls, rate limiting, audit logs, municipal data stewardship and a secure live-status backend. Do not publish personal vendor records or present this prototype as an operational allocation authority.
