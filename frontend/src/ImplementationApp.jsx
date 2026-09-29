import React, {useEffect, useState} from "react";
import {BarChart3, Building2, ChevronRight, FileText, Layers, LayoutDashboard, LogOut, MapPin, Menu, ShieldCheck, UserRound, X} from "lucide-react";
import AdminDashboard from "./components/AdminDashboard.jsx";
import AuthLanding from "./components/AuthLanding.jsx";
import RecommendationPage from "./components/RecommendationPage.jsx";
import VendorPortal from "./components/VendorPortal.jsx";
import BrandIdentity from "./components/BrandIdentity.jsx";
import {AnalysisPage, OverviewPage, ReviewPage, ZoneRegistryPage} from "./pages/ImplementationPages.jsx";
import {getCurrentUser, logout} from "./services/api.js";
import {useI18n} from "./i18n/react.jsx";
import {profileDisplayName, publicVendorId} from "./utils/profileIdentity.js";
import "./ImplementationApp.css";
import "./RoleShell.css";
import "./Polish.css";
import "./MunicipalTheme.css";

const ADMIN_NAV = [
  {id: "admin", title: "Admin dashboard", icon: ShieldCheck},
  {id: "overview", title: "Research overview", icon: LayoutDashboard},
  {id: "zones", title: "Zone registry", icon: Layers},
  {id: "recommend", title: "Research recommendations", icon: MapPin},
  {id: "analysis", title: "GIS & model insights", icon: BarChart3},
  {id: "review", title: "Expert review", icon: FileText},
];
const VENDOR_NAV = [
  {id: "vendor-dashboard", titleKey: "nav.dashboard", icon: LayoutDashboard},
  {id: "vendor-recommendations", titleKey: "nav.recommendations", icon: MapPin},
  {id: "vendor-requests", titleKey: "nav.requests", icon: FileText},
  {id: "vendor-profile", titleKey: "nav.profile", icon: UserRound},
];

export default function ImplementationApp() {
  const {t, applyProfileLanguage} = useI18n();
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState("vendor-dashboard");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [requestedDivision, setRequestedDivision] = useState("");

  const applySession = next => {
    if (next?.role === "VENDOR") applyProfileLanguage(next.vendor_profile?.preferred_language);
    setSession(next);
    const admin = next?.role === "ADMIN";
    const nextPage = admin ? "admin" : "vendor-dashboard";
    setPage(nextPage);
    window.history.replaceState({}, "", admin ? "/admin" : "/vendor");
  };
  useEffect(() => {
    getCurrentUser().then(applySession).catch(() => {
      setSession(null); window.history.replaceState({}, "", "/login");
    }).finally(() => setChecking(false));
  }, []);

  const signOut = async () => {
    try { await logout(); } finally {
      setSession(null); setPage("vendor-dashboard"); window.history.replaceState({}, "", "/login");
    }
  };
  const refreshSession = async () => applySession(await getCurrentUser());
  const navigate = id => {
    const allowed = (session?.role === "ADMIN" ? ADMIN_NAV : VENDOR_NAV).some(item => item.id === id);
    const safe = allowed ? id : session?.role === "ADMIN" ? "admin" : "vendor-dashboard";
    setPage(safe); setMobileOpen(false);
    window.history.replaceState({}, "", `${session?.role === "ADMIN" ? "/admin" : "/vendor"}/${safe}`);
  };
  const openZone = division => {
    setRequestedDivision(division === "Citywide" ? "" : division); navigate("recommend");
  };

  if (checking) return <div className="auth-loading"><Building2 size={28}/><span>{t("common.loading")}</span></div>;
  if (!session) return <AuthLanding onAuthenticated={applySession}/>;

  const onboarding = session.role === "NEW_VENDOR_ONBOARDING";
  const nav = session.role === "ADMIN" ? ADMIN_NAV : VENDOR_NAV;
  const current = nav.find(item => item.id === page) || nav[0];
  const navTitle = item => session.role === "ADMIN" ? item.title : t(item.titleKey);
  const vendorName = profileDisplayName(session.vendor_profile, {application: t("identity.applicationVendor"), registered: t("identity.registeredVendor")});
  return <div className="implementation-shell"><aside className={`implementation-sidebar ${mobileOpen ? "mobile-open" : ""}`}>
    <div className="brand"><BrandIdentity compact subtitle={session.role === "ADMIN" ? "NMC Officer Workspace" : t("nav.vendorServices")}/><button className="mobile-close" onClick={() => setMobileOpen(false)} aria-label={session.role === "ADMIN" ? "Close menu" : t("nav.close")}><X size={19}/></button></div>
    <div className="sidebar-section-label">{session.role === "ADMIN" ? (onboarding ? "PROFILE SETUP" : "YOUR WORKSPACE") : t(onboarding ? "nav.profileSetup" : "nav.workspace")}</div><nav className="implementation-nav" aria-label={session.role === "ADMIN" ? "Main navigation" : t("nav.workspace")}>{nav.map(item => <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => navigate(item.id)}><item.icon size={18}/><span>{navTitle(item)}</span>{page === item.id && <ChevronRight size={15} className="nav-arrow"/>}</button>)}</nav>
    <div className="sidebar-bottom auth-session-card"><div className="sidebar-bottom-label">{session.role === "ADMIN" ? "SIGNED IN AS" : t("nav.signedInAs")}</div><strong>{session.role === "ADMIN" ? session.admin_id : vendorName}</strong><p>{session.role === "ADMIN" ? "ADMIN" : onboarding ? t("nav.newOnboarding") : t(session.vendor_profile?.vendor_type === "NEW" ? "identity.applicationLabel" : "identity.registeredVendor")}</p>{session.role !== "ADMIN" && session.vendor_id && <small>{t(session.vendor_profile?.vendor_type === "NEW" ? "identity.applicationId" : "identity.vendorId", {id: publicVendorId(session.vendor_profile)})}</small>}<button onClick={signOut}><LogOut size={14}/> {session.role === "ADMIN" ? "Log out" : t("nav.logout")}</button></div>
  </aside>
  {mobileOpen && <button className="sidebar-backdrop" onClick={() => setMobileOpen(false)} aria-label={session.role === "ADMIN" ? "Close navigation" : t("nav.close")}/>}
  <div className="implementation-content"><header className="implementation-topbar"><button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label={session.role === "ADMIN" ? "Open navigation" : t("nav.open")}><Menu size={20}/></button><div className="topbar-breadcrumb">{session.role === "ADMIN" ? "Officer workspace" : t("nav.vendorWorkspace")} <ChevronRight size={13}/> <strong>{onboarding ? (session.role === "ADMIN" ? "Profile setup" : t("nav.profileSetup")) : navTitle(current)}</strong></div><div className="topbar-right"><span className="topbar-dot"/> {session.role === "ADMIN" ? "Authenticated" : t("nav.authenticated")} <span className="topbar-avatar">{session.role === "ADMIN" ? "N" : "V"}</span></div></header>
  <div className="implementation-view">
    {(session.role === "VENDOR" || onboarding) && <VendorPortal sessionProfile={session.vendor_profile} onboarding={onboarding} view={page} onNavigate={navigate} onRegistered={refreshSession}/>}
    {session.role === "ADMIN" && page === "admin" && <AdminDashboard adminId={session.admin_id}/>}
    {session.role === "ADMIN" && page === "overview" && <OverviewPage navigate={navigate}/>}
    {session.role === "ADMIN" && page === "zones" && <ZoneRegistryPage openZone={openZone}/>}
    {session.role === "ADMIN" && page === "recommend" && <RecommendationPage key={requestedDivision || "default"} initialDivision={requestedDivision}/>}
    {session.role === "ADMIN" && page === "analysis" && <AnalysisPage/>}
    {session.role === "ADMIN" && page === "review" && <ReviewPage/>}
  </div></div>
  </div>;
}
