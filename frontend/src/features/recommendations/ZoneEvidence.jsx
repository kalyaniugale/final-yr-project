import React, {useEffect, useState} from "react";

import {MapPin, ChevronDown, ChevronRight, Info, X, Check} from "lucide-react";

import {num} from "./viewModel.js";

export function Factor({factor,open,onToggle}){
  const value=factor.score==null?null:Math.max(0,Math.min(100,Number(factor.score)*100));
  return <div className={`factor-item ${open?"factor-open":""}`}>
    <button className="factor-head" onClick={onToggle} aria-expanded={open}>
      <div className="factor-main"><span className="factor-name">{factor.label}</span><span className="factor-summary">{factor.summary}</span></div>
      <div className="factor-score"><strong>{value==null?"—":Math.round(value)}</strong><span>/100</span></div>
      <ChevronDown size={17} className="factor-chevron"/>
    </button>
    <div className="factor-progress"><div style={{width:`${value||0}%`}}/></div>
    {open&&<div className="factor-detail">
      <p>{factor.details}</p>
      <div className="evidence-grid">{factor.evidence?.map((e,i)=><div className="evidence-cell" key={i}><span>{e.label}</span><strong>{e.value??"Unknown"}</strong></div>)}</div>
      <div className="contribution"><span>Contribution to overall score</span><strong>{factor.contribution==null?"—":`+${num(factor.contribution)} points`}</strong><small>{factor.weight}% weight</small></div>
    </div>}
  </div>;
}
export function Details({r,onClose}){
  const [openFactor,setOpenFactor]=useState("business");
  useEffect(()=>setOpenFactor("business"),[r?.zone_id]);
  if(!r)return <div className="detail-empty"><MapPin size={27}/><h3>Select a zone</h3><p>Choose a recommendation to inspect its location, evidence and scoring details.</p></div>;
  const strengths=[...(r.factors||[])].filter(f=>f.key!=="preference"&&f.key!=="historical"&&f.score!=null).sort((a,b)=>b.score-a.score).slice(0,2);
  return <div className="detail-content">
    <div className="detail-top"><div><span className="micro-label">ZONE DETAILS</span><h2>{r.zone_id}</h2><p>{r.zone_division}</p></div><button className="icon-button" onClick={onClose} aria-label="Close details"><X size={18}/></button></div>
    <div className="detail-score-card"><div><span>Overall suitability</span><strong>{num(r.score)}<small>/100</small></strong></div><span className="method-pill">MCDA</span></div>
    <p className="detail-description">{r.official_description}</p>
    <div className="detail-meta"><div><span>Official listed capacity</span><strong>{r.official_capacity??"Not listed"}</strong></div><div><span>Zone type</span><strong>NMC designated vending zone</strong></div></div>
    <section className="detail-section"><h3>Why this zone?</h3><p className="section-subtitle">The strongest observed factors behind this ranking.</p><div className="reasons">{strengths.map(f=><div className="reason" key={f.key}><div className="reason-marker"><Check size={13}/></div><div><strong>{f.label}</strong><p>{f.summary}</p></div></div>)}</div></section>
    <details className="detail-section service-disclosure"><summary>Scoring evidence and factor breakdown</summary><div className="section-title-row"><div><h3>Factor breakdown</h3><p className="section-subtitle">Select a factor to see the evidence and its contribution.</p></div></div><div className="factor-list">{r.factors?.map(f=><Factor key={f.key} factor={f} open={openFactor===f.key} onToggle={()=>setOpenFactor(openFactor===f.key?null:f.key)}/>)}</div></details>
    {r.shared_reference&&<div className="detail-footnote"><Info size={15}/><span>These environmental measurements are shared by {r.shared_reference_group_size} zone records. The exact site should be confirmed before allocation.</span></div>}
    <div className="detail-model"><span>Scoring method</span><strong>Weighted MCDA baseline</strong><p>Transparent factor contributions. K-Means provides environmental profiling; it does not generate this score. SHAP is not used for this baseline.</p></div>
  </div>;
}
export function ResultRow({r,selected,onClick}){
  const title=r.official_description||r.zone_id;
  const short=title.length>112?title.slice(0,109)+"…":title;
  return <button className={`result-row ${selected?"selected":""}`} onClick={onClick}>
    <div className="row-rank">{String(r.rank).padStart(2,"0")}</div>
    <div className="row-body"><div className="row-title"><strong>{r.zone_id}</strong>{r.fallback_used&&<span className="fallback-chip">Other division</span>}</div><p>{short}</p><div className="row-meta"><MapPin size={13}/>{r.zone_division}</div></div>
    <div className="row-right"><strong>{num(r.score)}</strong><span>INDEX</span><ChevronRight size={17}/></div>
  </button>;
}
