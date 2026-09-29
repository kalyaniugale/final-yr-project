import React, {useState} from "react";
import {ArrowRight, KeyRound, Landmark, Languages, LockKeyhole, Phone, ShieldCheck} from "lucide-react";
import {loginAdmin, requestVendorOtp, verifyVendorOtp} from "../services/api.js";
import {useI18n} from "../i18n/react.jsx";
import BrandIdentity from "./BrandIdentity.jsx";
import "./AuthLanding.css";

export default function AuthLanding({onAuthenticated}) {
  const {language, t, selectLanguage} = useI18n();
  const [mode, setMode] = useState("vendor");
  const [step, setStep] = useState("mobile");
  const [mobile, setMobile] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [otp, setOtp] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async action => {
    setBusy(true); setError("");
    try { await action(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  const requestOtp = event => { event.preventDefault(); run(async () => {
    const result = await requestVendorOtp(mobile);
    setChallengeId(result.challenge_id); setStep("otp");
  }); };
  const verifyOtp = event => { event.preventDefault(); run(async () => {
    const result = await verifyVendorOtp(challengeId, otp);
    onAuthenticated(result);
  }); };
  const officerLogin = event => { event.preventDefault(); run(async () => {
    onAuthenticated(await loginAdmin(username, password));
  }); };
  const switchMode = next => { setMode(next); setStep("mobile"); setError(""); setOtp(""); };

  return <main className="auth-page">
    <header className="auth-government-header">
      <BrandIdentity subtitle={t("auth.prototype")}/>
      <label className="auth-language"><Languages size={15}/><span>{t("language.label")}</span><select value={language} onChange={event => selectLanguage(event.target.value)}><option value="en">English</option><option value="mr">मराठी</option><option value="hi">हिन्दी</option></select></label>
    </header>
    <section className="auth-panel"><div className="auth-service-heading"><h1>{t("auth.servicesTitle")}</h1><p>{t("auth.servicesHelp")}</p></div><div className="auth-card">
      <div className="auth-choice" role="tablist"><button className={mode === "vendor" ? "active" : ""} onClick={() => switchMode("vendor")}><Phone size={16}/> {t("auth.vendorAccess")}</button><button className={mode === "admin" ? "active" : ""} onClick={() => switchMode("admin")}><Landmark size={16}/> {t("auth.officerAccess")}</button></div>
      {mode === "vendor" ? <>
        <div className="auth-section-title"><div className="auth-icon"><KeyRound size={20}/></div><div><h2>{step === "mobile" ? t("auth.mobileTitle") : t("auth.otpTitle")}</h2><p>{step === "mobile" ? t("auth.mobileHelp") : t("auth.otpHelp")}</p></div></div>
        {step === "mobile" ? <form onSubmit={requestOtp}><label><span>{t("auth.mobileLabel")}</span><div className="auth-input"><b>+91</b><input inputMode="numeric" autoComplete="tel" value={mobile} onChange={event => setMobile(event.target.value)} placeholder={t("auth.mobilePlaceholder")} required/></div></label><button className="auth-primary" disabled={busy}>{busy ? t("auth.requesting") : t("auth.requestOtp")}<ArrowRight size={16}/></button></form>
          : <form onSubmit={verifyOtp}><label><span>{t("auth.otpLabel")}</span><div className="auth-input"><LockKeyhole size={16}/><input className="otp-input" inputMode="numeric" autoComplete="one-time-code" maxLength="6" value={otp} onChange={event => setOtp(event.target.value.replace(/\D/g, ""))} placeholder="000000" required/></div></label><button className="auth-primary" disabled={busy || otp.length !== 6}>{busy ? t("auth.verifying") : t("auth.verifyContinue")}<ArrowRight size={16}/></button><button type="button" className="auth-link" onClick={() => {setStep("mobile"); setOtp("");}}>{t("auth.differentMobile")}</button></form>}
      </> : <>
        <div className="auth-section-title"><div className="auth-icon officer"><ShieldCheck size={20}/></div><div><h2>Officer sign in</h2><p>Authorised NMC officers only.</p></div></div>
        <form onSubmit={officerLogin}><label><span>Officer username</span><div className="auth-input"><input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} placeholder="Officer username" required/></div></label><label><span>Password</span><div className="auth-input"><LockKeyhole size={16}/><input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} placeholder="Password" required/></div></label><button className="auth-primary officer" disabled={busy}>{busy ? "Signing in…" : "Sign in to NMC dashboard"}<ArrowRight size={16}/></button></form>
      </>}
      {error && <div className="auth-error" role="alert">{error}</div>}
      {mode === "vendor" && <p className="auth-new-vendor">{t("auth.newVendorHelp")}</p>}
    </div></section>
    <footer className="auth-footer">{t("auth.prototype")}</footer>
  </main>;
}
