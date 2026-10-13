import React, {useEffect, useState} from "react";

import "leaflet/dist/leaflet.css";
import {MapPin, Search, ArrowRight, Info, SlidersHorizontal, RotateCcw} from "lucide-react";

import {apiRequest as request} from "../../services/api.js";
import {pretty, initial} from "./viewModel.js";
import {MapView} from "./RecommendationMap.jsx";
import {Details, ResultRow} from "./ZoneEvidence.jsx";
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
