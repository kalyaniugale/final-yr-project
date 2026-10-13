import React from "react";

import {FileText, MapPin, RefreshCw} from "lucide-react";

import {profileDisplayName, publicVendorId} from "../../shared/utils/profileIdentity.js";

import {useI18n} from "../../i18n/react.jsx";

import {categoryLabel, formatDate as localizedDate, priorityLabel, requestTypeLabel, statusLabel} from "../../i18n/index.js";

import {displayCapacity} from "./viewModel.js";

export function StatusPill({status}) {
  const {language} = useI18n();
  return <span className={`request-status status-${String(status).toLowerCase()}`}>{statusLabel(language, status)}</span>;
}

export function ProfileSummary({profile, onEdit}) {
  const {language, t} = useI18n();
  const applicationId = profile.vendor_type === "NEW";
  return <section className="vendor-account-card">
    <div className="vendor-account-heading"><div><span className="vendor-eyebrow">{t(applicationId ? "identity.applicationLabel" : "identity.registeredVendor")}</span><h2>{profileDisplayName(profile, {application: t("identity.applicationVendor"), registered: t("identity.registeredVendor")})}</h2>{profile.business_name && <p className="identity-business">{profile.business_name}</p>}<p>{t(applicationId ? "identity.applicationId" : "identity.vendorId", {id: publicVendorId(profile)})}</p></div><button className="vendor-secondary" onClick={onEdit}>{t("profile.edit")}</button></div>
    <div className="vendor-account-grid"><div><span>{t("profile.businessCategory")}</span><strong>{categoryLabel(language, profile.business_category)}</strong></div><div><span>{t("profile.preferredDivision")}</span><strong>{profile.preferred_division || t("common.anyDivision")}</strong></div><div><span>{t("profile.preferredLocality")}</span><strong>{profile.preferred_locality || t("common.notSpecified")}</strong></div><div><span>{t("profile.preferredLanguage")}</span><strong>{t(`language.${profile.preferred_language || profile.language || "en"}`)}</strong></div><div><span>{t("profile.priorityProfile")}</span><strong>{priorityLabel(language, profile.priority_profile)}</strong></div><div><span>{t("profile.accountStatus")}</span><strong>{statusLabel(language, profile.status)}</strong></div></div>
  </section>;
}

export function AllocationCard({allocation}) {
  const {language, t} = useI18n();
  return <section className="vendor-dashboard-card allocation-card"><div className="dashboard-section-heading"><div><span className="vendor-eyebrow">{t("allocation.heading")}</span><h2>{t("allocation.title")}</h2></div>{allocation && <StatusPill status="ACTIVE"/>}</div>
    {!allocation ? <div className="dashboard-empty"><MapPin size={27}/><strong>{t("allocation.noActive")}</strong><p>{t("allocation.noActiveHelp")}</p></div> : <><div className="allocation-zone"><MapPin size={22}/><div><strong>{allocation.zone_id}</strong><p>{allocation.zone_description || t("fallback.zoneDescription")}</p></div></div><details className="service-disclosure"><summary>{t("allocation.view")}</summary><div className="allocation-facts"><div><span>{t("allocation.date")}</span><strong>{localizedDate(language, allocation.allocated_at)}</strong></div><div><span>{t("allocation.type")}</span><strong>{requestTypeLabel(language, allocation.allocation_type || "NEW_ALLOCATION")}</strong></div><div><span>{t("common.liveStatus")}</span><strong>{statusLabel(language, allocation.live_zone_status)}</strong></div><div><span>{t("common.officialCapacity")}</span><strong>{displayCapacity(allocation.official_capacity, t)}</strong></div><div><span>{t("common.currentVendors")}</span><strong>{allocation.current_vendor_count ?? t("common.unknown")}</strong></div><div><span>{t("common.available")}</span><strong>{displayCapacity(allocation.available_capacity, t)}</strong></div></div></details></>}
  </section>;
}

export function RequestSummary({summary}) {
  const {t} = useI18n();
  const cards = [["pending", summary.pending_count], ["approved", summary.approved_count], ["rejected", summary.rejected_count], ["cancelled", summary.cancelled_count]];
  return <section className="request-summary-grid" aria-label={t("requests.statusTitle")}>{cards.map(([label, count]) => <div key={label} className={`request-summary-card status-border-${label}`}><span>{t(`requests.${label}`)}</span><strong>{count}</strong></div>)}</section>;
}

export function RequestHistory({requests, actionState, busy, onCancel, onRefresh, onNavigate}) {
  const {language, t} = useI18n();
  return <section className="vendor-dashboard-card request-history-card"><div className="dashboard-section-heading"><div><span className="vendor-eyebrow">{t("requests.heading")}</span><h2>{t("requests.history")}</h2><p>{t("requests.newest")}</p></div><button className="vendor-secondary" onClick={onRefresh} disabled={busy}><RefreshCw size={15}/> {t("common.refresh")}</button></div>
    {requests.length === 0 ? <div className="dashboard-empty"><FileText size={27}/><strong>{t("requests.empty")}</strong><p>{t("requests.emptyHelp")}</p><button className="vendor-primary" onClick={() => onNavigate("vendor-recommendations")}>{t("requests.viewRecommendations")}</button></div> : <div className="request-history-list">{requests.map(item => <article className="request-history-item" key={item.request_id}>
      <div className="request-history-main"><div><span className="request-type-label">{requestTypeLabel(language, item.request_type)}</span><h3>{item.requested_zone_id}</h3><p>{item.zone_description || t("fallback.zoneDescription")}</p></div><StatusPill status={item.status}/></div>
      <details className="service-disclosure"><summary>{t("requests.requestId")} · {item.request_id}</summary><dl className="request-meta"><div><dt>{t("requests.requestId")}</dt><dd>{item.request_id}</dd></div><div><dt>{t("common.submitted")}</dt><dd>{localizedDate(language, item.created_at)}</dd></div>{item.previous_zone_id && <div><dt>{t("requests.previousZone")}</dt><dd>{item.previous_zone_id}</dd></div>}{item.reviewed_at && <div><dt>{t("common.reviewed")}</dt><dd>{localizedDate(language, item.reviewed_at)}</dd></div>}</dl>
      <div className="request-timeline" aria-label={`${t("requests.history")}: ${item.request_id}`}><div className="timeline-step complete"><span/><div><strong>{t("common.submitted")}</strong><small>{localizedDate(language, item.created_at)}</small></div></div><div className="timeline-line"/><div className="timeline-step complete"><span/><div><strong>{t("requests.pendingReview")}</strong></div></div>{item.status !== "PENDING" && <><div className="timeline-line"/><div className={`timeline-step complete ${item.status.toLowerCase()}`}><span/><div><strong>{statusLabel(language, item.status)}</strong><small>{localizedDate(language, item.reviewed_at || item.updated_at)}</small></div></div></>}</div></details>
      {item.status === "REJECTED" && <p className="request-reason"><strong>{t("common.reason")}:</strong> {item.rejection_reason || t("requests.noReason")}</p>}
      <div className="request-row-actions">{item.status === "PENDING" && <button className="vendor-danger" onClick={() => onCancel(item.request_id)} disabled={busy}>{t("requests.cancel")}</button>}{item.status === "APPROVED" && <button className="vendor-secondary" onClick={() => onNavigate("vendor-dashboard")}>{t("allocation.view")}</button>}{item.status === "REJECTED" && actionState.can_submit_request && <button className="vendor-secondary" onClick={() => onNavigate("vendor-recommendations")}>{t("requests.returnRecommendations")}</button>}</div>
    </article>)}</div>}
  </section>;
}

export function DashboardSkeleton({label}) {
  return <div className="vendor-skeleton" role="status" aria-label={label}><span/><div/><div/><section><i/><i/><i/></section></div>;
}

