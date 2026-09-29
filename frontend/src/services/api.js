// Keep browser and API on the same hostname in local development. A page opened
// at localhost cannot reliably send a SameSite session cookie to 127.0.0.1
// (and vice versa), even though both addresses reach the same machine.
const LOCAL_API_BASE = typeof window === "undefined"
  ? "http://127.0.0.1:8000"
  : `${window.location.protocol}//${window.location.hostname}:8000`;
const API_BASE = (import.meta.env.VITE_API_BASE || LOCAL_API_BASE).replace(/\/$/, "");

export async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {credentials: "include", ...options});
  } catch {
    throw new Error("Unable to reach the service. Check that the backend is running and try again.");
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`The service returned an unreadable response (${response.status}).`);
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "The request could not be completed.";
    throw new Error(detail);
  }
  return body;
}

const jsonOptions = (method, body) => ({
  method,
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify(body),
});

export const getOptions = () => apiRequest("/api/options");
export const registerVendor = profile => apiRequest("/api/vendors", jsonOptions("POST", profile));
export const getVendorProfile = vendorId => apiRequest(`/api/vendors/${encodeURIComponent(vendorId)}`);
export const updateVendorProfile = (vendorId, updates) =>
  apiRequest(`/api/vendors/${encodeURIComponent(vendorId)}`, jsonOptions("PATCH", updates));
export const getActiveAllocation = vendorId =>
  apiRequest(`/api/vendors/${encodeURIComponent(vendorId)}/active-allocation`);
export const getVendorDashboard = () => apiRequest("/api/vendors/me/dashboard");
export const getVendorEligibleZones = () => apiRequest("/api/vendors/me/eligible-zones");
export const getRecommendations = (vendorId, excludeZone = "", preferences = {}) =>
  apiRequest("/api/recommendations", jsonOptions("POST", {
    vendor_id: vendorId,
    exclude_zone: excludeZone,
    business: preferences.business || "",
    division: preferences.division || "",
    top_n: 3,
  }));
export const createAllocationRequest = payload =>
  apiRequest("/api/allocation-requests", jsonOptions("POST", payload));
export const getAllocationRequest = requestId =>
  apiRequest(`/api/allocation-requests/${encodeURIComponent(requestId)}`);
export const cancelAllocationRequest = requestId =>
  apiRequest(`/api/allocation-requests/${encodeURIComponent(requestId)}/cancel`, {method: "POST"});
export const getZoneGeometry = () => apiRequest("/api/zones/geometry");
export const requestVendorOtp = mobile =>
  apiRequest("/api/auth/vendor/request-otp", jsonOptions("POST", {mobile}));
export const verifyVendorOtp = (challengeId, otp) =>
  apiRequest("/api/auth/vendor/verify-otp", jsonOptions("POST", {challenge_id: challengeId, otp}));
export const loginAdmin = (username, password) =>
  apiRequest("/api/auth/admin/login", jsonOptions("POST", {username, password}));
export const getCurrentUser = () => apiRequest("/api/auth/me");
export const logout = () => apiRequest("/api/auth/logout", {method: "POST"});
export const getAdminOverview = () => apiRequest("/api/admin/overview");
export const getAllocationRequests = (status = "") =>
  apiRequest(`/api/allocation-requests${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const approveAllocationRequest = (requestId, notes = null) =>
  apiRequest(`/api/allocation-requests/${encodeURIComponent(requestId)}/approve`,
    jsonOptions("POST", {notes}));
export const rejectAllocationRequest = (requestId, rejectionReason, notes = null) =>
  apiRequest(`/api/allocation-requests/${encodeURIComponent(requestId)}/reject`,
    jsonOptions("POST", {rejection_reason: rejectionReason, notes}));
export const getAllocations = (status = "") =>
  apiRequest(`/api/allocations${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const getZoneLiveStatus = zoneId =>
  apiRequest(`/api/zones/${encodeURIComponent(zoneId)}/live-status`);
export const updateZoneLiveStatus = (zoneId, status) =>
  apiRequest(`/api/zones/${encodeURIComponent(zoneId)}/live-status`,
    jsonOptions("PATCH", {status}));
export const getZoneCatalog = filters => {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => value && params.set(key, value));
  const query = params.toString();
  return apiRequest(`/api/admin/zones${query ? `?${query}` : ""}`);
};
