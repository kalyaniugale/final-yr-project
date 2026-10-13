# Geographic slot workspace review

The existing geographic map now uses a desktop map/inspector split of approximately
73/27 and a compact expandable mobile bottom sheet. Slot selection immediately
updates basic details and highlights the polygon without replacing/resizing the
map or scrolling the page. Controls, site-layer toggle and legend are on the map;
advanced evidence is in one Map information menu and admin generation/edit options
are in Layout tools. Surrounding officer chrome is compacted only while this map
is open. Other pages retain their existing presentation.

Zone names are prominent, internal IDs secondary. Vendor views distinguish
selected slots from the authenticated assigned slot. Private vendor identity and
allocation data are shown only in the admin inspector, which links to the existing
authorized details drawer. Assignment, release, reviewed generation, geometry
editing and validation reuse existing workflows and APIs.

Public business categories for other slots are not currently supplied by the API.
The UI displays an explicit unavailable value rather than using private vendor
fields or inventing business titles. The vendor's own category is supplied from
their existing profile. No new backend data contract was introduced.

Unreliable Start Navigation and follow-location controls are absent from this
page. Existing in-app GPS/routing modules remain intact for future work. View My
Slot targets only the authenticated assignment. Google Maps walking links require
a matching own-slot destination, finite WGS84 coordinates and an observed,
configured pedestrian approach. There is no centroid fallback. Recorded approaches
and slot geometry remain provisional and require site verification.

## Verification

- 10 focused tests passed: slot selection/cache state, GPS utilities retained for
  future navigation, public-category privacy and own observed-access link guards.
- Final Vite build ran once and passed; `git diff --check` passed.
- Desktop and mobile browser checks passed: S010 then S009 updates immediately
  without scrolling/map resizing; assigned S002 remains highlighted; injected
  other-vendor private fields are not rendered; no Start Navigation button or
  unobserved-centroid directions link exists; a configured own access point
  produces the correct external-link destination.
- Admin status save, generation/edit/reviewed save and map-instance persistence
  checks passed using isolated browser API fixtures.
- Desktop admin, mobile admin and mobile vendor screenshots were captured and
  visually reviewed. They remain in the temporary browser output directory
  `C:\Users\Darshan\AppData\Local\Temp\nmc-pilot-review-M9liOA` because copying
  them into the repository was declined.

Browser fixtures verify UI behavior, not live assignment writes or external
Google directions. No operational data, uploaded boundaries, algorithms,
authentication permissions or backend files were changed. No full backend suite,
live routing/GPS or municipal site review was run for this layout task.
