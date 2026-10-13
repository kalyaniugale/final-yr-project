import React, {useEffect, useMemo, useState} from "react";
import {CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap} from "react-leaflet";
import L from "leaflet";

import {buildAdminMapModel, uniqueMapPositions} from "../../shared/utils/mapGrouping.js";

import {STATUS_COLORS, pretty} from "./viewModel.js";

export function AdminMapFocus({groups, resetVersion}) {
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

export function AdminZoneMap({zones, geometry, onZone}) {
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

