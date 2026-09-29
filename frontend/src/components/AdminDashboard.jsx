import React, {useEffect, useMemo, useState} from "react";
import {CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  Activity, AlertTriangle, BarChart3, Building2, Check, ChevronRight, ClipboardList,
  Eye, Filter, Layers, MapPin, RefreshCw, Search, ShieldCheck, Users, X, XCircle,
} from "lucide-react";
import {
  approveAllocationRequest, getActiveAllocation, getAdminOverview, getAllocationRequests,
  getAllocations, getVendorProfile, getZoneCatalog, getZoneGeometry,
  rejectAllocationRequest, updateZoneLiveStatus,
} from "../services/api.js";
import {buildAdminMapModel, uniqueMapPositions} from "../utils/mapGrouping.js";
import {publicVendorId} from "../utils/profileIdentity.js";
import ToastRegion from "./ToastRegion.jsx";
import {useDialogFocus} from "../utils/dialogFocus.js";
import "./AdminDashboard.css";
import "./MapGrouping.css";

const TABS = [
  {id: "overview", label: "Overview", icon: BarChart3},
  {id: "requests", label: "Pending Requests", icon: ClipboardList},
  {id: "zones", label: "Zone Management", icon: Layers},
  {id: "allocations", label: "Allocations", icon: Users},
  {id: "map", label: "Map / Zone Explorer", icon: MapPin},
];
const STATUS_COLORS = {
  OPEN: "#218657", FULL: "#b45309", CLOSED: "#64748b", SUSPENDED: "#b91c1c",
  RESTRICTED: "#7c3aed", NO_VENDING: "#334155",
};
const pretty = value => String(value || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
const display = value => value == null ? "—" : value;
const when = value => value ? new Date(value).toLocaleString() : "—";

function StatusBadge({status}) {
  return <span className={`admin-status status-${String(status).toLowerCase()}`}>{pretty(status)}</span>;
}

function AdminMapFocus({groups, resetVersion}) {
  const map = useMap();
  useEffect(() => {
    const positions = uniqueMapPositions(groups);
    if (!positions.length) return;
    map.invalidateSize({pan: false});
    if (positions.length === 1) map.setView(positions[0], 14, {animate: false});
    else {
      const bounds = L.latLngBounds(positions);
      if (bounds.isValid()) map.fitBounds(bounds, {padding: [32, 32], maxZoom: 14, animate: false});
    }
    const timer = setTimeout(() => map.invalidateSize({pan: false}), 0);
    return () => clearTimeout(timer);
  }, [map, groups, resetVersion]);
  return null;
}

function AdminZoneMap({zones, geometry, onZone}) {
  const [resetVersion, setResetVersion] = useState(0);
  const model = useMemo(() => geometry
    ? buildAdminMapModel(zones, geometry)
    : {groups: [], unavailableZoneIds: [], representedZoneCount: 0}, [zones, geometry]);
  return <div className="admin-map-shell">
    <button className="admin-map-reset" onClick={() => setResetVersion(value => value + 1)}>View all zones</button>
    <MapContainer center={[19.9975, 73.7898]} zoom={12} scrollWheelZoom className="admin-map-canvas">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
      <AdminMapFocus groups={model.groups} resetVersion={resetVersion}/>
      {model.groups.map(group => {const primary = group.zones[0]; return <CircleMarker key={group.key} center={group.position} radius={group.shared ? 7 : 5}
        pathOptions={{color: group.shared ? "#3f586c" : "#fff", weight: group.shared ? 2 : 1.5, fillOpacity: group.shared ? .78 : .82, fillColor: group.shared ? "#718596" : STATUS_COLORS[primary.live_status] || "#64748b"}}>
        <Tooltip direction="top">{group.shared ? `${group.zones.length} zones share this analytical reference` : primary.zone_id}</Tooltip>
        <Popup className="admin-shared-popup" minWidth={group.shared ? 310 : 235}>
          <strong>{group.shared ? "Shared analytical reference" : primary.zone_id}</strong>
          <div className="admin-shared-list">{group.zones.map(zone => <button key={zone.zone_id} onClick={() => onZone(zone)}><span><i style={{background: STATUS_COLORS[zone.live_status] || "#64748b"}}/><b>{zone.zone_id}</b></span><em>{zone.live_status}</em><small>{zone.available_capacity == null ? "Capacity unknown" : `${zone.available_capacity} available`}</small></button>)}</div>
          {group.shared && <p>These official zones share the same analytical GIS reference. They remain separate NMC zone records.</p>}
        </Popup>
      </CircleMarker>;})}
    </MapContainer>
    <div className="admin-map-legend">{Object.keys(STATUS_COLORS).map(status => <span key={status}><i style={{background: STATUS_COLORS[status]}}/>{pretty(status)}</span>)}<span><i className="shared-reference-key"/>Shared reference</span></div>
    <div className="admin-map-disclaimer">Analytical reference points only — not legal zone boundaries · {model.groups.length} locations · {model.representedZoneCount} zones · {model.unavailableZoneIds.length} map references unavailable</div>
  </div>;
}

function DataTable({children}) {
  return <div className="admin-table-wrap"><table className="admin-table">{children}</table></div>;
}

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
    <header className="admin-header"><div className="admin-header-identity"><img src="/nmc-logo.jpg" alt="Nashik Municipal Corporation emblem"/><div><span className="admin-eyebrow">NASHIK MUNICIPAL CORPORATION</span><h1>Operational zoning dashboard</h1><p>Street Vendor Management — Officer Portal</p></div></div><div className="admin-controls"><div className="admin-session-id"><span>Signed in officer</span><strong>{adminId}</strong></div><button onClick={() => refresh("Dashboard data refreshed.")} disabled={loading}><RefreshCw size={15}/>{loading ? "Refreshing…" : "Refresh data"}</button></div></header>
    <div className="admin-demo-note"><InfoIcon/> Officer identity is supplied by the authenticated server session and recorded with administrative actions.</div>
    <nav className="admin-tabs" aria-label="Administration sections">{TABS.map(item => <button key={item.id} className={tab === item.id ? "active" : ""} aria-current={tab === item.id ? "page" : undefined} onClick={() => setTab(item.id)}><item.icon size={16}/>{item.label}{item.id === "requests" && <b>{pending.length}</b>}</button>)}</nav>
    <ToastRegion success={notice} error={error} onDismissSuccess={() => setNotice("")} onDismissError={() => setError("")} retry={() => refresh()}/>
    {loading && !overview && <div className="admin-loading-state" role="status"><RefreshCw size={20}/><div><strong>Loading operational dashboard</strong><span>Retrieving requests, allocations, live zone status, and map references.</span></div></div>}

    {tab === "overview" && <section><div className="admin-section-heading"><div><span className="admin-eyebrow">LIVE OPERATIONS</span><h2>Municipal overview</h2></div><small>Historical associations are not counted as occupancy.</small></div><div className="admin-summary-grid">{summaryCards.map(([label, value, Icon, tone]) => <article className={`admin-summary-card ${tone}`} key={label}><div><span>{label}</span><strong>{value ?? "—"}</strong></div><Icon size={20}/></article>)}</div><div className="admin-overview-panels"><article><h3>Action queue</h3><p><b>{pending.length}</b> allocation requests require officer review.</p><button onClick={() => setTab("requests")}>Open pending requests <ChevronRight size={15}/></button></article><article><h3>Capacity health</h3><p><b>{zoneCounts.FULL || 0}</b> zones are currently full and excluded from vendor recommendations.</p><button onClick={() => {setZoneFilters(current => ({...current, live_status: "FULL"})); setTab("zones");}}>Inspect full zones <ChevronRight size={15}/></button></article><article><h3>Active operations</h3><p><b>{allocationCounts.ACTIVE || 0}</b> confirmed active allocations are stored operationally.</p><button onClick={() => {setAllocationFilter("ACTIVE"); setTab("allocations");}}>View allocations <ChevronRight size={15}/></button></article></div></section>}

    {tab === "requests" && <section><div className="admin-section-heading"><div><span className="admin-eyebrow">OFFICER REVIEW</span><h2>Pending allocation requests</h2></div><span className="admin-count">{pending.length} pending</span></div>{pending.length === 0 ? <div className="admin-empty"><ClipboardList size={28}/><h3>No pending requests</h3><p>New vendor submissions will appear here automatically.</p></div> : <DataTable><thead><tr><th>Request</th><th>Vendor</th><th>Business</th><th>Type</th><th>Current zone</th><th>Selected zone</th><th>Division</th><th>Created</th><th>Target status</th><th>Available</th><th>Actions</th></tr></thead><tbody>{pending.map(request => {const zone = zones.find(item => item.zone_id === request.zone_id); const current = allocations.find(item => item.vendor_id === request.vendor_id && item.status === "ACTIVE"); return <tr key={request.request_id}><td><strong>{request.request_id}</strong></td><td><strong>{request.vendor_name || "Registered Vendor"}</strong><small className="admin-secondary-id">{request.vendor_type === "NEW" ? request.application_vendor_id || "Application ID pending" : request.vendor_id}</small></td><td>{request.business_name || pretty(request.business_category)}</td><td>{pretty(request.request_type)}</td><td>{request.request_type === "RELOCATION" ? current?.zone_id || "—" : "—"}</td><td>{request.zone_id}</td><td>{request.preferred_division || "—"}</td><td>{when(request.created_at)}</td><td><StatusBadge status={zone?.live_status}/></td><td>{display(zone?.available_capacity)}</td><td><div className="table-actions"><button onClick={() => openRequest(request)}><Eye size={14}/> Details</button><button className="approve" onClick={() => setDialog({type: "approve", ...request})}>Approve</button><button className="reject" onClick={() => setDialog({type: "reject", ...request})}>Reject</button></div></td></tr>;})}</tbody></DataTable>}</section>}

    {tab === "zones" && <section><div className="admin-section-heading"><div><span className="admin-eyebrow">OPERATIONAL REGISTRY</span><h2>Zone management</h2></div><span className="admin-count">{filteredZones.length} zones</span></div><div className="admin-filters"><label className="admin-search"><Search size={15}/><input value={zoneFilters.q} onChange={event => setZoneFilters(current => ({...current, q: event.target.value}))} placeholder="Search zone ID or description"/></label><select value={zoneFilters.division} onChange={event => setZoneFilters(current => ({...current, division: event.target.value}))}><option value="">All divisions</option>{divisions.map(item => <option key={item}>{item}</option>)}</select><select value={zoneFilters.zone_type} onChange={event => setZoneFilters(current => ({...current, zone_type: event.target.value}))}><option value="">All zone types</option><option>FREE</option><option>RESTRICTED</option><option>NO_VENDING</option></select><select value={zoneFilters.live_status} onChange={event => setZoneFilters(current => ({...current, live_status: event.target.value}))}><option value="">All live statuses</option>{Object.keys(STATUS_COLORS).map(item => <option key={item}>{item}</option>)}</select></div><DataTable><thead><tr><th>Zone</th><th>Description</th><th>Division</th><th>Type</th><th>Capacity</th><th>Current</th><th>Available</th><th>Live status</th><th>Reference</th><th/></tr></thead><tbody>{filteredZones.map(zone => <tr key={zone.zone_id}><td><strong>{zone.zone_id}</strong></td><td className="description-cell">{zone.official_description}</td><td>{zone.division}</td><td>{pretty(zone.zone_type)}</td><td>{display(zone.official_capacity)}</td><td>{zone.current_vendor_count}</td><td>{display(zone.available_capacity)}</td><td><StatusBadge status={zone.live_status}/></td><td>{pretty(zone.reference_audit_status || "Not audited")}</td><td><button className="row-detail" onClick={() => setSelectedZone(zone)}><ChevronRight size={16}/></button></td></tr>)}</tbody></DataTable></section>}

    {tab === "allocations" && <section><div className="admin-section-heading"><div><span className="admin-eyebrow">CONFIRMED RECORDS</span><h2>Allocations</h2></div><span className="admin-count">{filteredAllocations.length} records</span></div><div className="admin-filters compact"><select value={allocationFilter} onChange={event => setAllocationFilter(event.target.value)}><option value="">All allocations</option><option>ACTIVE</option><option>RELEASED</option></select></div>{filteredAllocations.length === 0 ? <div className="admin-empty"><Users size={28}/><h3>No allocations found</h3></div> : <DataTable><thead><tr><th>Allocation ID</th><th>Vendor</th><th>Zone</th><th>Status</th><th>Allocated</th><th>Released</th><th>Approved by</th><th>Request</th><th>Links</th></tr></thead><tbody>{filteredAllocations.map(item => <tr key={item.allocation_id}><td><strong>{item.allocation_id}</strong></td><td><strong>{item.vendor_name || "Registered Vendor"}</strong><small className="admin-secondary-id">{item.vendor_type === "NEW" ? item.application_vendor_id || "Application ID pending" : item.vendor_id}</small></td><td>{item.zone_id}</td><td><StatusBadge status={item.status}/></td><td>{when(item.allocated_at)}</td><td>{when(item.released_at)}</td><td>{item.approved_by || "—"}</td><td>{item.request_id || "—"}</td><td><div className="table-actions"><button onClick={async () => {try {const vendor = await getVendorProfile(item.vendor_id); setRequestDetail({vendor, active: item, request: null, zone: zones.find(zone => zone.zone_id === item.zone_id)});} catch (err) {setError(err.message);}}}>Vendor</button><button onClick={() => setSelectedZone(zones.find(zone => zone.zone_id === item.zone_id))}>Zone</button></div></td></tr>)}</tbody></DataTable>}</section>}

    {tab === "map" && <section><div className="admin-section-heading"><div><span className="admin-eyebrow">ZONE EXPLORER</span><h2>All-zone operational map</h2><p>Search and filter all canonical zone records. Zones without usable references remain available in the registry.</p></div><span className="admin-count">{mappedZones.length} mapped records</span></div><div className="admin-filters map-explorer-filters"><label className="admin-search"><Search size={15}/><input value={zoneFilters.q} onChange={event => setZoneFilters(current => ({...current, q: event.target.value}))} placeholder="Search zone ID or description"/></label><select value={zoneFilters.division} onChange={event => setZoneFilters(current => ({...current, division: event.target.value}))}><option value="">All divisions</option>{divisions.map(item => <option key={item}>{item}</option>)}</select><select value={zoneFilters.zone_type} onChange={event => setZoneFilters(current => ({...current, zone_type: event.target.value}))}><option value="">All zone types</option><option>FREE</option><option>RESTRICTED</option><option>NO_VENDING</option></select></div><div className="map-status-filters">{Object.keys(STATUS_COLORS).map(status => <label key={status}><input type="checkbox" checked={mapStatuses.includes(status)} onChange={() => setMapStatuses(current => current.includes(status) ? current.filter(item => item !== status) : [...current, status])}/><i style={{background: STATUS_COLORS[status]}}/>{pretty(status)}</label>)}</div><AdminZoneMap zones={mappedZones} geometry={geometry} onZone={setSelectedZone}/></section>}

    {requestDetail && <div className="admin-drawer-backdrop" onClick={() => setRequestDetail(null)}><aside className="admin-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close" onClick={() => setRequestDetail(null)}><X size={18}/></button><span className="admin-eyebrow">{requestDetail.request ? "REQUEST DETAILS" : "VENDOR & ALLOCATION"}</span><h2>{requestDetail.request?.request_id || publicVendorId(requestDetail.vendor)}</h2>{requestDetail.request && <StatusBadge status={requestDetail.request.status}/>}<div className="drawer-grid"><div><span>{requestDetail.vendor.vendor_type === "NEW" ? "Application Vendor ID" : "Vendor ID"}</span><strong>{publicVendorId(requestDetail.vendor)}</strong></div><div><span>Vendor type</span><strong>{pretty(requestDetail.vendor.vendor_type)}</strong></div><div><span>Business</span><strong>{pretty(requestDetail.request?.business_category || requestDetail.vendor.business_category)}</strong></div><div><span>Priority</span><strong>{pretty(requestDetail.vendor.priority_profile)}</strong></div><div><span>Request type</span><strong>{pretty(requestDetail.request?.request_type || "—")}</strong></div><div><span>Created</span><strong>{when(requestDetail.request?.created_at)}</strong></div><div><span>Current zone</span><strong>{requestDetail.active?.zone_id || "None"}</strong></div><div><span>Target zone</span><strong>{requestDetail.zone?.zone_id || "—"}</strong></div><div><span>Division</span><strong>{requestDetail.zone?.division || "—"}</strong></div><div><span>Live status</span><strong>{requestDetail.zone?.live_status || "—"}</strong></div><div><span>Official capacity</span><strong>{display(requestDetail.zone?.official_capacity)}</strong></div><div><span>Current vendors</span><strong>{display(requestDetail.zone?.current_vendor_count)}</strong></div><div><span>Available</span><strong>{display(requestDetail.zone?.available_capacity)}</strong></div></div>{requestDetail.zone && <p className="drawer-description">{requestDetail.zone.official_description}</p>}{requestDetail.request && <div className="drawer-actions"><button className="admin-approve" onClick={() => setDialog({type: "approve", ...requestDetail.request})}>Approve request</button><button className="admin-reject" onClick={() => setDialog({type: "reject", ...requestDetail.request})}>Reject request</button></div>}</aside></div>}

    {selectedZone && <div className="admin-drawer-backdrop" onClick={() => setSelectedZone(null)}><aside className="admin-drawer" onClick={event => event.stopPropagation()}><button className="drawer-close" onClick={() => setSelectedZone(null)}><X size={18}/></button><span className="admin-eyebrow">ZONE DETAILS</span><h2>{selectedZone.zone_id}</h2><StatusBadge status={selectedZone.live_status}/><p className="drawer-description">{selectedZone.official_description}</p><div className="drawer-grid"><div><span>Division</span><strong>{selectedZone.division}</strong></div><div><span>Policy type</span><strong>{pretty(selectedZone.zone_type)}</strong></div><div><span>Official capacity</span><strong>{display(selectedZone.official_capacity)}</strong></div><div><span>Current vendors</span><strong>{selectedZone.current_vendor_count}</strong></div><div><span>Available</span><strong>{display(selectedZone.available_capacity)}</strong></div><div><span>Reference status</span><strong>{pretty(selectedZone.reference_audit_status || "Not audited")}</strong></div><div><span>Active allocations</span><strong>{allocations.filter(item => item.zone_id === selectedZone.zone_id && item.status === "ACTIVE").length}</strong></div><div><span>Pending requests</span><strong>{pending.filter(item => item.zone_id === selectedZone.zone_id).length}</strong></div></div>{selectedZone.zone_type === "FREE" ? <div className="zone-status-actions"><span>Manual operational status</span><p>FULL remains capacity-derived. Opening a zero-capacity zone keeps it FULL.</p><div>{["OPEN", "CLOSED", "SUSPENDED"].map(status => <button key={status} disabled={loading || selectedZone.live_status === status} onClick={() => changeStatus(status)}>{status}</button>)}</div></div> : <div className="policy-lock"><ShieldCheck size={17}/> Policy-controlled {pretty(selectedZone.zone_type)} zones cannot be changed here.</div>}</aside></div>}

    {dialog && <div className="admin-modal-backdrop" onClick={() => setDialog(null)}><div className="admin-modal" onClick={event => event.stopPropagation()}><div className={`modal-icon ${dialog.type}`} >{dialog.type === "approve" ? <Check size={24}/> : <XCircle size={24}/>}</div><span className="admin-eyebrow">{dialog.type === "approve" ? "CONFIRM APPROVAL" : "REJECT REQUEST"}</span><h2>{dialog.type === "approve" ? `Approve allocation to ${dialog.zone_id}?` : `Reject ${dialog.request_id}?`}</h2>{dialog.type === "approve" && <p>This will create an ACTIVE allocation and update the zone’s live occupancy atomically.</p>}{dialog.type === "reject" && <label><span>Rejection reason *</span><textarea value={reason} onChange={event => setReason(event.target.value)} placeholder="Explain why this request cannot be approved"/></label>}<label><span>Officer notes <small>optional</small></span><textarea value={notes} onChange={event => setNotes(event.target.value)} placeholder="Internal review note"/></label><div className="modal-capacity"><span>Current occupancy</span><strong>{zones.find(zone => zone.zone_id === dialog.zone_id)?.current_vendor_count ?? "—"}</strong><span>Available before review</span><strong>{display(zones.find(zone => zone.zone_id === dialog.zone_id)?.available_capacity)}</strong></div><div className="modal-actions"><button onClick={() => setDialog(null)}>Cancel</button><button className={dialog.type === "approve" ? "admin-approve" : "admin-reject"} onClick={dialog.type === "approve" ? approve : reject} disabled={loading}>{dialog.type === "approve" ? "Approve allocation" : "Reject request"}</button></div></div></div>}
    {statusTarget && <div className="admin-modal-backdrop" onClick={() => setStatusTarget(null)}><div className="admin-modal" role="dialog" aria-modal="true" aria-labelledby="zone-status-title" onClick={event => event.stopPropagation()}><div className="modal-icon approve"><ShieldCheck size={24}/></div><span className="admin-eyebrow">CONFIRM STATUS CHANGE</span><h2 id="zone-status-title">Change {statusTarget.zone_id} to {pretty(statusTarget.status)}?</h2><p>{statusTarget.status === "OPEN" ? "This will reopen the zone for operational use. Capacity rules still apply." : `This will remove the zone from live vendor recommendations while it is ${statusTarget.status.toLowerCase()}.`}</p><div className="modal-capacity"><span>Current status</span><strong>{pretty(statusTarget.from)}</strong><span>New status</span><strong>{pretty(statusTarget.status)}</strong></div><div className="modal-actions"><button onClick={() => setStatusTarget(null)}>Keep current status</button><button className={statusTarget.status === "OPEN" ? "admin-approve" : "admin-reject"} onClick={() => applyStatus(statusTarget.status)} disabled={loading}>Confirm change</button></div></div></div>}
  </main>;
}

function InfoIcon() { return <AlertTriangle size={15}/>; }
