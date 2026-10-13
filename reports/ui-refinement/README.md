# UI refinement review

The authenticated application uses a shared service theme in `frontend/src/ServiceTheme.css`: off-white background (#F8FAF9), white surfaces, charcoal text (#1F2937), muted text (#667784), teal primary actions (#087F72), pale borders (#E7ECEF), 12px surfaces, 24px spacing, and 44px button/input targets. Shared CSS patterns cover disclosures, action sections, quick actions, filters, tables, forms, dialogs, map inspectors and destination cards. Native details/summary controls retain keyboard access without new dependencies.

## Screens and changes
- Officer home leads with pending applications and three quick actions. All operational counts remain in expandable details.
- Registry search remains visible; division/type/status filters expand on demand. Tables and smaller contextual drawers share the service styling.
- Overview, GIS/model insights and expert review retain their research content; count grids and clustering metrics expand on demand.
- Research recommendations retain results, maps, factor evidence and scoring. Factor breakdown is expandable.
- Vendor home retains allocation status, makes profile and request totals expandable, and emphasizes the next state-dependent action.
- Vendor requests retain cancellation, decisions and reasons; metadata/timeline expand within each request.
- Vendor profile and recommendation forms use shared controls and quieter surfaces.
- Slot mapping prioritizes polygons and selection; generation, map controls, assumptions and legend expand on demand. Assignment and draft editing remain available.
- Vendor navigation uses the existing single map. Start/Stop and recenter live in the bottom destination card; route options, source/approach details and GIS information are secondary.

Logo elements, dimensions and their sidebar/header placement are retained. Authentication and signup remain under their existing theme. This refinement did not change backend files, APIs, authorization, calculation logic, database state or saved polygon coordinates.

## Verification
- `npm test`: 32 passed.
- `npm run build`: passed.
- `node tests/pilot-browser-smoke.mjs --screenshots`: passed. Checks generation/edit/save, selected slot persistence, independent drawer state, a single map, route SVG with drawn geometry, approach guidance, GPS stopping/permission denial, unavailable routing and no assignment.
- Additional 1440px and 390px viewport checks passed for research overview, registry, GIS/model insights, expert review, research recommendation initial state, vendor requests, profile and home. Map checks cover desktop/mobile; no horizontal overflow in checked views.
- Screenshots in this directory were captured from real components using browser-only API/GPS fixtures. Empty research summaries show unavailable values rather than fabricated statistics. They are visual review artifacts, not live operational evidence.
- Visually inspected mobile slot management, mobile navigation, research overview and mobile profile screenshots.

## Remaining limits
The local `.env` has no ORS_API_KEY configured (only presence was checked; values were not logged). Consequently live provider routing was not tested. Real routing requires that server-side key, a backend restart and browser location permission. Provider fixtures verify actual frontend path rendering; no substitute route is created on provider failure. Real GPS, provider availability and every populated research/recommendation/error/dialog state still require live integration review. Existing component CSS is retained for authentication compatibility; the scoped service theme supplies shared authenticated styling.
