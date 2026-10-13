# Geographic slot allocation and unified navigation — Lekha Nagar

This upgrades the existing NN_F_013 pilot. It reuses the pilot endpoints, SQLite
entities, officer/vendor sessions, approved zone allocations and React Leaflet.
The recommendation, MCDA, AHP, K-Means and Goal Programming paths are unchanged.
No new package or external drawing library was installed.

## Imported boundaries and actual results

The exact coordinates supplied in this conversation are saved in
`data/pilot/lekha_nagar_boundaries.geojson`. Property ID **2974** is **Boundary A**;
**3577** is **Boundary B**. Original geographic rings are preserved. No buffer or
guessed geometry replaces them. The loader rejects missing, invalid, duplicate,
wrong-CRS or nonlocal polygons instead of repairing them silently.

Both are user-drawn Geoman proposals, not surveyed or legally verified NMC
boundaries. NN_F_013's official record remains FREE, New Nashik, listed capacity
10, Lekha Nagar/Balbharati Office. Its analytical reference is shared with
NO_VENDING records NV_064 and NV_069; the original A/B/C GPS points are outside
that reference. Proposed boundary import does not resolve these policy conflicts.

The default generation was executed against the supplied polygons:

| Check | Actual result |
| --- | --- |
| Boundary A | Valid polygon; 5 slots, S001–S005 |
| Boundary B | Valid polygon; 5 slots, S006–S010 |
| Total capacity | 10 / maximum 10 |
| Dimensions | Every footprint 2 m × 2 m; largest edge error about 1.9 × 10⁻⁹ m |
| Minimum footprint spacing | 0.4999999991 m, within the 0.002 m numerical tolerance |
| Containment | Every slot contained in its actual parent polygon |
| Overlap | No slot overlaps another slot or its pedestrian corridor |
| Corridor | Continuous rectangular 1.2 m strip per boundary, assumed side |
| Physical/legal verification | Not established |

The machine-readable measurements are in
`reports/pilot_slots/geographic_validation.json`. They validate geometry, not
real pavement usability, absence of unknown obstructions or legal authorization.

## Generation and validation

`backend/pilot_geometry.py` uses PyProj with `always_xy=True`: GeoJSON coordinates
are longitude/latitude in EPSG:4326; calculations use EPSG:32643 (UTM 43N).

For each boundary, the generator infers a straight alignment from its minimum
rotated rectangle's longest edge, or uses an admin-specified UTM angle. Left/right
corridor side refers to that alignment frame and makes no building-side claim.
It searches candidate rows and feasible continuous stretches at 0.25 m intervals.
Each candidate 2 m square and its adjacent corridor strip must fit completely in
the parent. Candidates maintain at least 0.5 m spacing. Known recorded obstacles
are excluded. The reserved strip extends along the feasible continuous stretch,
allowing validated later moves along it.

Generation initially attempts five slots per boundary. If shape, width, spacing,
corridor or recorded obstacles prevent that result, it returns fewer slots and
boundary-specific rejection reasons. This is a conservative deterministic search,
not a guarantee of globally optimal packing. It never fills missing capacity by
placing invalid rectangles. The generator configuration supports spacing and
clearance increases; neither can drop below the requested 0.5 m / 1.2 m defaults.
Slot dimensions remain fixed at 2 m × 2 m.

Server validation independently checks every saved proposal: valid four-corner
rectangles, dimensions/area, parent containment, unique IDs, ten-slot maximum,
spacing, continuous corridor width, corridor non-overlap and observed obstacles.
Map storage/display converts validated geometry back to EPSG:4326.

## Persistence, editing and migration

Existing `pilot_slot_layouts`, `pilot_slots` and `pilot_slot_events` are reused.
The existing schema initializer idempotently adds `parent_boundary_id`,
`geometry_crs` and `is_deleted` to the slot table. Boundary provenance, imported
rings, corridor configuration/geometries, observed obstructions, access points,
validation summary and layout revision live in the existing layout metadata.
No competing allocation or boundary tables were introduced.

Existing schematic rows and assignments are preserved until an officer reviews
and saves a geographic preview. **Assigned or OCCUPIED slots cannot be moved,
deleted or silently replaced by regeneration.** Release their demo assignment
and change their demo status explicitly before a migration that affects them.
Real approved zone allocations are retained. An unchanged assigned polygon can
remain in a saved revision while unrelated unassigned geometry is edited.

Draft geometry is separate from saved geometry. Select an unprotected slot, drag
its centre handle on the map, or apply a rotation. The backend reconstructs the
2 m square in UTM metres and rejects invalid placements. Delete is a soft deletion
so event history and stable IDs remain available; initialization does not reseed
deleted geographic slots. BLOCKED status uses the existing officer status action.

Recorded obstruction footprints are generated in metres around a clicked map
point, with an officer-entered note and radius. An obstruction that invalidates
the current draft is retained for review, but **saving is disabled/rejected**.
Use **Regenerate around observations** to seek a valid layout, or remove the
incorrect observation. New observation data never silently overrides a protected
assignment. An access point can be clicked per boundary, with an approach note
and an observation flag; this is not municipal verification.

Every save checks a boundary-source hash, expected layout revision and expected
slot timestamps inside an immediate SQLite transaction. Concurrent status or
geometry changes require a reload. Explicit review confirmation is required.
Slot changes are officer-attributed in the separate demo event history.

New vendor links require the saved slot to be AVAILABLE and the vendor to have
an ACTIVE NN_F_013 allocation joined to its matching APPROVED request. Unique
vendor indexing prevents multiple active demo slots. One slot has one vendor
link. Release clears only the demo link, not the operational zone allocation.
The old schematic cannot provide a geographic navigation destination.

## One-map vendor navigation

Only vendors with an approved pilot-zone allocation can retrieve pilot data.
The dashboard shows **Navigate to My Slot** when their geographic demo assignment
exists. Otherwise it shows **No vending slot has been assigned yet**, with an
optional pilot map entry for an approved zone allocation. Recommendation alone
does not enable assignment or navigation. Other vendors' identifying information
is redacted, and vendors cannot mutate statuses or geometry.

The same Leaflet map contains the assigned polygon, nearby slots, boundaries,
GPS position/accuracy circle, actual walking-route polyline and returned route
endpoint. It does not open an external map or create a second navigation map.

**Start Navigation** explicitly requests browser location permission. GPS is
watched with high accuracy, a 10-second cached-fix allowance and a 20-second
timeout. Live updates remain in browser memory. Only a route-request position
is sent through the proxy to the provider. Watching stops on Stop Navigation,
pilot close or component unmount. Denied/unavailable GPS and insecure contexts
show usable messages while retaining the assigned polygon.

Controls include Start/Stop, Recenter on My Location, Show My Slot, Show Entire
Route, Refresh Walking Route and optional follow mode. Panning pauses follow.
Within 40 m of the returned access endpoint (or requested access point), with GPS
accuracy no worse than 50 m, follow mode zooms toward the assigned polygon and
nearby numbers. The UI says **You are near your assigned vending area**, never
that the vendor has entered a specific 2 m stall. Poor accuracy suppresses this
proximity transition. Selected/assigned labels remain visible at low zoom;
neighbor labels appear at zoom 19+. Base-map tiles beyond native zoom 19 are
enlarged for polygon identification, with no claim of extra map precision.

The slot's interior representative point, an admin-recorded approach point and
the actual returned pedestrian-network endpoint are distinct concepts. Without
an observed approach point, routing requests nearby network snapping around the
slot point; an endpoint more than 35 m from the requested point is rejected.
The final approach remains explicitly approximate. No straight connector is
displayed as a walkable path; site access and crossings remain unverified.

Displayed route distance, duration and instructions come from the provider's
response. Distance/duration are labelled as route-calculation values, not live
remaining distance or guaranteed arrival time. No ETA is invented when absent.

## Walking provider and configuration

The backend proxy uses **openrouteservice**, POST
`/v2/directions/foot-walking/geojson`. The provider documents pedestrian profiles
and GeoJSON LineString responses with distance, duration and walking steps:
[directions response documentation](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/requests-and-return-types),
[profile configuration](https://github.com/GIScience/openrouteservice/blob/main/ors-config.env).
It does not use the OSRM public driving demo.

Add your own server-side values to `.env` if live routing is needed:

```dotenv
ORS_API_KEY=your-own-openrouteservice-key
ORS_BASE_URL=https://api.openrouteservice.org
```

`.env.example` contains these optional variables. The user's `.env` was not read
or edited. No key is embedded in the frontend or returned in a route response.
A configured self-hosted ORS instance is supported; HTTP is accepted only for
localhost. Hosted ORS needs an account/key with walking access. Check your account
quota and current [service restrictions](https://openrouteservice.org/restrictions/)
and [account plans](https://account.heigit.org/info/plans). The proxy adds a
per-process ten-second request interval per vendor and a 15-second timeout; live
GPS ticks do not automatically request new routes. Routing failures, rate limits,
missing credentials or unreliable endpoints produce map-only guidance without
inventing geometry, distance or ETA.

**Live provider routing was not exercised with real credentials.** Provider
normalization and failure handling were tested with controlled HTTP responses,
and browser GPS/routing were mocked. A real-device field demonstration requires
your key, GPS permission, network connectivity and verified safe site approach.
Only OpenStreetMap tiles are enabled; no unauthorized satellite provider is added.

## Windows startup

From the existing configured environment, terminal one:

```powershell
Set-Location C:\Users\Darshan\final-yr-project
.\.venv\Scripts\python.exe -m uvicorn api:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Terminal two:

```powershell
Set-Location C:\Users\Darshan\final-yr-project\frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Keep browser/API hostnames consistent for cookies.
Outside localhost, browser GPS requires HTTPS. Restart the backend after adding
routing environment values. Existing requirements provide Shapely/PyProj/httpx;
there are no added dependencies or manual database-reset steps.

## Admin demonstration

1. Sign in, open **Admin → Map / Zone Explorer**, select NN_F_013 from its shared
   analytical-reference popup and click **View Slot Map** in Zone Details.
   Zone Management's NN_F_013 details have the same entry.
2. See both imported proposed boundaries. Set Boundary A/B's assumed corridor
   side and optional UTM alignment angle. The default uses the polygon long axis.
3. Click **Generate geographic preview**. The default fits five slots per
   boundary. Review any rejection reasons, positions and corridor strips.
4. Check the review box and **Save reviewed layout**. If legacy slots are assigned
   or occupied, cancel the preview and explicitly release/change their demo
   state before retrying the reviewed migration.
5. Click the S005 polygon or choose it in the inspector. **Zoom to selected
   slot** makes a 2 m footprint legible. Set RESERVED/OCCUPIED and choose an
   eligible approved vendor while S005 is saved AVAILABLE; click
   **Save demonstration slot**. The real zone allocation is unchanged.
6. **Edit Slot Layout** creates a draft. Unassigned/unoccupied slots have a drag
   handle and rotation/delete controls. Record obstructions/access points as
   appropriate, review the validated result, then save or cancel.
7. **Back to All Zones** returns to the city map. Drawer visibility is independent
   of the pilot; closing/reopening retains the map instance, selection, geometry
   and zoom. ResizeObserver/Leaflet invalidateSize handle panel changes.
8. Reload the page and verify persisted geographic geometry and assignment.
   Slot data persists; transient selection/draft UI starts a new session.

## Vendor demonstration

1. Sign in as the vendor with the approved NN_F_013 allocation and saved demo
   assignment. The dashboard displays its slot number and 2 m × 2 m size.
2. Click **Navigate to My Slot**. Their polygon is selected/highlighted among
   neighboring numbered stalls on one large map; management controls are absent.
3. Click **Start Navigation**, grant permission and inspect GPS accuracy. With
   configured walking credentials, the provider's actual route is displayed.
   Otherwise the map explains routing unavailability without a guessed route.
4. Use follow/recenter/entire-route controls. Near the endpoint, follow mode
   transitions to the slot view on the same map, with approximate-approach and
   provisional-position warnings. **Show My Slot** works at any time.
5. **Stop Navigation** ends GPS watching but keeps the polygon/map available.
   **Back to Dashboard** also stops watching.

## Tests and verification

Executed on 10 October 2026:

| Check | Result |
| --- | --- |
| Python compilation | Passed |
| Geographic-specific backend tests | 12 passed |
| Complete backend suite, including existing pilot/allocation/auth tests | 98 passed |
| Frontend tests, including GPS cleanup and proximity tests | 32 passed |
| Vite production build | Passed; geographic module loaded as a separate chunk |
| Desktop/mobile Edge browser checks | Passed, with mocked GPS/provider responses |
| Git diff whitespace check | Passed |

The backend suite reports one existing Starlette/httpx deprecation warning.
No live routing request with a real key or physical GPS field test was performed.
Reproduce the checks:

```powershell
Set-Location C:\Users\Darshan\final-yr-project
.\.venv\Scripts\python.exe -m compileall -q backend tests/test_pilot_slots.py tests/test_pilot_geographic.py
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm test
npm run build
npm run test:pilot:browser
```

The browser test uses installed Edge, existing Vite and Node's built-in WebSocket;
no automation package is required. Set `$env:EDGE_PATH` for a nondefault Edge
installation. It derives its slot fixture from the real backend generator and
supplied boundaries, then mocks API/GPS/provider interactions. It checks desktop
and 390 px mobile layouts, polygon selection, preview/edit/save, drawer independence,
map preservation, vendor dashboard navigation, a single map instance, proximity
guidance, GPS stop/denial, route failure and no-assignment state.

`node tests/pilot-browser-smoke.mjs --screenshots` saves review captures in a new
temporary directory and prints its location. Production builds do not include
the test harness. The geographic pilot is loaded on demand to keep its code out
of the initial dashboard bundle.

Backend tests cover the supplied geometry, order of coordinates, dimensions,
containment/spacing/corridors/capacity, rotated/irregular/narrow synthetic fixtures,
invalid poses, metre-based move persistence, protected slots, stale writes,
soft deletion, approved allocation eligibility, concurrent assignment, data
isolation, vendor ownership/privacy, actual route-response normalization and
failure fallback. Synthetic test shapes are never production boundaries.

## Remaining field evidence

Required before verified ground mapping: authoritative zone boundaries and
resolution of nearby NO_VENDING restrictions; survey CRS/method/accuracy and GPS
point association; measured pavement edges, usable width/length and road/building
orientation; obstacles, entrances, crossings, utilities and emergency access;
municipal clearance/dimension rules; verified pedestrian approach and site review.
No landmarks, site photographs, safe crossings or arrival confirmations were invented.

## File manifest for this upgrade

Created:

- `backend/pilot_geometry.py`
- `backend/pilot_navigation.py`
- `data/pilot/lekha_nagar_boundaries.geojson`
- `frontend/src/utils/pilotNavigation.js`
- `frontend/src/utils/pilotNavigation.test.js`
- `tests/test_pilot_geographic.py`
- `reports/pilot_slots/geographic_validation.json`

Modified existing pilot/integration files:

- `.env.example`
- `backend/api.py`
- `backend/database.py`
- `backend/pilot_slots.py`
- `frontend/package.json`
- `frontend/src/components/AdminDashboard.jsx`
- `frontend/src/components/VendorPortal.jsx`
- `frontend/src/components/PilotSlotMap.jsx`
- `frontend/src/components/PilotSlotMap.css`
- `frontend/src/services/api.js`
- `frontend/src/utils/pilotState.js`
- `frontend/tests/pilot-harness.jsx`
- `frontend/tests/pilot-browser-smoke.mjs`
- `docs/pilot-slot-mapping.md`

Pre-existing untracked research outputs and the synthetic-demo script were left
untouched. The original schematic generator and its tests remain for compatibility;
the geographic map replaces the schematic as the primary pilot UI.
