import React, {useEffect, useMemo, useRef, useState} from "react";
import {CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap} from "react-leaflet";
import L from "leaflet";
import {MapPin} from "lucide-react";
import {getZoneGeometry} from "../../services/api.js";
import {buildVendorExplorerMapModel, uniqueMapPositions, vendorVisibleContextZones} from "../../shared/utils/mapGrouping.js";

import {useI18n} from "../../i18n/react.jsx";

import {statusLabel} from "../../i18n/index.js";

import {RANK_COLORS, score} from "./viewModel.js";

export function MapFocus({groups, selectedId, markerRefs}) {
  const map = useMap();
  useEffect(() => {
    const positions = uniqueMapPositions(groups);
    if (!positions.length) return;
    map.invalidateSize({pan: false});
    if (positions.length === 1) map.setView(positions[0], 14, {animate: false});
    else {
      const bounds = L.latLngBounds(positions);
      if (bounds.isValid()) map.fitBounds(bounds, {padding: [35, 35], maxZoom: 14, animate: false});
    }
    const timer = setTimeout(() => map.invalidateSize({pan: false}), 0);
    return () => clearTimeout(timer);
  }, [map, groups]);
  useEffect(() => {
    const selected = groups.find(group => group.zones.some(zone => zone.zone_id === selectedId));
    if (selected) {
      map.flyTo(selected.position, Math.max(map.getZoom(), 14), {duration: .35});
      markerRefs.current.get(selected.key)?.openPopup();
    }
  }, [map, groups, selectedId, markerRefs]);
  return null;
}

export function RecommendationMap({recommendations, context, selectedId, onFocus, onSelect, onGeometryStatus}) {
  const {language, t} = useI18n();
  const [geometry, setGeometry] = useState(null);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const markerRefs = useRef(new Map());
  useEffect(() => {
    getZoneGeometry().then(setGeometry).catch(err => setError(err.message));
  }, []);
  const visibleContextZones = useMemo(() => vendorVisibleContextZones(context, showAll), [showAll, context]);
  const model = useMemo(() => geometry
    ? buildVendorExplorerMapModel(recommendations, visibleContextZones, geometry)
    : {groups: [], unavailableZoneIds: [], representedZoneCount: 0}, [geometry, recommendations, visibleContextZones]);
  useEffect(() => {
    onGeometryStatus?.(geometry ? model.unavailableZoneIds : null);
  }, [geometry, model.unavailableZoneIds, onGeometryStatus]);
  return <div className="vendor-map-wrap" id="vendor-recommendation-map">
    {error && <div className="vendor-inline-error">{t("recommend.mapError", {message: error})}</div>}
    <div className="vendor-map-toolbar"><div><strong>{t("recommend.mapTitle")}</strong><span>{showAll ? t("recommend.allZonesHelp") : t("recommend.recommendationsHelp")}</span></div><button className="vendor-secondary" onClick={() => setShowAll(value => !value)}>{t(showAll ? "recommend.showRecommendations" : "recommend.viewAllZones")}</button></div>
    <div className="map-recommendation-index" aria-label={t("recommend.mapIndexLabel")}>{recommendations.map(zone => <button key={zone.zone_id} className={selectedId === zone.zone_id ? "active" : ""} aria-pressed={selectedId === zone.zone_id} onClick={() => (onFocus || onSelect)(zone.zone_id)}><b style={{background: RANK_COLORS[zone.rank]}}>{zone.rank}</b><span>{zone.zone_id}</span><small>{score(zone.score)}</small></button>)}</div>
    <MapContainer center={[19.9975, 73.7898]} zoom={12} scrollWheelZoom={false} className="vendor-map">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
      <MapFocus groups={model.groups} selectedId={selectedId} markerRefs={markerRefs}/>
      {model.groups.map(group => {const selected = group.zones.some(zone => zone.zone_id === selectedId); const primary = group.zones[0]; const recommendationRanks = group.zones.filter(zone => zone.is_recommendation).map(zone => zone.rank).sort((left, right) => left - right); const recommended = recommendationRanks.length > 0; const markerLabel = recommendationRanks.length > 1 ? recommendationRanks.join(" · ") : recommendationRanks[0] ?? group.zones.length; const current = group.zones.some(zone => zone.zone_id === context?.current_zone_id); const pending = group.zones.some(zone => zone.zone_id === context?.pending_zone_id); const available = group.zones.some(zone => zone.eligible !== false); return <CircleMarker
        key={group.key}
        ref={marker => {if (marker) markerRefs.current.set(group.key, marker); else markerRefs.current.delete(group.key);}}
        center={group.position}
        radius={selected ? 15 : recommended ? 12 : group.shared ? 9 : 6}
        pathOptions={{color: selected ? "#0f2e48" : "#fff", weight: selected ? 4 : 2, dashArray: pending ? "3 2" : undefined, fillOpacity: recommended || current || pending ? 1 : .45, fillColor: current ? "#287b78" : pending ? "#b46a18" : recommended ? RANK_COLORS[primary.rank] || "#174b77" : available ? "#778b9b" : "#aeb7bf"}}
      >
        {(recommended || group.shared) ? <Tooltip permanent direction="center" className={`rank-tooltip ${recommendationRanks.length > 1 ? "shared-ranks" : ""} ${!recommended ? "subtle-count" : ""}`}>{markerLabel}</Tooltip> : <Tooltip>{primary.zone_id}</Tooltip>}
        <Popup className="shared-reference-popup" minWidth={group.shared ? 285 : 220}>
          <strong>{group.shared ? t("recommend.shared") : t("recommend.rankReference", {rank: primary.rank})}</strong>
          <div className="shared-zone-list">{group.zones.map(zone => <button key={zone.zone_id} onClick={() => onSelect(zone.zone_id)}><b>{zone.is_recommendation ? `#${zone.rank}` : "•"}</b><span>{zone.zone_id}</span><em>{zone.is_recommendation ? score(zone.score) : zone.zone_id === context?.current_zone_id ? t("recommend.currentLegend") : zone.zone_id === context?.pending_zone_id ? t("recommend.pendingLegend") : statusLabel(language, zone.live_status)}</em></button>)}</div>
          {group.shared && <p>{t("recommend.sharedNotice")}</p>}
          {!group.shared && <small>{t("recommend.availableCapacity", {capacity: primary.available_capacity == null ? t("common.notSpecified") : primary.available_capacity})}</small>}
        </Popup>
      </CircleMarker>;})}
    </MapContainer>
    <div className="vendor-map-legend"><span><i className="top"/> {t("recommend.recommendedLegend")}</span><span><i className="current"/> {t("recommend.currentLegend")}</span><span><i className="pending"/> {t("recommend.pendingLegend")}</span><span><i className="eligible"/> {t("recommend.availableLegend")}</span><span><i className="unavailable"/> {t("recommend.unavailableLegend")}</span></div>
    <span className="vendor-map-note"><MapPin size={13}/> {t("recommend.analytical", {count: model.groups.length, suffix: model.groups.length === 1 ? "" : language === "en" ? "s" : ""})}</span>
  </div>;
}
