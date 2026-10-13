import React, {useEffect, useMemo, useState} from "react";
import {MapContainer, TileLayer, CircleMarker, Popup, useMap} from "react-leaflet";
import L from "leaflet";
import {MapPin} from "lucide-react";

import {apiRequest as request} from "../../services/api.js";

export function Fit({points,selected}){
  const map=useMap();
  useEffect(()=>{if(points.length){const b=L.latLngBounds(points.map(p=>p.position));if(b.isValid())map.fitBounds(b.pad(.35),{maxZoom:15,animate:false});}},[map,points]);
  useEffect(()=>{if(selected)map.flyTo(selected.position,Math.max(map.getZoom(),14),{duration:.4});},[map,selected]);
  return null;
}
export function MapView({results,selectedId,onSelect}){
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
