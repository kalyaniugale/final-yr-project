import {useCallback, useEffect, useReducer, useRef, useState} from "react";

import {cancelAllocationRequest, createAllocationRequest, getActiveAllocation, getOptions, getRecommendations, getVendorDashboard, getVendorEligibleZones, registerVendor, updateVendorProfile, getPilotLayout} from "../../services/api.js";

import {profileDisplayName} from "../../shared/utils/profileIdentity.js";
import {useDialogFocus} from "../../shared/utils/dialogFocus.js";
import {useI18n} from "../../i18n/react.jsx";

import {initialPilotState, pilotReducer} from "../pilot-slots/pilotState.js";

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

export default function useVendorWorkspace({sessionProfile = null, onboarding = false, view = "vendor-dashboard", onNavigate = () => {}, onRegistered}) {

  const {language, t, selectLanguage} = useI18n();
  const [options, setOptions] = useState({categories: [], divisions: []});
  const [profile, setProfile] = useState(null);
  const [draft, setDraft] = useState(draftFromProfile());
  const [activeAllocation, setActiveAllocation] = useState(null);
  const [pilot, dispatchPilot] = useReducer(pilotReducer, initialPilotState);
  const [pilotSummary, setPilotSummary] = useState(null);
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
      if (data.active_allocation?.zone_id === "NN_F_013") {
        try {setPilotSummary(await getPilotLayout());} catch {setPilotSummary(null);}
      } else setPilotSummary(null);
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

  return {language, t, options, profile, draft, setDraft, activeAllocation, pilot, dispatchPilot, pilotSummary, recommendationData, mapContext, selectedId, setSelectedId, detailZone, setDetailZone, confirmZone, setConfirmZone, cancelTarget, setCancelTarget, preferenceConfirm, setPreferenceConfirm, dashboard, dashboardLoading, busy, error, setError, success, setSuccess, mapUnavailableIds, stage, setStage, handleGeometryStatus, refreshDashboard, register, persistProfile, saveProfile, findZones, submitZone, cancelRequest, changeLanguage, recommendations, displayName, greetingPeriod};
}
