import React from "react";

import {Bus, CircleParking, Store} from "lucide-react";

import {useI18n} from "../../i18n/react.jsx";

import {categoryLabel, priorityLabel} from "../../i18n/index.js";

import {PROFILES, LANGUAGES} from "./viewModel.js";

export function PreferenceFields({draft, setDraft, options, disabled = false, onLanguageChange, requireIdentity = false}) {
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
