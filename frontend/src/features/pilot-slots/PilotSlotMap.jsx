import SlotInspector from "./SlotInspector.jsx";
import {googleWalkingLink} from "./slotPresentation.js";
import React, {useEffect, useReducer, useState, useRef} from "react";
import {CircleMarker, GeoJSON, MapContainer, Marker, Popup, TileLayer, Tooltip} from "react-leaflet";
import L from "leaflet";
import {getPilotLayout, initializePilotLayout, updatePilotSlot, previewPilotGeometry, validatePilotGeometry, savePilotGeometry, getPilotDestination} from "../../services/api.js";
import {initialPilotState, pilotReducer} from "./pilotState.js";
import {geographicCenter} from "../navigation/pilotNavigation.js";
import "./PilotSlotMap.css";
import "./SlotWorkspace.css";

const COLORS = {AVAILABLE: "#218657", OCCUPIED: "#c43e3e", RESERVED: "#e5b93b", BLOCKED: "#788491"};
const NAMES = {"2974": "Boundary A", "3577": "Boundary B"};
const CONFIG = {spacing_m: .5, clearance_m: 1.2, boundaries: {"2974": {side: "left", angle: null}, "3577": {side: "left", angle: null}}};
const handleIcon = L.divIcon({className: "pilot-drag-handle", html: "↔", iconSize: [30, 30], iconAnchor: [15, 15]});
const ll = p => [p[1], p[0]];

import MapLifecycle from "./MapLifecycle.jsx";

export default function PilotSlotMap({admin = false, visible = true, onBack, allocations = [], ownBusinessCategory, onViewVendor, session, dispatch: externalDispatch}) {
  const [local, localDispatch] = useReducer(pilotReducer, initialPilotState);
  const {layout, selectedId} = session || local, dispatch = externalDispatch || localDispatch;
  const [draft, setDraft] = useState(null), [config, setConfig] = useState(CONFIG), [boundaryId, setBoundaryId] = useState("2974");
  const [status, setStatus] = useState("AVAILABLE"), [vendorId, setVendorId] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [reviewed, setReviewed] = useState(false), [command, setCommand] = useState(null), [clickMode, setClickMode] = useState(null), [angle, setAngle] = useState(0);
  const [obstructionNote, setObstructionNote] = useState(""), [obstructionRadius, setObstructionRadius] = useState(.5);
  const [accessNote, setAccessNote] = useState(""), [accessObserved, setAccessObserved] = useState(false);
  const moveMap = kind => setCommand({kind, id: Date.now() + Math.random()});
  const [destination,setDestination] = useState(null), [infoOpen,setInfoOpen] = useState(false), [toolsOpen,setToolsOpen] = useState(false), [showLayers,setShowLayers] = useState(true);
  const workspaceRef = useRef(null), [workspaceHeight,setWorkspaceHeight] = useState(600);
  useEffect(() => {
    if (!visible) return;
    const resize = () => {if(workspaceRef.current) setWorkspaceHeight(Math.max(window.innerWidth <= 760 ? 460 : 320,window.innerHeight - workspaceRef.current.getBoundingClientRect().top - 16));};
    const timer = setTimeout(resize,0); window.addEventListener("resize",resize);
    return () => {clearTimeout(timer);window.removeEventListener("resize",resize);};
  }, [visible,layout,draft]);
  const shown = draft || layout, selected = shown?.slots.find(s => s.slot_id === selectedId), assigned = layout?.slots.find(s => s.slot_id === layout.my_slot_id);
  const slots = shown?.georeferenced ? shown.slots : [], protectedSlot = selected?.assigned_vendor_id || selected?.status === "OCCUPIED";
  const select = slot => {dispatch({type: "select", slotId: slot.slot_id}); if (slot.parent_boundary_id) setBoundaryId(slot.parent_boundary_id);};
  const run = async action => {setBusy(true); setError(""); try {return await action();} catch (e) {setError(e.message); return null;} finally {setBusy(false);}};
  const load = () => run(async () => {const data = await (admin ? initializePilotLayout() : getPilotLayout()); dispatch({type: "loaded", layout: data}); setConfig(data.config || CONFIG); if (!admin) setDestination(await getPilotDestination());});
  useEffect(() => {load();}, [admin]);
  useEffect(() => {setStatus(selected?.status || "AVAILABLE"); setVendorId(selected?.assigned_vendor_id || ""); setAngle(selected?.pose?.angle || 0);}, [selected]);
  const preview = () => run(async () => {setDraft(await previewPilotGeometry(config, draft?.obstructions)); setReviewed(false); moveMap("slots"); setNotice("Unsaved preview. Review positions, corridor side and unresolved site restrictions.");});
  const beginEdit = () => {const copy = structuredClone(layout); copy.expected_revision = layout.revision; copy.expected_versions = Object.fromEntries(layout.slots.map(s => [s.slot_id, s.updated_at])); setDraft(copy); setReviewed(false); setNotice("Draft edit: drag the selected slot's centre handle. Dimensions stay fixed in metres.");};
  const validateDraft = (next, poses = {}) => run(async () => {const valid = await validatePilotGeometry(next, poses); setDraft(valid); setReviewed(false); return valid;});
  const saveDraft = () => run(async () => {const saved = await savePilotGeometry(draft); dispatch({type: "loaded", layout: saved}); setDraft(null); setClickMode(null); setNotice("Validated provisional layout saved; operational allocations unchanged.");});
  const saveStatus = (release = false) => run(async () => {const slot = await updatePilotSlot(selected.slot_id, {status: release ? "AVAILABLE" : status, assigned_vendor_id: release ? null : vendorId || null, expected_updated_at: selected.updated_at}); dispatch({type: "updated", slot}); setNotice(`${slot.slot_id} demonstration updated.`);});
  const mapClick = async p => {
    if (!draft || !clickMode || busy) return;
    const next = clickMode === "access" ? {...draft, access_points: {...draft.access_points, [boundaryId]: {longitude: p.lng, latitude: p.lat, observed: accessObserved, note: accessNote}}}
      : {...draft, obstruction_request: {longitude: p.lng, latitude: p.lat, radius_m: Number(obstructionRadius), note: obstructionNote}};
    if (await validateDraft(next)) setClickMode(null);
  };
  const mapsLink = !admin ? googleWalkingLink(destination,assigned?.slot_id) : null;
  const eligible = allocations.filter(a => a.zone_id === "NN_F_013" && a.status === "ACTIVE" && a.request_id);
  return <section className={`pilot-panel pilot-geographic ${admin ? "pilot-admin" : "pilot-vendor"}`} hidden={!visible} aria-label="Lekha Nagar geographic pilot">
    <header className="pilot-header"><div><h2>Lekha Nagar - Slot map</h2><span>Balbharati Office - New Nashik <small> - NN_F_013</small></span></div><button onClick={onBack}>{admin ? "Back to All Zones" : "Back to Dashboard"}</button></header>
    <p className="slot-provisional-warning">Provisional positions - not surveyed or authorized on-ground slots.</p>
    {error && <div className="pilot-error" role="alert">{error} <button disabled={busy || Boolean(draft)} onClick={load}>Reload saved layout</button></div>}{notice && <p role="status">{notice}</p>}{busy && !layout && <p role="status">Loading proposed boundaries…</p>}
    {layout && <>
      {!shown.georeferenced && <p className="pilot-assignment">Imported proposed boundaries are shown. {admin ? "Generate a reviewed geographic layout. Assigned or occupied legacy slots must be explicitly released before replacement." : "Geographic layout review is pending; schematic slots cannot be navigation destinations."}</p>}
      {draft && <div className="pilot-draft-banner"><strong>UNSAVED PREVIEW · {draft.slots.length} slots · {draft.validation?.valid ? "Geometry checks passed" : draft.validation?.reason || "Validation required"}</strong>{!draft.validation?.valid && <button onClick={preview} disabled={busy}>Regenerate around observations</button>}<label><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/> I reviewed the provisional positions and assumptions.</label><button disabled={busy || !reviewed || !draft.validation?.valid} onClick={saveDraft}>Save reviewed layout</button><button disabled={busy} onClick={() => {setDraft(null); setClickMode(null); setError("");}}>Cancel without saving</button></div>}
      <div ref={workspaceRef} style={{"--slot-workspace-height":`${workspaceHeight}px`}} className="pilot-workspace"><div className="pilot-visual"><div className="pilot-map-frame">
        <div className="slot-map-controls"><button onClick={() => moveMap("all")}>Recenter map</button><button disabled={!selected?.geometry} onClick={() => moveMap("slot")}>Zoom to selected slot</button>{!admin && assigned && <button onClick={() => {select(assigned); setCommand({kind:"own",id:Date.now()});}}>View My Slot</button>}<button aria-pressed={showLayers} onClick={() => setShowLayers(!showLayers)}>Site layers</button><button aria-expanded={infoOpen} onClick={() => {setInfoOpen(!infoOpen);setToolsOpen(false);}}>Map information</button>{mapsLink && <a href={mapsLink} target="_blank" rel="noopener noreferrer">Google Maps - my access point</a>}{admin && <button aria-expanded={toolsOpen} onClick={() => {setToolsOpen(!toolsOpen);setInfoOpen(false);}}>Layout tools</button>}</div>
        {infoOpen && <div className="slot-map-information"><strong>Map information</strong><p>User-drawn boundaries, corridor side and obstructions require site review. Nearby no-vending restrictions remain unresolved.</p><p>WGS84 display - UTM 43N metre validation. Enlarged tiles at zoom 20?22 add no survey precision.</p>{shown.rejections?.map(r => <p key={r.boundary_id}>{NAMES[r.boundary_id]}: {r.generated}/{r.requested}. {r.reason}</p>)}{!admin && <p>In-app turn-by-turn navigation is paused. External directions are offered only to an administrator-recorded pedestrian access point for your own assignment; access still requires site verification.</p>}{admin && <button disabled={busy || Boolean(draft)} onClick={load}>Refresh saved layout</button>}</div>}
{admin && toolsOpen && <div className="slot-tools-popover"><div className="pilot-generation"><label>Boundary<select value={boundaryId} onChange={e => setBoundaryId(e.target.value)}>{Object.entries(NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><label>Assumed corridor side<select value={config.boundaries[boundaryId].side} disabled={Boolean(draft)} onChange={e => setConfig(c => ({...c, boundaries: {...c.boundaries, [boundaryId]: {...c.boundaries[boundaryId], side: e.target.value}}}))}><option value="left">Left of alignment (conceptual)</option><option value="right">Right of alignment (conceptual)</option></select></label><label>UTM alignment degrees<input type="number" min="0" max="180" step=".1" disabled={Boolean(draft)} placeholder="Auto: polygon long axis" value={config.boundaries[boundaryId].angle ?? ""} onChange={e => setConfig(c => ({...c, boundaries: {...c.boundaries, [boundaryId]: {...c.boundaries[boundaryId], angle: e.target.value === "" ? null : Number(e.target.value)}}}))}/></label><button disabled={busy || Boolean(draft)} onClick={preview}>Generate geographic preview</button><button disabled={busy || Boolean(draft) || !layout.georeferenced} onClick={beginEdit}>Edit Slot Layout</button></div></div>}
        <div className="slot-map-legend">{Object.entries(COLORS).map(([name,color]) => <span key={name}><i style={{background:color}}/>{name.toLowerCase()}</span>)}<span><i className="slot-selected-key"/>Selected</span>{!admin && <span><i className="slot-own-key"/>My slot</span>}</div>
        <MapContainer center={[19.974, 73.7725]} zoom={17} maxZoom={22} className="pilot-context-map" scrollWheelZoom>
          <TileLayer maxNativeZoom={19} maxZoom={22} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
          <MapLifecycle visible={visible} boundaries={shown.boundaries} slots={slots} command={command} selected={selected} assigned={assigned} boundaryId={boundaryId} onPan={() => {}} onClick={mapClick}/>
          {showLayers && shown.boundaries?.features.map(f => <GeoJSON key={`boundary-${f.properties.boundary_id}`} data={f} style={{color: "#687b8b", weight: 2, fillOpacity: .04, dashArray: "6 5"}} eventHandlers={{click: () => setBoundaryId(f.properties.boundary_id)}}><Tooltip>{f.properties.name} · proposed, not surveyed</Tooltip></GeoJSON>)}
          {showLayers && shown.corridors?.map(c => <GeoJSON key={`corridor-${JSON.stringify(c.geometry)}`} data={c.geometry} style={{color: "#347d95", weight: 1, fillColor: "#73c4db", fillOpacity: .2}}><Tooltip>Continuous {shown.clearance_m} m corridor · assumed side</Tooltip></GeoJSON>)}
          {slots.map(slot => <GeoJSON key={`${slot.slot_id}-${JSON.stringify(slot.geometry)}-${slot.status}`} data={slot.geometry} style={{color: selectedId === slot.slot_id ? "#142e50" : slot.slot_id === layout.my_slot_id ? "#086c72" : "#fff", dashArray: slot.slot_id === layout.my_slot_id ? "5 2" : undefined, weight: selectedId === slot.slot_id || slot.slot_id === layout.my_slot_id ? 4 : 1.5, fillColor: COLORS[slot.status], fillOpacity: .8, className: `pilot-slot-polygon pilot-slot-${slot.slot_id} ${slot.slot_id === layout.my_slot_id ? "pilot-assigned-polygon" : ""}`}} eventHandlers={{click: e => {L.DomEvent.stopPropagation(e); select(slot);}}}><Tooltip permanent direction="center" className={`pilot-map-label ${slot.slot_id === layout.my_slot_id ? "pilot-label-assigned" : selectedId === slot.slot_id ? "pilot-label-focused" : ""}`}>{slot.slot_id}</Tooltip></GeoJSON>)}
          {showLayers && shown.obstructions?.map((o, i) => <GeoJSON key={`obstruction-${i}-${JSON.stringify(o.geometry)}`} data={o.geometry} style={{color: "#a52828", weight: 2, fillOpacity: .5}}><Tooltip>Observed obstruction: {o.note || "No note"}</Tooltip></GeoJSON>)}
          {showLayers && Object.entries(shown.access_points || {}).map(([id, p]) => <CircleMarker key={`access-${id}-${p.longitude}`} center={[p.latitude, p.longitude]} radius={6} pathOptions={{color: "#783fab", fillOpacity: .8}}><Popup>{NAMES[id]} approach · {p.observed ? "admin-recorded observation" : "unverified"}<br/>{p.note}</Popup></CircleMarker>)}
          {draft && selected?.geometry && !protectedSlot && <Marker icon={handleIcon} draggable position={ll(geographicCenter(selected.geometry))} eventHandlers={{dragend: e => {const p = e.target.getLatLng(); e.target.setLatLng(ll(geographicCenter(selected.geometry))); validateDraft(structuredClone(draft), {[selected.slot_id]: {longitude: p.lng, latitude: p.lat, angle: selected.pose.angle}});}}}/>}
        </MapContainer>
      </div></div>
      <SlotInspector selected={selected} selectedId={selectedId} slots={shown.slots} onSelect={select} admin={admin} assigned={assigned} allocations={allocations} ownBusinessCategory={ownBusinessCategory} onViewVendor={onViewVendor}>
        {selected && admin && !draft && <form onSubmit={e => {e.preventDefault(); saveStatus();}}><label>Demo status<select value={status} onChange={e => {setStatus(e.target.value); if (["AVAILABLE", "BLOCKED"].includes(e.target.value)) setVendorId("");}}>{Object.keys(COLORS).map(s => <option key={s}>{s}</option>)}</select></label><label>Approved pilot vendor<select value={vendorId} disabled={!["RESERVED", "OCCUPIED"].includes(status)} onChange={e => setVendorId(e.target.value)}><option value="">No linked vendor</option>{selected.assigned_vendor_id && !eligible.some(a => a.vendor_id === selected.assigned_vendor_id) && <option value={selected.assigned_vendor_id}>{selected.assigned_vendor_id} · eligibility changed</option>}{eligible.map(a => <option key={a.allocation_id} value={a.vendor_id}>{a.vendor_name || a.vendor_id}</option>)}</select></label><small>New assignments require a saved AVAILABLE slot and an approved NN_F_013 allocation.</small><button disabled={busy}>Save demonstration slot</button>{selected.assigned_vendor_id && <button type="button" disabled={busy} onClick={() => saveStatus(true)}>Release demo assignment</button>}</form>}
        {admin && draft && <div className="pilot-edit-controls">{protectedSlot ? <p>Assigned/occupied position is locked. Explicitly release its demo assignment/status before editing geometry.</p> : <><label>Rotation degrees<input type="number" value={angle} onChange={e => setAngle(Number(e.target.value))}/></label><button disabled={busy} onClick={() => validateDraft(structuredClone(draft), {[selected.slot_id]: {...selected.pose, angle}})}>Apply Rotation</button><button disabled={busy} onClick={() => validateDraft({...draft, slots: draft.slots.filter(s => s.slot_id !== selected.slot_id)})}>Delete proposed slot from draft</button></>}</div>}
        {admin && draft && <div className="pilot-edit-controls"><h4>Observed site information</h4><label>Obstruction note<input maxLength={300} value={obstructionNote} onChange={e => setObstructionNote(e.target.value)}/></label><label>Obstruction radius (m)<input type="number" min=".1" max="10" step=".1" value={obstructionRadius} onChange={e => setObstructionRadius(e.target.value)}/></label><button onClick={() => setClickMode("obstruction")}>Record obstruction on map</button><label>Pedestrian approach note<input maxLength={300} value={accessNote} onChange={e => setAccessNote(e.target.value)}/></label><label><input type="checkbox" checked={accessObserved} onChange={e => setAccessObserved(e.target.checked)}/> Approach observed on site (not municipal verification)</label><button onClick={() => setClickMode("access")}>Set boundary access point on map</button>{clickMode && <p role="status">Click the map to place the {clickMode === "access" ? "approach point" : "obstruction"}. Invalid placements are rejected.</p>}{draft.obstructions?.length > 0 && <button onClick={() => validateDraft({...draft, obstructions: draft.obstructions.slice(0, -1)})}>Remove last obstruction from draft</button>}</div>}
      {!admin && <div className="slot-own-access"><span>{assigned ? `My assigned slot: ${assigned.slot_id}` : "No vending slot has been assigned yet."}</span>{mapsLink ? <a href={mapsLink} target="_blank" rel="noopener noreferrer">Open in Google Maps - recorded access point</a> : <small>No observed pedestrian access point configured; external directions unavailable.</small>}</div>}
      </SlotInspector>
      </div>

    </>}
  </section>;
}
