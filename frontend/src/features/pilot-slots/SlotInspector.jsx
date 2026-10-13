import React, {useState} from "react";
import {categoryLabel, statusLabel} from "../../i18n/index.js";
import {useI18n} from "../../i18n/react.jsx";
import {publicSlotCategory} from "./slotPresentation.js";

export default function SlotInspector({selected, slots, selectedId, onSelect, admin, assigned, allocations, ownBusinessCategory, onViewVendor, children}) {
  const [expanded,setExpanded] = useState(false);
  const {language} = useI18n();
  const allocation = admin && selected?.assigned_vendor_id ? allocations.find(a => a.vendor_id === selected.assigned_vendor_id && a.zone_id === "NN_F_013" && a.status === "ACTIVE") : null;
  const category = admin ? allocation?.business_category || selected?.public_business_category : publicSlotCategory(selected,assigned?.slot_id,ownBusinessCategory);
  return <aside className={`pilot-details slot-inspector ${expanded ? "is-expanded" : ""}`} aria-label="Selected slot inspector">
    <button className="slot-sheet-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Less detail" : "More details"}<span aria-hidden="true">{expanded ? "⌄" : "⌃"}</span></button>
    <div className="slot-inspector-basic" aria-live="polite"><span className="slot-context-label">{selected?.slot_id === assigned?.slot_id ? "Selected slot · My assigned slot" : "Selected slot"}</span>
      <div className="slot-inspector-title"><h3>{selected?.slot_id || "Choose a slot"}</h3>{selected && <span className={`pilot-status slot-status-${selected.status.toLowerCase()}`}>{statusLabel(language,selected.status)}</span>}</div>
      <strong className="slot-zone-name">Lekha Nagar · Balbharati Office</strong><small>New Nashik · NN_F_013</small>
      {!admin && assigned && selected?.slot_id !== assigned.slot_id && <small className="slot-my-assignment">My assigned slot: {assigned.slot_id}</small>}
      {selected && <p className="slot-basic-meta">{selected.width_m ?? 2} × {selected.depth_m ?? 2} m · {category ? categoryLabel(language,category) : "Business category not provided"}</p>}
    </div>
    <div className="slot-inspector-extra"><label>Selected slot<select aria-label="Select pilot slot" value={selectedId || ""} onChange={e => {const slot = slots.find(s => s.slot_id === e.target.value); if(slot) onSelect(slot);}}><option value="">Select a slot</option>{slots.map(s => <option key={s.slot_id} value={s.slot_id}>{s.slot_id} · {s.status}</option>)}</select></label>
      {!admin && assigned && <p className="slot-own-note">My assigned slot: <strong>{assigned.slot_id}</strong>. Inspecting another slot does not change your assignment.</p>}
      {!selected ? <p>Click a numbered polygon or select a slot above.</p> : <><dl><div><dt>Location evidence</dt><dd>{selected.geometry ? "Provisional, not surveyed" : "Illustrative schematic"}</dd></div>{admin && <><div><dt>Assigned vendor</dt><dd>{allocation?.vendor_name || selected.assigned_vendor_id || "None"}</dd></div>{allocation && <div><dt>Approved allocation</dt><dd>{allocation.allocation_id}</dd></div>}</>}</dl>
        {admin && allocation && onViewVendor && <button onClick={() => onViewVendor(allocation)}>View authorized vendor details</button>}
        {children}
      </>}
    </div>
  </aside>;
}
