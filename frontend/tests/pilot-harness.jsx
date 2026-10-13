// Browser-only review fixture. Never imported by the application entry point.
import React from "react";
import {createRoot} from "react-dom/client";
import ImplementationApp from "../src/app/ImplementationApp.jsx";
import AuthLanding from "../src/features/auth/AuthLanding.jsx";
import AdminDashboard from "../src/features/admin/AdminDashboard.jsx";
import PilotSlotMap from "../src/features/pilot-slots/PilotSlotMap.jsx";
import RecommendationPage from "../src/features/recommendations/RecommendationPage.jsx";
import {OverviewPage,ZoneRegistryPage,AnalysisPage,ReviewPage} from "../src/pages/ImplementationPages.jsx";
import VendorPortal from "../src/features/vendor/VendorPortal.jsx";
import {I18nProvider} from "../src/i18n/react.jsx";
import "../src/features/recommendations/RecommendationPage.css";

const fixture = await fetch("/__pilot_fixture__").then(response => response.json());
const mode = new URLSearchParams(location.search).get("mode") || "admin";
let layout = JSON.parse(sessionStorage.getItem("pilot-review-layout") || "null") || structuredClone(fixture.layout);
const vendor = {vendor_id: "V_PILOT_DEMO", vendor_name: "Pilot Test Vendor", allocation_id: "ALLOC_DEMO", request_id: "REQ_DEMO", zone_id: "NN_F_013", status: "ACTIVE"};
const profile = {vendor_id: vendor.vendor_id, vendor_type: "EXISTING_IMPORTED", full_name: "Pilot Test Vendor", business_category: "food", preferred_division: "New Nashik", preferred_language: "en", priority_profile: "BALANCED", status: "ACTIVE"};
if (["vendor-access","vendor", "portal-vendor", "denied", "routing-failure"].includes(mode)) {layout.my_slot_id = "S002"; layout.slots[1].assigned_vendor_id = vendor.vendor_id; layout.slots[1].status = "RESERVED";}
if (mode === "empty") layout.my_slot_id = null;
if (mode.startsWith("vendor")) {layout.slots[8].assigned_vendor_id="PRIVATE_VENDOR_ID";layout.slots[8].vendor_name="PRIVATE_VENDOR_NAME";layout.slots[8].business_category="PRIVATE_VENDOR_CATEGORY";}
window.__gps = {clears: 0};
window.__slotPoint = [layout.slots[1].pose.longitude, layout.slots[1].pose.latitude];
Object.defineProperty(navigator, "geolocation", {configurable: true, value: {
  watchPosition: (success, error) => {window.__gps.success = success; window.__gps.error = error; setTimeout(() => mode === "denied" ? error({code: 1}) : success({coords: {longitude: 73.7719, latitude: 19.9745, accuracy: 8}}), 0); return 42;},
  clearWatch: () => {window.__gps.clears++;},
}});
window.fetch = async (url, options = {}) => {
  const path = new URL(url, location.origin).pathname;
  if (path.startsWith("/api/")) {if (options.credentials !== "include") throw new Error("Missing authenticated request credentials");}
  let body;
  if (path === "/api/auth/me") body = mode === "shell-admin" ? {role:"ADMIN",admin_id:"fixture-officer"} : {role:"VENDOR",vendor_id:vendor.vendor_id,vendor_profile:profile};
  else if (path === "/api/overview" || path === "/api/review-summary") body = {};
  else if (path === "/api/catalog") body = {zones: [fixture.zone]};
  else if (path === "/api/admin/overview") body = {total_official_zones: 1, zone_status_counts: {OPEN: 1}, request_status_counts: {}, allocation_status_counts: {ACTIVE: 1}};
  else if (path === "/api/admin/zones") body = {zones: [fixture.zone]};
  else if (path === "/api/allocation-requests") body = {requests: []};
  else if (path === "/api/allocations") body = {allocations: [vendor]};
  else if (path === "/api/zones/geometry") body = {type: "FeatureCollection", features: fixture.layout.evidence.analytical_references};
  else if (path === "/api/pilot/initialize" || path === "/api/pilot/layout") {
    if (options.method === "PATCH") {layout = {...JSON.parse(options.body).layout, revision: "SAVED_REVIEW"}; layout.slots.forEach(s => {s.updated_at = new Date().toISOString();}); sessionStorage.setItem("pilot-review-layout", JSON.stringify(layout));}
    body = layout;
  }
  else if (path === "/api/pilot/preview") body = {...structuredClone(fixture.layout), expected_revision: layout.revision, expected_versions: Object.fromEntries(layout.slots.map(s => [s.slot_id, s.updated_at]))};
  else if (path === "/api/pilot/validate") {body = JSON.parse(options.body).layout; window.__editValidations = (window.__editValidations || 0) + 1;}
  else if (path === "/api/pilot/navigation") body = {assigned: !!layout.my_slot_id, navigable: !!layout.my_slot_id, slot_id: layout.my_slot_id, approach_observed:mode === "vendor-access", requested_access_point: mode === "vendor-access" ? [73.7718,19.9744] : window.__slotPoint, proximity_threshold_m: 40};
  else if (path === "/api/pilot/route") body = mode === "routing-failure" ? {available: false, reason: "Walking routing unavailable. Your slot remains visible."} : {available: true, geometry: {type: "LineString", coordinates: [[73.7719, 19.9745], [73.7725, 19.974], window.__slotPoint]}, access_endpoint: window.__slotPoint, distance_m: 200, duration_s: 150, instructions: [{instruction: "Follow the pedestrian route"}], attribution: "MOCK PROVIDER RESPONSE — BROWSER TEST ONLY"};
  else if (path === "/api/options") body = {categories: ["food"], divisions: ["New Nashik"]};
  else if (path === "/api/vendors/me/dashboard") body = {profile, active_allocation: vendor, requests: [], request_summary: {pending_count: 0, approved_count: 1, rejected_count: 0, cancelled_count: 0}, action_state: {has_pending_request: false, can_submit_request: true}};
  else if (path.startsWith("/api/pilot/slots/")) {
    const slot = layout.slots.find(s => s.slot_id === path.split("/").at(-1));
    Object.assign(slot, JSON.parse(options.body), {updated_at: new Date().toISOString()});
    sessionStorage.setItem("pilot-review-layout", JSON.stringify(layout));
    body = slot;
  } else throw new Error(`Unexpected review API: ${path}`);
  return new Response(JSON.stringify(body), {status: 200, headers: {"Content-Type": "application/json"}});
};
createRoot(document.getElementById("root")).render(<I18nProvider>{mode.startsWith("shell-") ? <ImplementationApp/> : mode === "auth" ? <AuthLanding onAuthenticated={() => {}}/> : mode === "admin" ? <AdminDashboard/> : mode === "overview" ? <OverviewPage navigate={() => {}}/> : mode === "registry" ? <ZoneRegistryPage openZone={() => {}}/> : mode === "analysis" ? <AnalysisPage/> : mode === "review" ? <ReviewPage/> : mode === "research-recommendations" ? <RecommendationPage/> : mode.startsWith("portal-") ? <VendorPortal sessionProfile={profile} view={mode === "portal-profile" ? "vendor-profile" : mode === "portal-requests" ? "vendor-requests" : "vendor-dashboard"}/> : <PilotSlotMap onBack={() => {}}/>}</I18nProvider>);

import "../src/styles/foundation.css";
