import {AdminHome, PendingRequests, ZoneManagement, AllocationRecords, ZoneExplorer} from "./AdminTabPanels.jsx";
import React, {useEffect, useMemo, useReducer, useState} from "react";

import "leaflet/dist/leaflet.css";
import {Activity, AlertTriangle, Building2, Check, ClipboardList, RefreshCw, ShieldCheck, Users, X, XCircle} from "lucide-react";
import {approveAllocationRequest, getActiveAllocation, getAdminOverview, getAllocationRequests, getAllocations, getVendorProfile, getZoneCatalog, getZoneGeometry, rejectAllocationRequest, updateZoneLiveStatus} from "../../services/api.js";

import {publicVendorId} from "../../shared/utils/profileIdentity.js";
import ToastRegion from "../../shared/ui/ToastRegion.jsx";
const PilotSlotMap = React.lazy(() => import("../pilot-slots/PilotSlotMap.jsx"));
import {initialPilotState, pilotReducer} from "../pilot-slots/pilotState.js";
import {useDialogFocus} from "../../shared/utils/dialogFocus.js";
import "./AdminDashboard.css";
import "../../shared/maps/MapGrouping.css";

import {TABS, STATUS_COLORS, pretty, display, when} from "./viewModel.js";

import {StatusBadge} from "./AdminPrimitives.jsx";
export default function AdminDashboard({adminId = "Officer"}) {
  const [tab, setTab] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [pending, setPending] = useState([]);
  const [zones, setZones] = useState([]);
  const [allocations, setAllocations] = useState([]);
  const [geometry, setGeometry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [zoneFilters, setZoneFilters] = useState({q: "", division: "", zone_type: "", live_status: ""});
  const [allocationFilter, setAllocationFilter] = useState("");
  const [mapStatuses, setMapStatuses] = useState(Object.keys(STATUS_COLORS));
  const [selectedZone, setSelectedZone] = useState(null);
  const [pilot, dispatchPilot] = useReducer(pilotReducer, initialPilotState);
  const openPilot = () => {dispatchPilot({type: "open"}); setTab("map"); setSelectedZone(null);};
  const [requestDetail, setRequestDetail] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [statusTarget, setStatusTarget] = useState(null);
  useDialogFocus(Boolean(dialog || statusTarget || selectedZone || requestDetail), ".admin-modal, .admin-drawer");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  const refresh = async (message = "") => {
    setLoading(true); setError("");
    try {
      const [summary, requestData, zoneData, allocationData, geo] = await Promise.all([
        getAdminOverview(), getAllocationRequests("PENDING"), getZoneCatalog({}), getAllocations(),
        geometry ? Promise.resolve(geometry) : getZoneGeometry(),
      ]);
      setOverview(summary); setPending(requestData.requests); setZones(zoneData.zones);
      setAllocations(allocationData.allocations); setGeometry(geo);
      if (selectedZone) setSelectedZone(zoneData.zones.find(zone => zone.zone_id === selectedZone.zone_id) || null);
      if (message) setNotice(message);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); }, []);

  const divisions = useMemo(() => [...new Set(zones.map(zone => zone.division).filter(Boolean))].sort(), [zones]);
  const filteredZones = useMemo(() => zones.filter(zone =>
    (!zoneFilters.division || zone.division === zoneFilters.division)
    && (!zoneFilters.zone_type || zone.zone_type === zoneFilters.zone_type)
    && (!zoneFilters.live_status || zone.live_status === zoneFilters.live_status)
    && (!zoneFilters.q || `${zone.zone_id} ${zone.official_description}`.toLowerCase().includes(zoneFilters.q.toLowerCase()))
  ), [zones, zoneFilters]);
  const filteredAllocations = allocations.filter(item => !allocationFilter || item.status === allocationFilter);
  const mappedZones = filteredZones.filter(zone => mapStatuses.includes(zone.live_status));

  const openRequest = async request => {
    setError("");
    try {
      const [vendor, active] = await Promise.all([
        getVendorProfile(request.vendor_id), getActiveAllocation(request.vendor_id),
      ]);
      setRequestDetail({request, vendor, active: active.allocation, zone: zones.find(zone => zone.zone_id === request.zone_id)});
    } catch (err) { setError(err.message); }
  };
  const approve = async () => {
    if (!adminId.trim()) { setError("Enter an Admin ID before approval."); return; }
    setLoading(true); setError("");
    try {
      await approveAllocationRequest(dialog.request_id, notes || null);
      setDialog(null); setRequestDetail(null); setNotes("");
      await refresh(`Request ${dialog.request_id} approved. Allocation and occupancy were refreshed.`);
    } catch (err) { setError(err.message); setLoading(false); }
  };
  const reject = async () => {
    if (!adminId.trim()) { setError("Enter an Admin ID before rejection."); return; }
    if (!reason.trim()) { setError("A rejection reason is required."); return; }
    setLoading(true); setError("");
    try {
      await rejectAllocationRequest(dialog.request_id, reason.trim(), notes || null);
      setDialog(null); setRequestDetail(null); setReason(""); setNotes("");
      await refresh(`Request ${dialog.request_id} rejected. Zone occupancy was not changed.`);
    } catch (err) { setError(err.message); setLoading(false); }
  };
  const applyStatus = async status => {
    if (!adminId.trim()) { setError("Enter an Admin ID before changing zone status."); return; }
    setLoading(true); setError("");
    try {
      const zoneId = statusTarget?.zone_id || selectedZone?.zone_id;
      const updated = await updateZoneLiveStatus(zoneId, status);
      setStatusTarget(null);
      await refresh(`${zoneId} updated to ${updated.status}.`);
    } catch (err) { setError(err.message); setLoading(false); }
  };
  const changeStatus = status => setStatusTarget({zone_id: selectedZone.zone_id, from: selectedZone.live_status, status});
  useEffect(() => {
    if (!dialog && !statusTarget && !selectedZone && !requestDetail) return undefined;
    const close = event => {
      if (event.key !== "Escape") return;
      setDialog(null); setStatusTarget(null); setSelectedZone(null); setRequestDetail(null);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [dialog, statusTarget, selectedZone, requestDetail]);

  const zoneCounts = overview?.zone_status_counts || {};
  const requestCounts = overview?.request_status_counts || {};
  const allocationCounts = overview?.allocation_status_counts || {};
  const summaryCards = [
    ["Official zones", overview?.total_official_zones, Building2, "neutral"],
    ["Open zones", zoneCounts.OPEN, Activity, "open"], ["Full zones", zoneCounts.FULL, AlertTriangle, "full"],
    ["Closed zones", zoneCounts.CLOSED, XCircle, "closed"], ["Suspended", zoneCounts.SUSPENDED, AlertTriangle, "suspended"],
    ["Restricted", zoneCounts.RESTRICTED, ShieldCheck, "restricted"], ["No vending", zoneCounts.NO_VENDING, XCircle, "novending"],
    ["Active allocations", allocationCounts.ACTIVE, Users, "active"], ["Pending requests", requestCounts.PENDING, ClipboardList, "pending"],
    ["Approved", requestCounts.APPROVED, Check, "approved"], ["Rejected", requestCounts.REJECTED, XCircle, "rejected"],
  ];

  return <main className="admin-dashboard" aria-busy={loading}>
    <header className="admin-header"><div className="admin-header-identity"><img src="/nmc-logo.jpg" alt="Nashik Municipal Corporation emblem"/><div><span className="admin-eyebrow">NASHIK MUNICIPAL CORPORATION</span><h1>Vendor operations</h1><p>Street Vendor Management — Officer Portal</p></div></div><div className="admin-controls"><div className="admin-session-id"><span>Signed in officer</span><strong>{adminId}</strong></div><button onClick={() => refresh("Dashboard data refreshed.")} disabled={loading}><RefreshCw size={15}/>{loading ? "Refreshing…" : "Refresh data"}</button></div></header>
    <details className="service-disclosure service-session-note"><summary>About officer actions</summary><p>Officer identity is supplied by the authenticated server session and recorded with administrative actions.</p></details>
    <nav className="admin-tabs" aria-label="Administration sections">{TABS.map(item => <button key={item.id} className={tab === item.id ? "active" : ""} aria-current={tab === item.id ? "page" : undefined} onClick={() => setTab(item.id)}><item.icon size={16}/>{item.label}{item.id === "requests" && <b>{pending.length}</b>}</button>)}</nav>
    <ToastRegion success={notice} error={error} onDismissSuccess={() => setNotice("")} onDismissError={() => setError("")} retry={() => refresh()}/>
    {loading && !overview && <div className="admin-loading-state" role="status"><RefreshCw size={20}/><div><strong>Loading operational dashboard</strong><span>Retrieving requests, allocations, live zone status, and map references.</span></div></div>}

    {tab === "overview" && <AdminHome pending={pending} allocationCounts={allocationCounts} summaryCards={summaryCards} zoneCounts={zoneCounts} setTab={setTab} setAllocationFilter={setAllocationFilter} setZoneFilters={setZoneFilters}/>}

    {tab === "requests" && <PendingRequests pending={pending} zones={zones} allocations={allocations} openRequest={openRequest} setDialog={setDialog}/>}

    {tab === "zones" && <ZoneManagement filteredZones={filteredZones} zoneFilters={zoneFilters} setZoneFilters={setZoneFilters} divisions={divisions} setSelectedZone={setSelectedZone}/>}

    {tab === "allocations" && <AllocationRecords filteredAllocations={filteredAllocations} allocationFilter={allocationFilter} setAllocationFilter={setAllocationFilter} setRequestDetail={setRequestDetail} zones={zones} setSelectedZone={setSelectedZone} setError={setError}/>}

    {tab === "map" && !pilot.open && <ZoneExplorer mappedZones={mappedZones} zoneFilters={zoneFilters} setZoneFilters={setZoneFilters} divisions={divisions} mapStatuses={mapStatuses} setMapStatuses={setMapStatuses} geometry={geometry} setSelectedZone={setSelectedZone}/>}

    {pilot.visited && <React.Suspense fallback={<p role="status">Loading geographic pilot…</p>}><PilotSlotMap onViewVendor={async allocation => {try {const [vendor,active] = await Promise.all([getVendorProfile(allocation.vendor_id),getActiveAllocation(allocation.vendor_id)]);setRequestDetail({vendor,active:active.allocation,zone:zones.find(z => z.zone_id === allocation.zone_id)});} catch(e) {setError(e.message);}}} admin session={pilot} dispatch={dispatchPilot} visible={tab === "map" && pilot.open} onBack={() => dispatchPilot({type: "close"})} allocations={allocations}/></React.Suspense>}

    {requestDetail && <div className="admin-drawer-backdrop" onClick={() => setRequestDetail(null)}><aside className="admin-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close" onClick={() => setRequestDetail(null)}><X size={18}/></button><span className="admin-eyebrow">{requestDetail.request ? "REQUEST DETAILS" : "VENDOR & ALLOCATION"}</span><h2>{requestDetail.request?.request_id || publicVendorId(requestDetail.vendor)}</h2>{requestDetail.request && <StatusBadge status={requestDetail.request.status}/>}<div className="drawer-grid"><div><span>{requestDetail.vendor.vendor_type === "NEW" ? "Application Vendor ID" : "Vendor ID"}</span><strong>{publicVendorId(requestDetail.vendor)}</strong></div><div><span>Vendor type</span><strong>{pretty(requestDetail.vendor.vendor_type)}</strong></div><div><span>Business</span><strong>{pretty(requestDetail.request?.business_category || requestDetail.vendor.business_category)}</strong></div><div><span>Priority</span><strong>{pretty(requestDetail.vendor.priority_profile)}</strong></div><div><span>Request type</span><strong>{pretty(requestDetail.request?.request_type || "—")}</strong></div><div><span>Created</span><strong>{when(requestDetail.request?.created_at)}</strong></div><div><span>Current zone</span><strong>{requestDetail.active?.zone_id || "None"}</strong></div><div><span>Target zone</span><strong>{requestDetail.zone?.zone_id || "—"}</strong></div><div><span>Division</span><strong>{requestDetail.zone?.division || "—"}</strong></div><div><span>Live status</span><strong>{requestDetail.zone?.live_status || "—"}</strong></div><div><span>Official capacity</span><strong>{display(requestDetail.zone?.official_capacity)}</strong></div><div><span>Current vendors</span><strong>{display(requestDetail.zone?.current_vendor_count)}</strong></div><div><span>Available</span><strong>{display(requestDetail.zone?.available_capacity)}</strong></div></div>{requestDetail.zone && <p className="drawer-description">{requestDetail.zone.official_description}</p>}{requestDetail.request && <div className="drawer-actions"><button className="admin-approve" onClick={() => setDialog({type: "approve", ...requestDetail.request})}>Approve request</button><button className="admin-reject" onClick={() => setDialog({type: "reject", ...requestDetail.request})}>Reject request</button></div>}</aside></div>}

    {selectedZone && <div className="admin-drawer-backdrop" onClick={() => setSelectedZone(null)}><aside className="admin-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close" onClick={() => setSelectedZone(null)}><X size={18}/></button><span className="admin-eyebrow">ZONE DETAILS</span><h2>{selectedZone.zone_id}</h2><StatusBadge status={selectedZone.live_status}/><p className="drawer-description">{selectedZone.official_description}</p><div className="drawer-grid"><div><span>Division</span><strong>{selectedZone.division}</strong></div><div><span>Policy type</span><strong>{pretty(selectedZone.zone_type)}</strong></div><div><span>Official capacity</span><strong>{display(selectedZone.official_capacity)}</strong></div><div><span>Current vendors</span><strong>{selectedZone.current_vendor_count}</strong></div><div><span>Available</span><strong>{display(selectedZone.available_capacity)}</strong></div><div><span>Reference status</span><strong>{pretty(selectedZone.reference_audit_status || "Not audited")}</strong></div><div><span>Active allocations</span><strong>{allocations.filter(item => item.zone_id === selectedZone.zone_id && item.status === "ACTIVE").length}</strong></div><div><span>Pending requests</span><strong>{pending.filter(item => item.zone_id === selectedZone.zone_id).length}</strong></div></div>{selectedZone.zone_id === "NN_F_013" && <button onClick={openPilot}>View Slot Map</button>}{selectedZone.zone_type === "FREE" ? <div className="zone-status-actions"><span>Manual operational status</span><p>FULL remains capacity-derived. Opening a zero-capacity zone keeps it FULL.</p><div>{["OPEN", "CLOSED", "SUSPENDED"].map(status => <button key={status} disabled={loading || selectedZone.live_status === status} onClick={() => changeStatus(status)}>{status}</button>)}</div></div> : <div className="policy-lock"><ShieldCheck size={17}/> Policy-controlled {pretty(selectedZone.zone_type)} zones cannot be changed here.</div>}</aside></div>}

    {dialog && <div className="admin-modal-backdrop" onClick={() => setDialog(null)}><div className="admin-modal" onClick={event => event.stopPropagation()}><div className={`modal-icon ${dialog.type}`} >{dialog.type === "approve" ? <Check size={24}/> : <XCircle size={24}/>}</div><span className="admin-eyebrow">{dialog.type === "approve" ? "CONFIRM APPROVAL" : "REJECT REQUEST"}</span><h2>{dialog.type === "approve" ? `Approve allocation to ${dialog.zone_id}?` : `Reject ${dialog.request_id}?`}</h2>{dialog.type === "approve" && <p>This will create an ACTIVE allocation and update the zone’s live occupancy atomically.</p>}{dialog.type === "reject" && <label><span>Rejection reason *</span><textarea value={reason} onChange={event => setReason(event.target.value)} placeholder="Explain why this request cannot be approved"/></label>}<label><span>Officer notes <small>optional</small></span><textarea value={notes} onChange={event => setNotes(event.target.value)} placeholder="Internal review note"/></label><div className="modal-capacity"><span>Current occupancy</span><strong>{zones.find(zone => zone.zone_id === dialog.zone_id)?.current_vendor_count ?? "—"}</strong><span>Available before review</span><strong>{display(zones.find(zone => zone.zone_id === dialog.zone_id)?.available_capacity)}</strong></div><div className="modal-actions"><button onClick={() => setDialog(null)}>Cancel</button><button className={dialog.type === "approve" ? "admin-approve" : "admin-reject"} onClick={dialog.type === "approve" ? approve : reject} disabled={loading}>{dialog.type === "approve" ? "Approve allocation" : "Reject request"}</button></div></div></div>}
    {statusTarget && <div className="admin-modal-backdrop" onClick={() => setStatusTarget(null)}><div className="admin-modal" role="dialog" aria-modal="true" aria-labelledby="zone-status-title" onClick={event => event.stopPropagation()}><div className="modal-icon approve"><ShieldCheck size={24}/></div><span className="admin-eyebrow">CONFIRM STATUS CHANGE</span><h2 id="zone-status-title">Change {statusTarget.zone_id} to {pretty(statusTarget.status)}?</h2><p>{statusTarget.status === "OPEN" ? "This will reopen the zone for operational use. Capacity rules still apply." : `This will remove the zone from live vendor recommendations while it is ${statusTarget.status.toLowerCase()}.`}</p><div className="modal-capacity"><span>Current status</span><strong>{pretty(statusTarget.from)}</strong><span>New status</span><strong>{pretty(statusTarget.status)}</strong></div><div className="modal-actions"><button onClick={() => setStatusTarget(null)}>Keep current status</button><button className={statusTarget.status === "OPEN" ? "admin-approve" : "admin-reject"} onClick={() => applyStatus(statusTarget.status)} disabled={loading}>Confirm change</button></div></div></div>}
  </main>;
}

