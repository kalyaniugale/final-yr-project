import React, {useEffect, useMemo, useState} from "react";
import {MapContainer, TileLayer, CircleMarker, Popup, useMap} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {MapPin, Search, ArrowRight, ArrowLeft, ChevronDown, ChevronRight, Info, SlidersHorizontal, BarChart3, Building2, Navigation, Map as MapIcon, RotateCcw, X, Check, ShieldCheck} from "lucide-react";

const API=(import.meta.env.VITE_API_BASE||"http://127.0.0.1:8000").replace(/\/$/,"");
const pretty=s=>(s||"").replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
const num=n=>n==null?"—":Number(n).toFixed(1);
const initial={mode:"new",vendorId:"",business:"vegetable_fruit",division:"",excludeZone:""};
async function request(path,options={}){
  const res=await fetch(`${API}${path}`,options);
  let body;try{body=await res.json();}catch{throw new Error(`Server returned ${res.status}.`);}
  if(!res.ok)throw new Error(typeof body.detail==="string"?body.detail:"Request failed.");
  return body;
}
function Fit({points,selected}){
  const map=useMap();
  useEffect(()=>{if(points.length){const b=L.latLngBounds(points.map(p=>p.position));if(b.isValid())map.fitBounds(b.pad(.35),{maxZoom:15,animate:false});}},[map,points]);
  useEffect(()=>{if(selected)map.flyTo(selected.position,Math.max(map.getZoom(),14),{duration:.4});},[map,selected]);
  return null;
}
function MapView({results,selectedId,onSelect}){
  const [geo,setGeo]=useState(null),[error,setError]=useState("");
  useEffect(()=>{request("/api/zones/geometry").then(setGeo).catch(e=>setError(e.message));},[]);
  const points=useMemo(()=>{
    if(!geo)return [];
    const byId=new Map(geo.features.map(f=>[f.properties.zone_id,f]));
    return results.flatMap(r=>{
      const f=byId.get(r.zone_id);
      if(f?.geometry?.type!=="Point")return [];
      const [lng,lat]=f.geometry.coordinates;
      return Number.isFinite(lat)&&Number.isFinite(lng)?[{...r,position:[lat,lng]}]:[];
    });
  },[geo,results]);
  const selected=points.find(p=>p.zone_id===selectedId);
  return <div className="map-shell">
    {error&&<p className="map-error">{error}</p>}
    <MapContainer center={[19.9975,73.7898]} zoom={12} scrollWheelZoom={false} className="map-canvas">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
      <Fit points={points} selected={selected}/>
      {points.map(p=><CircleMarker key={p.zone_id} center={p.position} radius={p.zone_id===selectedId?11:8}
        pathOptions={{color:"#fff",weight:2.5,fillColor:p.zone_id===selectedId?"#174b38":"#64748b",fillOpacity:1}}
        eventHandlers={{click:()=>onSelect(p.zone_id)}}>
        <Popup><strong>{p.zone_id}</strong><br/>{p.official_description}<br/><small>Analytical reference point</small></Popup>
      </CircleMarker>)}
    </MapContainer>
    <div className="map-overlay"><MapPin size={13}/> Approximate reference points</div>
  </div>;
}
function Factor({factor,open,onToggle}){
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
function Details({r,onClose}){
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
    <section className="detail-section"><div className="section-title-row"><div><h3>Factor breakdown</h3><p className="section-subtitle">Select a factor to see the evidence and its contribution.</p></div></div><div className="factor-list">{r.factors?.map(f=><Factor key={f.key} factor={f} open={openFactor===f.key} onToggle={()=>setOpenFactor(openFactor===f.key?null:f.key)}/>)}</div></section>
    {r.shared_reference&&<div className="detail-footnote"><Info size={15}/><span>These environmental measurements are shared by {r.shared_reference_group_size} zone records. The exact site should be confirmed before allocation.</span></div>}
    <div className="detail-model"><span>Scoring method</span><strong>Weighted MCDA baseline</strong><p>Transparent factor contributions. K-Means provides environmental profiling; it does not generate this score. SHAP is not used for this baseline.</p></div>
  </div>;
}
function ResultRow({r,selected,onClick}){
  const title=r.official_description||r.zone_id;
  const short=title.length>112?title.slice(0,109)+"…":title;
  return <button className={`result-row ${selected?"selected":""}`} onClick={onClick}>
    <div className="row-rank">{String(r.rank).padStart(2,"0")}</div>
    <div className="row-body"><div className="row-title"><strong>{r.zone_id}</strong>{r.fallback_used&&<span className="fallback-chip">Other division</span>}</div><p>{short}</p><div className="row-meta"><MapPin size={13}/>{r.zone_division}</div></div>
    <div className="row-right"><strong>{num(r.score)}</strong><span>INDEX</span><ChevronRight size={17}/></div>
  </button>;
}
export default function RecommendationPage({initialDivision=""}){
  const [form,setForm]=useState({...initial,division:initialDivision}),[options,setOptions]=useState({categories:["vegetable_fruit","food","clothing","flower","general_goods","other"],divisions:[]});
  const [vendor,setVendor]=useState(null),[results,setResults]=useState([]),[selected,setSelected]=useState("");
  const [loading,setLoading]=useState(false),[lookupLoading,setLookupLoading]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState(""),[searched,setSearched]=useState(false);
  const [showDetails,setShowDetails]=useState(true);
  useEffect(()=>{request("/api/options").then(setOptions).catch(e=>setError(`Backend unavailable: ${e.message}`));},[]);
  const set=(key,value)=>setForm(f=>({...f,[key]:value}));
  async function lookup(){
    if(!form.vendorId.trim())return;
    setLookupLoading(true);setError("");
    try{const v=await request(`/api/vendor/${encodeURIComponent(form.vendorId.trim())}`);setVendor(v);setForm(f=>({...f,business:v.business_category,division:v.division,excludeZone:""}));}
    catch(e){setVendor(null);setError(e.message);}
    finally{setLookupLoading(false);}
  }
  async function submit(e){
    e.preventDefault();setLoading(true);setError("");setNotice("");
    try{
      if(form.mode==="existing"&&(!vendor||vendor.vendor_id!==form.vendorId.trim()))throw new Error("Look up the registered vendor ID first.");
      const body={business:form.business,division:form.division,vendor_id:form.mode==="existing"?form.vendorId.trim():"",exclude_zone:form.excludeZone.trim(),top_n:3,require_verified:false};
      const data=await request("/api/recommendations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      setResults(data.recommendations);setSelected(data.recommendations[0]?.zone_id||"");setNotice(data.notice);setSearched(true);setShowDetails(true);
    }catch(e){setError(e.message);}finally{setLoading(false);}
  }
  function reset(){setForm({...initial,division:initialDivision});setVendor(null);setResults([]);setSelected("");setError("");setNotice("");setSearched(false);}
  const active=results.find(r=>r.zone_id===selected);
  function select(id){setSelected(id);setShowDetails(true);}
  return <main className="nashik-rec">
    <div className="rec-heading"><div className="heading-kicker"><span className="kicker-line"/> VENDOR SERVICES <span className="kicker-separator">/</span> ZONE PLANNING</div><h1>Find a vending zone</h1><p>Explore designated locations based on your business and preferred area.</p></div>
    <div className="rec-layout">
      <aside className="rec-form-panel"><div className="panel-label"><SlidersHorizontal size={16}/> SEARCH CRITERIA</div><div className="mode-switch"><button className={form.mode==="new"?"active":""} onClick={()=>{setForm(f=>({...f,mode:"new",vendorId:"",excludeZone:""}));setVendor(null);}}>New vendor</button><button className={form.mode==="existing"?"active":""} onClick={()=>{set("mode","existing");setVendor(null);}}>Existing vendor</button></div>
        <form onSubmit={submit}>
          {form.mode==="existing"&&<div className="rec-field"><label htmlFor="vendor-id">Registered vendor ID</label><div className="lookup-control"><input id="vendor-id" value={form.vendorId} onChange={e=>{set("vendorId",e.target.value);setVendor(null);}} placeholder="V2024_00001"/><button type="button" onClick={lookup} disabled={lookupLoading||!form.vendorId.trim()} aria-label="Look up vendor"><Search size={17}/></button></div>{vendor&&<p className="lookup-confirm">Record found · {pretty(vendor.business_category)}</p>}</div>}
          <div className="rec-field"><label htmlFor="business">Business type</label><select id="business" value={form.business} onChange={e=>set("business",e.target.value)}>{options.categories.map(c=><option key={c} value={c}>{pretty(c)}</option>)}</select></div>
          <div className="rec-field"><label htmlFor="division">Preferred division</label><select id="division" value={form.division} onChange={e=>set("division",e.target.value)}><option value="">Any division</option>{options.divisions.map(d=><option key={d} value={d}>{d}</option>)}</select></div>
          {form.mode==="existing"&&<div className="rec-field"><label htmlFor="current-zone">Current zone ID <span className="optional">optional</span></label><input id="current-zone" value={form.excludeZone} onChange={e=>set("excludeZone",e.target.value)} placeholder="Enter if verified"/><small>Exclude your confirmed current zone.</small></div>}
          <button className="rec-submit" disabled={loading||form.mode==="existing"&&!vendor}>{loading?"Finding zones…":"Find zones"}<ArrowRight size={17}/></button>
          <button className="rec-reset" type="button" onClick={reset}><RotateCcw size={13}/> Reset search</button>
        </form>
        <div className="form-method"><div className="method-title"><Info size={15}/> About the ranking</div><p>Environmental GIS, business evidence and your preferences are combined using a transparent weighted score.</p><span>MCDA baseline · K-Means profiling</span></div>
      </aside>
      <div className="rec-main">
        <section className="rec-results"><div className="results-heading"><div><span className="panel-label">RECOMMENDATIONS</span><h2>{searched?"Your matching zones":"Zone recommendations"}</h2><p>{searched?`${results.length} results for ${pretty(form.business)}${form.division?" · "+form.division:""}`:"Enter your details to begin."}</p></div>{searched&&results.length>0&&<span className="result-count">{results.length} ZONES</span>}</div>
          {error&&<div className="rec-error" role="alert">{error}</div>}
          {!searched?<div className="rec-empty"><div className="empty-symbol"><MapPin size={27}/></div><h3>Discover suitable locations</h3><p>Your top three zones will appear here with a map and detailed scoring evidence.</p></div>:results.length===0?<div className="rec-empty"><h3>No matching zones</h3><p>Try another division or business type.</p></div>:<div className="result-list">{results.map(r=><ResultRow key={r.zone_id} r={r} selected={selected===r.zone_id} onClick={()=>select(r.zone_id)}/>)}</div>}
          {searched&&results.length>0&&<div className="results-context"><span><Info size={14}/> Scores are comparative, not success probabilities.</span><button onClick={()=>{setShowDetails(true);if(!selected)setSelected(results[0].zone_id);}}>View scoring details <ArrowRight size={14}/></button></div>}
        </section>
        {searched&&results.length>0&&<section className="rec-map-panel"><div className="map-heading"><div><span className="panel-label">LOCATION OVERVIEW</span><h2>Map view</h2></div><span className="map-count">{results.length} locations</span></div><MapView results={results} selectedId={selected} onSelect={select}/></section>}
      </div>
      {searched&&results.length>0&&showDetails&&<aside className="rec-detail-panel"><Details r={active} onClose={()=>setShowDetails(false)}/></aside>}
    </div>
    <footer className="rec-footer"><span>Nashik vendor zoning · Decision-support prototype</span><span>NMC designated zone records · Decision-support implementation</span></footer>
  </main>;
}
