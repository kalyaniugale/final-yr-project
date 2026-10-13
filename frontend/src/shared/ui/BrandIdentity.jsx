import React from "react";

export default function BrandIdentity({subtitle, compact = false}) {
  return <div className={`municipal-brand ${compact ? "compact" : ""}`}>
    <span className="municipal-brand-mark"><img src="/nmc-logo.jpg" alt="Nashik Municipal Corporation emblem"/></span>
    <span className="municipal-wordmark"><strong>Nashik Municipal Corporation</strong><span>Street Vendor Management System</span>{subtitle && <small>{subtitle}</small>}</span>
  </div>;
}
