import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  ArrowLeft, ArrowRight, Building2, Bus, Check, ChevronDown,
  CircleParking, Clock3, FileText, Info, Languages, MapPin, RefreshCw, Store,
  UserRound, X,
} from "lucide-react";
import {
  cancelAllocationRequest, createAllocationRequest, getActiveAllocation,
  getOptions, getRecommendations, getVendorDashboard, getVendorEligibleZones,
  getZoneGeometry, registerVendor, updateVendorProfile,
} from "../services/api.js";
import {buildVendorExplorerMapModel, uniqueMapPositions, vendorVisibleContextZones} from "../utils/mapGrouping.js";
import {profileDisplayName, publicVendorId} from "../utils/profileIdentity.js";
import {useDialogFocus} from "../utils/dialogFocus.js";
import {useI18n} from "../i18n/react.jsx";
import ToastRegion from "./ToastRegion.jsx";
import {categoryLabel, factorLabel, factorSummary, formatDate as localizedDate, priorityLabel, requestTypeLabel, statusLabel, vendorTypeLabel} from "../i18n/index.js";
import "./VendorPortal.css";
import "./MapGrouping.css";
import "./VendorDashboard.css";

const PROFILES = ["BALANCED", "COMMERCIAL", "ACCESSIBILITY", "FACILITIES"];
const LANGUAGES = [{value: "en", label: "English"}, {value: "mr", label: "मराठी"}, {value: "hi", label: "हिंदी"}];
const RANK_COLORS = {1: "#174b77", 2: "#28658f", 3: "#3b78a3"};
const pretty = value => (value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
const score = value => value == null ? "—" : Number(value).toFixed(1);
const displayCapacity = (value, t) => value == null ? t("common.notSpecified") : String(value);

function draftFromProfile(profile) {
  return {
    full_name: profile?.full_name || "",
    business_name: profile?.business_name || "",
    business_category: profile?.business_category || "food",
    preferred_division: profile?.preferred_division || "",
    preferred_locality: profile?.preferred_locality || "",
    priority_profile: profile?.priority_profile || "BALANCED",
    market_preference: Boolean(profile?.market_preference),
    transport_preference: Boolean(profile?.transport_preference),
    parking_preference: Boolean(profile?.parking_preference),
    preferred_language: profile?.preferred_language || "en",
  };
}

function MapFocus({groups, selectedId, markerRefs}) {
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

function RecommendationMap({recommendations, context, selectedId, onFocus, onSelect, onGeometryStatus}) {
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

function PreferenceFields({draft, setDraft, options, disabled = false, onLanguageChange, requireIdentity = false}) {
  const {language, t} = useI18n();
  const set = (key, value) => setDraft(current => ({...current, [key]: value}));
  return <div className="vendor-form-grid">
    <label><span>{t("identity.fullName")}</span><input disabled={disabled} required={requireIdentity} maxLength={120} value={draft.full_name} onChange={event => set("full_name", event.target.value)} placeholder={t("identity.fullNamePlaceholder")}/></label>
    <label><span>{t("identity.businessName")}</span><input disabled={disabled} maxLength={120} value={draft.business_name} onChange={event => set("business_name", event.target.value)} placeholder={t("identity.businessNamePlaceholder")}/></label>
    <label><span>{t("profile.businessCategory")}</span><select disabled={disabled} value={draft.business_category} onChange={event => set("business_category", event.target.value)}>{options.categories.map(item => <option value={item} key={item}>{categoryLabel(language, item)}</option>)}</select></label>
    <label><span>{t("profile.preferredDivision")}</span><select disabled={disabled} required={requireIdentity} value={draft.preferred_division} onChange={event => set("preferred_division", event.target.value)}><option value="">{t("common.anyDivision")}</option>{options.divisions.map(item => <option value={item} key={item}>{item}</option>)}</select></label>
    <fieldset className="vendor-priority-options vendor-wide-field"><legend>{t("profile.priorityProfile")}</legend><div>{PROFILES.map(item => <label className={draft.priority_profile === item ? "selected" : ""} key={item}><input disabled={disabled} type="radio" name="priority_profile" value={item} checked={draft.priority_profile === item} onChange={() => set("priority_profile", item)}/><strong>{priorityLabel(language, item)}</strong><small>{t(item === "BALANCED" ? "profile.balancedHelp" : item === "COMMERCIAL" ? "profile.commercialHelp" : item === "ACCESSIBILITY" ? "profile.accessHelp" : "profile.facilitiesHelp")}</small></label>)}</div></fieldset>
    <label><span>{t("profile.preferredLanguage")}</span><select disabled={disabled} value={draft.preferred_language} onChange={event => {set("preferred_language", event.target.value); onLanguageChange?.(event.target.value);}}>{LANGUAGES.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
    <label className="vendor-wide-field"><span>{t("profile.localityOptional")}</span><input disabled={disabled} value={draft.preferred_locality} onChange={event => set("preferred_locality", event.target.value)} placeholder={t("profile.localityPlaceholder")}/><small className="field-note">{t("profile.localityHelp")}</small></label>
    <div className="vendor-preference-toggles vendor-wide-field">
      <label><input disabled={disabled} type="checkbox" checked={draft.market_preference} onChange={event => set("market_preference", event.target.checked)}/><Store size={17}/><span>{t("profile.market")}</span></label>
      <label><input disabled={disabled} type="checkbox" checked={draft.transport_preference} onChange={event => set("transport_preference", event.target.checked)}/><Bus size={17}/><span>{t("profile.transport")}</span></label>
      <label><input disabled={disabled} type="checkbox" checked={draft.parking_preference} onChange={event => set("parking_preference", event.target.checked)}/><CircleParking size={17}/><span>{t("profile.parking")}</span></label>
    </div>
  </div>;
}

function ZoneDetails({zone, metadata, onClose, onSelect}) {
  const {language, t} = useI18n();
  const [expanded, setExpanded] = useState(false);
  if (!zone) return null;
  return <div className="vendor-drawer-backdrop" onClick={onClose}>
    <aside className="vendor-zone-drawer" onClick={event => event.stopPropagation()} aria-label={`${t("common.details")}: ${zone.zone_id}`}>
      <button className="vendor-icon-button" onClick={onClose} aria-label={t("common.close")}><X size={19}/></button>
      <span className="vendor-eyebrow">{t("recommend.whyZone")}</span>
      <h2>#{zone.rank} · {zone.zone_id}</h2>
      <p className="zone-drawer-description">{zone.official_description}</p>
      <div className="zone-summary-grid">
        <div><span>{t("recommend.finalScore")}</span><strong>{score(zone.score)}</strong></div>
        <div><span>{t("common.liveStatus")}</span><strong>{statusLabel(language, zone.live_status)}</strong></div>
        <div><span>{t("common.available")}</span><strong>{displayCapacity(zone.available_capacity, t)}</strong></div>
        <div><span>{t("common.currentVendors")}</span><strong>{zone.current_vendor_count ?? "—"}</strong></div>
      </div>
      <div className="vendor-factor-list">
        {(zone.factors || []).map(factor => <div className="vendor-factor" key={factor.key}>
          <div><strong>{factorLabel(language, factor.key, factor.label)}</strong><span>{factorSummary(language, factor.key, factor.summary)}</span></div>
          <div className="factor-numbers"><b>{factor.score == null ? "—" : `${Math.round(factor.score * 100)}/100`}</b><small>{Number(factor.weight).toFixed(1)}% · +{score(factor.contribution)}</small></div>
          <div className="factor-score-bar" aria-label={`${factor.label} score ${factor.score == null ? "unavailable" : Math.round(factor.score * 100) + " out of 100"}`}><span style={{width: `${Math.max(0, Math.min(100, Number(factor.score || 0) * 100))}%`}}/></div>
          {factor.evidence?.length > 0 && <div className="vendor-evidence">{factor.evidence.map((item, index) => <span key={index}>{item.label}: <b>{item.value ?? t("common.unknown")}</b></span>)}</div>}
        </div>)}
      </div>
      <button className="weight-disclosure" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>{t("recommend.whyRanking")} <ChevronDown size={16}/></button>
      {expanded && <div className="weight-grid">{Object.entries(metadata.effective_factor_weights || {}).map(([key, value]) => <div key={key}><span>{factorLabel(language, key, pretty(key))}</span><strong>{(value * 100).toFixed(1)}%</strong></div>)}</div>}
      <button className="vendor-primary vendor-full-button" onClick={() => onSelect(zone)}>{t("recommend.selectThis")} <ArrowRight size={17}/></button>
    </aside>
  </div>;
}

function StatusPill({status}) {
  const {language} = useI18n();
  return <span className={`request-status status-${String(status).toLowerCase()}`}>{statusLabel(language, status)}</span>;
}

function ProfileSummary({profile, onEdit}) {
  const {language, t} = useI18n();
  const applicationId = profile.vendor_type === "NEW";
  return <section className="vendor-account-card">
    <div className="vendor-account-heading"><div><span className="vendor-eyebrow">{t(applicationId ? "identity.applicationLabel" : "identity.registeredVendor")}</span><h2>{profileDisplayName(profile, {application: t("identity.applicationVendor"), registered: t("identity.registeredVendor")})}</h2>{profile.business_name && <p className="identity-business">{profile.business_name}</p>}<p>{t(applicationId ? "identity.applicationId" : "identity.vendorId", {id: publicVendorId(profile)})}</p></div><button className="vendor-secondary" onClick={onEdit}>{t("profile.edit")}</button></div>
    <div className="vendor-account-grid"><div><span>{t("profile.businessCategory")}</span><strong>{categoryLabel(language, profile.business_category)}</strong></div><div><span>{t("profile.preferredDivision")}</span><strong>{profile.preferred_division || t("common.anyDivision")}</strong></div><div><span>{t("profile.preferredLocality")}</span><strong>{profile.preferred_locality || t("common.notSpecified")}</strong></div><div><span>{t("profile.preferredLanguage")}</span><strong>{t(`language.${profile.preferred_language || profile.language || "en"}`)}</strong></div><div><span>{t("profile.priorityProfile")}</span><strong>{priorityLabel(language, profile.priority_profile)}</strong></div><div><span>{t("profile.accountStatus")}</span><strong>{statusLabel(language, profile.status)}</strong></div></div>
  </section>;
}

function AllocationCard({allocation}) {
  const {language, t} = useI18n();
  return <section className="vendor-dashboard-card allocation-card"><div className="dashboard-section-heading"><div><span className="vendor-eyebrow">{t("allocation.heading")}</span><h2>{t("allocation.title")}</h2></div>{allocation && <StatusPill status="ACTIVE"/>}</div>
    {!allocation ? <div className="dashboard-empty"><MapPin size={27}/><strong>{t("allocation.noActive")}</strong><p>{t("allocation.noActiveHelp")}</p></div> : <><div className="allocation-zone"><MapPin size={22}/><div><strong>{allocation.zone_id}</strong><p>{allocation.zone_description || t("fallback.zoneDescription")}</p></div></div><div className="allocation-facts"><div><span>{t("allocation.date")}</span><strong>{localizedDate(language, allocation.allocated_at)}</strong></div><div><span>{t("allocation.type")}</span><strong>{requestTypeLabel(language, allocation.allocation_type || "NEW_ALLOCATION")}</strong></div><div><span>{t("common.liveStatus")}</span><strong>{statusLabel(language, allocation.live_zone_status)}</strong></div><div><span>{t("common.officialCapacity")}</span><strong>{displayCapacity(allocation.official_capacity, t)}</strong></div><div><span>{t("common.currentVendors")}</span><strong>{allocation.current_vendor_count ?? t("common.unknown")}</strong></div><div><span>{t("common.available")}</span><strong>{displayCapacity(allocation.available_capacity, t)}</strong></div></div></>}
  </section>;
}

function RequestSummary({summary}) {
  const {t} = useI18n();
  const cards = [["pending", summary.pending_count], ["approved", summary.approved_count], ["rejected", summary.rejected_count], ["cancelled", summary.cancelled_count]];
  return <section className="request-summary-grid" aria-label={t("requests.statusTitle")}>{cards.map(([label, count]) => <div key={label} className={`request-summary-card status-border-${label}`}><span>{t(`requests.${label}`)}</span><strong>{count}</strong></div>)}</section>;
}

function RequestHistory({requests, actionState, busy, onCancel, onRefresh, onNavigate}) {
  const {language, t} = useI18n();
  return <section className="vendor-dashboard-card request-history-card"><div className="dashboard-section-heading"><div><span className="vendor-eyebrow">{t("requests.heading")}</span><h2>{t("requests.history")}</h2><p>{t("requests.newest")}</p></div><button className="vendor-secondary" onClick={onRefresh} disabled={busy}><RefreshCw size={15}/> {t("common.refresh")}</button></div>
    {requests.length === 0 ? <div className="dashboard-empty"><FileText size={27}/><strong>{t("requests.empty")}</strong><p>{t("requests.emptyHelp")}</p><button className="vendor-primary" onClick={() => onNavigate("vendor-recommendations")}>{t("requests.viewRecommendations")}</button></div> : <div className="request-history-list">{requests.map(item => <article className="request-history-item" key={item.request_id}>
      <div className="request-history-main"><div><span className="request-type-label">{requestTypeLabel(language, item.request_type)}</span><h3>{item.requested_zone_id}</h3><p>{item.zone_description || t("fallback.zoneDescription")}</p></div><StatusPill status={item.status}/></div>
      <dl className="request-meta"><div><dt>{t("requests.requestId")}</dt><dd>{item.request_id}</dd></div><div><dt>{t("common.submitted")}</dt><dd>{localizedDate(language, item.created_at)}</dd></div>{item.previous_zone_id && <div><dt>{t("requests.previousZone")}</dt><dd>{item.previous_zone_id}</dd></div>}{item.reviewed_at && <div><dt>{t("common.reviewed")}</dt><dd>{localizedDate(language, item.reviewed_at)}</dd></div>}</dl>
      <div className="request-timeline" aria-label={`${t("requests.history")}: ${item.request_id}`}><div className="timeline-step complete"><span/><div><strong>{t("common.submitted")}</strong><small>{localizedDate(language, item.created_at)}</small></div></div><div className="timeline-line"/><div className="timeline-step complete"><span/><div><strong>{t("requests.pendingReview")}</strong></div></div>{item.status !== "PENDING" && <><div className="timeline-line"/><div className={`timeline-step complete ${item.status.toLowerCase()}`}><span/><div><strong>{statusLabel(language, item.status)}</strong><small>{localizedDate(language, item.reviewed_at || item.updated_at)}</small></div></div></>}</div>
      {item.status === "REJECTED" && <p className="request-reason"><strong>{t("common.reason")}:</strong> {item.rejection_reason || t("requests.noReason")}</p>}
      <div className="request-row-actions">{item.status === "PENDING" && <button className="vendor-danger" onClick={() => onCancel(item.request_id)} disabled={busy}>{t("requests.cancel")}</button>}{item.status === "APPROVED" && <button className="vendor-secondary" onClick={() => onNavigate("vendor-dashboard")}>{t("allocation.view")}</button>}{item.status === "REJECTED" && actionState.can_submit_request && <button className="vendor-secondary" onClick={() => onNavigate("vendor-recommendations")}>{t("requests.returnRecommendations")}</button>}</div>
    </article>)}</div>}
  </section>;
}

function DashboardSkeleton({label}) {
  return <div className="vendor-skeleton" role="status" aria-label={label}><span/><div/><div/><section><i/><i/><i/></section></div>;
}

export default function VendorPortal({sessionProfile = null, onboarding = false, view = "vendor-dashboard", onNavigate = () => {}, onRegistered}) {
  const {language, t, selectLanguage} = useI18n();
  const [options, setOptions] = useState({categories: [], divisions: []});
  const [profile, setProfile] = useState(null);
  const [draft, setDraft] = useState(draftFromProfile());
  const [activeAllocation, setActiveAllocation] = useState(null);
  const [recommendationData, setRecommendationData] = useState(null);
  const [mapContext, setMapContext] = useState({zones: [], current_zone_id: null, pending_zone_id: null});
  const [selectedId, setSelectedId] = useState("");
  const [detailZone, setDetailZone] = useState(null);
  const [confirmZone, setConfirmZone] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);
  const [preferenceConfirm, setPreferenceConfirm] = useState(false);
  useDialogFocus(Boolean(confirmZone || detailZone || cancelTarget || preferenceConfirm), ".vendor-zone-drawer, .vendor-confirm");
  const [dashboard, setDashboard] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [mapUnavailableIds, setMapUnavailableIds] = useState(null);
  const languagePatchRef = useRef("");
  const stage = onboarding ? "register" : view === "vendor-profile" ? "profile" : view === "vendor-recommendations" && !dashboard?.action_state?.has_pending_request ? "recommendations" : "dashboard";
  const setStage = next => onNavigate(next === "profile" ? "vendor-profile" : next === "recommendations" ? "vendor-recommendations" : "vendor-dashboard");
  const handleGeometryStatus = useCallback(ids => setMapUnavailableIds(ids ? new Set(ids) : null), []);

  useEffect(() => { getOptions().then(setOptions).catch(err => setError(err.message)); }, []);
  useEffect(() => {
    if (!sessionProfile) return;
    setProfile(sessionProfile); setDraft(draftFromProfile(sessionProfile));
  }, [sessionProfile?.vendor_id]);
  const run = async action => {
    setBusy(true); setError(""); setSuccess("");
    try { return await action(); } catch (err) { setError(err.message); return null; } finally { setBusy(false); }
  };
  const refreshDashboard = useCallback(async (quiet = false) => {
    if (!sessionProfile?.vendor_id) return null;
    if (!quiet) setDashboardLoading(true);
    try {
      const data = await getVendorDashboard();
      setDashboard(data); setActiveAllocation(data.active_allocation);
      return data;
    } catch (err) {
      setError(err.message); return null;
    } finally {
      if (!quiet) setDashboardLoading(false);
    }
  }, [sessionProfile?.vendor_id]);
  useEffect(() => {
    if (!onboarding && sessionProfile?.vendor_id) refreshDashboard();
  }, [onboarding, sessionProfile?.vendor_id, view, refreshDashboard]);
  const hydrateVendor = async vendor => {
    setProfile(vendor); setDraft(draftFromProfile(vendor)); selectLanguage(vendor.preferred_language, {deliberate: false});
    const active = await getActiveAllocation(vendor.vendor_id);
    setActiveAllocation(active.allocation);
  };
  const register = event => { event.preventDefault(); run(async () => {
    const vendor = await registerVendor({...draft, preferred_division: draft.preferred_division || null, preferred_locality: draft.preferred_locality || null});
    await hydrateVendor(vendor); await onRegistered?.(); setSuccess(t("onboarding.created"));
  }); };
  const persistProfile = () => run(async () => {
    const vendor = await updateVendorProfile(profile.vendor_id, {...draft, preferred_division: draft.preferred_division || null, preferred_locality: draft.preferred_locality || null});
    setProfile(vendor); setDraft(draftFromProfile(vendor)); selectLanguage(vendor.preferred_language); setRecommendationData(null); await refreshDashboard(true); setSuccess(t("profile.saved"));
  });
  const saveProfile = event => {
    event.preventDefault();
    if (recommendationData) setPreferenceConfirm(true);
    else persistProfile();
  };
  const findZones = () => run(async () => {
    const active = await getActiveAllocation(profile.vendor_id);
    setActiveAllocation(active.allocation);
    const [data, context] = await Promise.all([
      getRecommendations(profile.vendor_id, active.allocation?.zone_id || "", {
        business: draft.business_category,
        division: draft.preferred_division,
      }),
      getVendorEligibleZones(),
    ]);
    setMapUnavailableIds(null);
    setMapContext(context); setRecommendationData(data); setSelectedId(data.recommendations[0]?.zone_id || ""); onNavigate("vendor-recommendations");
  });
  useEffect(() => {
    if (view === "vendor-recommendations" && profile && !recommendationData && !dashboard?.action_state?.has_pending_request) findZones();
  }, [view, profile?.vendor_id, dashboard?.action_state?.has_pending_request]);
  const submitZone = () => run(async () => {
    const requestType = activeAllocation ? "RELOCATION" : "NEW_ALLOCATION";
    const created = await createAllocationRequest({
      vendor_id: profile.vendor_id, zone_id: confirmZone.zone_id, request_type: requestType,
      business_category: profile.business_category, preferred_division: profile.preferred_division,
      notes: "Submitted through vendor portal",
    });
    setConfirmZone(null); await refreshDashboard(true); onNavigate("vendor-requests");
    setSuccess(t("requests.submittedNotice"));
  });
  const cancelRequest = requestId => run(async () => {
    await cancelAllocationRequest(requestId);
    await refreshDashboard(true); setSuccess(t("requests.cancelledNotice"));
  });
  useEffect(() => {
    if (!confirmZone && !detailZone && !cancelTarget && !preferenceConfirm) return undefined;
    const close = event => {
      if (event.key !== "Escape") return;
      setConfirmZone(null); setDetailZone(null); setCancelTarget(null); setPreferenceConfirm(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [confirmZone, detailZone, cancelTarget, preferenceConfirm]);
  const changeLanguage = next => {
    selectLanguage(next);
    setDraft(current => ({...current, preferred_language: next}));
    if (!onboarding && profile?.vendor_id && profile.preferred_language !== next && languagePatchRef.current !== next) {
      languagePatchRef.current = next;
      updateVendorProfile(profile.vendor_id, {preferred_language: next})
        .then(vendor => {
          if (languagePatchRef.current !== next) return;
          setProfile(vendor);
          setDraft(current => ({...current, preferred_language: vendor.preferred_language}));
          setDashboard(current => current ? {...current, profile: {...current.profile, preferred_language: vendor.preferred_language}} : current);
        })
        .catch(err => setError(err.message))
        .finally(() => { if (languagePatchRef.current === next) languagePatchRef.current = ""; });
    }
  };
  const recommendations = recommendationData?.recommendations || [];
  const identityProfile = dashboard?.profile || profile;
  const displayName = profileDisplayName(identityProfile, {application: t("identity.applicationVendor"), registered: t("identity.registeredVendor")});
  const hour = new Date().getHours();
  const greetingPeriod = t(hour < 12 ? "vendor.morning" : hour < 17 ? "vendor.afternoon" : "vendor.evening");

  return <main className="vendor-portal">
    <header className="vendor-hero">
      <div><span className="vendor-eyebrow">{t("vendor.kicker")}</span><h1>{onboarding ? t("vendor.onboardingTitle") : t("vendor.greeting", {period: greetingPeriod, name: displayName})}</h1><p>{onboarding ? t("vendor.onboardingIntro") : t("vendor.greetingHelp")}</p></div>
      <label className="language-control"><Languages size={17}/><span>{t("language.label")}</span><select value={language} onChange={event => changeLanguage(event.target.value)}>{LANGUAGES.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
    </header>
    {onboarding && <nav className="vendor-progress" aria-label={t("nav.newOnboarding")}><div className="active"><span>1</span>{t("onboarding.account")}</div><div className="active"><span>2</span>{t("onboarding.business")}</div><div className="active"><span>3</span>{t("onboarding.preferences")}</div><div><span>4</span>{t("onboarding.recommendations")}</div></nav>}
    <ToastRegion success={success} error={error} onDismissSuccess={() => setSuccess("")} onDismissError={() => setError("")}/>

    {!onboarding && view === "vendor-dashboard" && dashboardLoading && !dashboard && <DashboardSkeleton label={t("requests.loadingDashboard")}/>}
    {!onboarding && view === "vendor-dashboard" && dashboard && <div className="vendor-dashboard-stack">
      <ProfileSummary profile={dashboard.profile} onEdit={() => onNavigate("vendor-profile")}/>
      <AllocationCard allocation={dashboard.active_allocation}/>
      <div><div className="dashboard-section-heading"><div><span className="vendor-eyebrow">{t("requests.overview")}</span><h2>{t("requests.statusTitle")}</h2></div><button className="vendor-secondary" onClick={() => onNavigate("vendor-requests")}>{t("requests.viewAll")}</button></div><RequestSummary summary={dashboard.request_summary}/></div>
      {dashboard.action_state.blocked_reason && <div className="vendor-action-notice"><Clock3 size={18}/><div><strong>{dashboard.action_state.blocked_reason}</strong><p>{t("requests.follow")}</p></div></div>}
    </div>}

    {!onboarding && view === "vendor-requests" && dashboardLoading && !dashboard && <DashboardSkeleton label={t("requests.loadingHistory")}/>}
    {!onboarding && view === "vendor-requests" && dashboard && <div className="vendor-dashboard-stack"><RequestSummary summary={dashboard.request_summary}/><RequestHistory requests={dashboard.requests} actionState={dashboard.action_state} busy={busy} onCancel={setCancelTarget} onRefresh={() => refreshDashboard()} onNavigate={onNavigate}/></div>}

    {!onboarding && view === "vendor-recommendations" && dashboard?.action_state?.has_pending_request && <div className="vendor-empty"><Clock3 size={30}/><h3>{t("requests.pendingExists")}</h3><p>{t("requests.pendingHelp")}</p><button className="vendor-primary" onClick={() => onNavigate("vendor-requests")}>{t("requests.open")}</button></div>}

    {stage === "register" && <section className="vendor-panel narrow"><span className="vendor-eyebrow">{t("onboarding.verified")}</span><h2>{t("onboarding.setupTitle")}</h2><p className="panel-copy">{t("onboarding.setupHelp")}</p><form onSubmit={register}><PreferenceFields draft={draft} setDraft={setDraft} options={options} onLanguageChange={changeLanguage} requireIdentity/><button className="vendor-primary" disabled={busy}>{t(busy ? "onboarding.creating" : "onboarding.create")}<ArrowRight size={17}/></button></form></section>}

    {stage === "profile" && profile && <section className="vendor-profile-layout">
      <aside className="vendor-profile-card"><span className="vendor-eyebrow">{t(profile.vendor_type === "NEW" ? "profile.applicationId" : "profile.historical")}</span><div className="profile-avatar"><UserRound size={24}/></div><h2>{profile.full_name || t(profile.vendor_type === "NEW" ? "identity.applicationVendor" : "identity.registeredVendor")}</h2>{profile.business_name && <p>{profile.business_name}</p>}<small>{publicVendorId(profile)}</small><span className="vendor-type">{vendorTypeLabel(language, profile.vendor_type, pretty(profile.vendor_type))}</span><dl><div><dt>{t("common.business")}</dt><dd>{categoryLabel(language, profile.business_category)}</dd></div><div><dt>{t("common.division")}</dt><dd>{profile.preferred_division || t("common.anyDivision")}</dd></div><div><dt>{t("allocation.active")}</dt><dd>{activeAllocation?.zone_id || t("common.none")}</dd></div></dl></aside>
      <section className="vendor-panel"><span className="vendor-eyebrow">{t("profile.heading")}</span><h2>{t("profile.title")}</h2><p className="panel-copy">{t("profile.help")}</p><form onSubmit={saveProfile}><PreferenceFields draft={draft} setDraft={setDraft} options={options} onLanguageChange={changeLanguage}/><div className="profile-actions"><button className="vendor-secondary" disabled={busy}>{t("profile.save")}</button><button className="vendor-primary" type="button" onClick={findZones} disabled={busy}>{t(busy ? "common.loading" : "profile.getTop3")}<ArrowRight size={17}/></button></div></form></section>
    </section>}

    {stage === "recommendations" && profile && <section className="recommendation-workspace">
      <div className="recommendation-toolbar"><div><button className="vendor-back" onClick={() => setStage("profile")}><ArrowLeft size={15}/> {t("onboarding.preferences")}</button><span className="vendor-eyebrow">{t("recommend.heading")}</span><h2>{t("recommend.title")}</h2><p>{t("recommend.eligible", {count: recommendationData?.candidate_count_after_live_filter ?? 0})}</p></div><button className="vendor-secondary" onClick={findZones} disabled={busy}><RefreshCw size={15}/> {t("common.refresh")}</button></div>
      <div className="personalization-strip"><div><span>{t("recommend.preferences")}</span><strong>{t("common.priority")}: {priorityLabel(language, recommendationData?.priority_profile)}</strong></div><p>{t("profile.transport")}: <b>{t(recommendationData?.preference_flags?.transport ? "common.yes" : "common.no")}</b> · {t("profile.market")}: <b>{t(recommendationData?.preference_flags?.market ? "common.yes" : "common.no")}</b> · {t("profile.parking")}: <b>{t(recommendationData?.preference_flags?.parking ? "common.yes" : "common.no")}</b></p><details><summary>{t("recommend.whyRanking")}</summary><div>{Object.entries(recommendationData?.effective_factor_weights || {}).map(([key, value]) => <span key={key}>{factorLabel(language, key, pretty(key))} <b>{(value * 100).toFixed(1)}%</b></span>)}</div></details></div>
      {recommendations.length === 0 ? <div className="vendor-empty"><MapPin size={30}/><h3>{t("recommend.noZones")}</h3><p>{t("recommend.noZonesHelp")}</p></div> : <div className="recommendation-grid">
        <div className="zone-card-list">{recommendations.map(zone => <article key={zone.zone_id} className={`zone-card ${selectedId === zone.zone_id ? "selected" : ""}`} aria-selected={selectedId === zone.zone_id} onClick={() => {setSelectedId(zone.zone_id); setDetailZone(zone);}}>
          <span className="zone-rank" style={{background: RANK_COLORS[zone.rank]}}>#{zone.rank}</span><div className="zone-card-heading"><div><h3>{zone.zone_id}</h3><span>{zone.zone_division}</span></div><strong>{score(zone.score)}<small>/100</small></strong></div><p>{zone.official_description}</p>
          {mapUnavailableIds?.has(zone.zone_id) && <div className="map-reference-unavailable"><MapPin size={13}/> {t("recommend.mapUnavailable")}</div>}
          <div className="zone-live-grid"><span><b>{statusLabel(language, zone.live_status)}</b> {t("common.liveStatus")}</span><span><b>{displayCapacity(zone.available_capacity, t)}</b> {t("common.available")}</span><span><b>{zone.current_vendor_count ?? "—"}</b> {t("common.currentVendors")}</span></div><div className="zone-card-actions"><button onClick={event => {event.stopPropagation(); setSelectedId(zone.zone_id); document.getElementById("vendor-recommendation-map")?.scrollIntoView({behavior: "smooth", block: "center"});}}><MapPin size={14}/> {t("recommend.viewMap")}</button><button onClick={event => {event.stopPropagation(); setDetailZone(zone); setSelectedId(zone.zone_id);}}>{t("recommend.viewDetails")}</button><button className="select-zone" onClick={event => {event.stopPropagation(); setConfirmZone(zone);}}>{t("recommend.select")}</button></div>
        </article>)}</div>
        <RecommendationMap recommendations={recommendations} context={mapContext} selectedId={selectedId} onGeometryStatus={handleGeometryStatus} onFocus={setSelectedId} onSelect={id => {setSelectedId(id); const recommendation = recommendations.find(zone => zone.zone_id === id); if (recommendation) setDetailZone(recommendation);}}/>
      </div>}
    </section>}

    {detailZone && <ZoneDetails zone={detailZone} metadata={recommendationData} onClose={() => setDetailZone(null)} onSelect={zone => {setDetailZone(null); setConfirmZone(zone);}}/>}
    {confirmZone && <div className="vendor-confirm-backdrop" onClick={() => setConfirmZone(null)}><div className="vendor-confirm" onClick={event => event.stopPropagation()}><div className="confirm-icon"><Building2 size={24}/></div><span className="vendor-eyebrow">{t("recommend.confirm")}</span><h2>{t("recommend.confirmTitle", {zoneId: confirmZone.zone_id})}</h2><p>{t("recommend.confirmHelp")}</p><div><span>{t("recommend.requestType")}</span><strong>{requestTypeLabel(language, activeAllocation ? "RELOCATION" : "NEW_ALLOCATION")}</strong></div><div className="confirm-actions"><button className="vendor-secondary" onClick={() => setConfirmZone(null)}>{t("common.goBack")}</button><button className="vendor-primary" onClick={submitZone} disabled={busy}>{t(busy ? "recommend.submitting" : "recommend.submit")}</button></div></div></div>}
    {cancelTarget && <div className="vendor-confirm-backdrop" onClick={() => setCancelTarget(null)}><div className="vendor-confirm" role="dialog" aria-modal="true" aria-labelledby="cancel-request-title" onClick={event => event.stopPropagation()}><div className="confirm-icon danger"><X size={24}/></div><span className="vendor-eyebrow">{t("requests.heading")}</span><h2 id="cancel-request-title">{t("confirm.cancelRequestTitle")}</h2><p>{t("confirm.cancelRequestHelp")}</p><div><span>{t("requests.requestId")}</span><strong>{cancelTarget}</strong></div><div className="confirm-actions"><button className="vendor-secondary" onClick={() => setCancelTarget(null)}>{t("confirm.keepRequest")}</button><button className="vendor-danger" onClick={async () => {const target = cancelTarget; setCancelTarget(null); await cancelRequest(target);}} disabled={busy}>{t("confirm.cancelRequest")}</button></div></div></div>}
    {preferenceConfirm && <div className="vendor-confirm-backdrop" onClick={() => setPreferenceConfirm(false)}><div className="vendor-confirm" role="dialog" aria-modal="true" aria-labelledby="preference-confirm-title" onClick={event => event.stopPropagation()}><div className="confirm-icon"><RefreshCw size={24}/></div><span className="vendor-eyebrow">{t("profile.heading")}</span><h2 id="preference-confirm-title">{t("confirm.preferenceTitle")}</h2><p>{t("confirm.preferenceHelp")}</p><div className="confirm-actions"><button className="vendor-secondary" onClick={() => setPreferenceConfirm(false)}>{t("confirm.keepPreferences")}</button><button className="vendor-primary" onClick={() => {setPreferenceConfirm(false); persistProfile();}} disabled={busy}>{t("confirm.savePreferences")}</button></div></div></div>}
  </main>;
}
