import React, {useState} from "react";

import {ArrowRight, ChevronDown, X} from "lucide-react";

import {useI18n} from "../../i18n/react.jsx";

import {factorLabel, factorSummary, statusLabel} from "../../i18n/index.js";

import {pretty, score, displayCapacity} from "./viewModel.js";

export function ZoneDetails({zone, metadata, onClose, onSelect}) {
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
