import React,{useEffect,useState} from "react";

export {default as useData} from "../hooks/useApiData.js";
export function State({error,children}){return error?<div className="hub-error">{error}</div>:children;}
export function Stat({label,value,note}){return <div className="hub-stat"><span>{label}</span><strong>{value??"—"}</strong>{note&&<small>{note}</small>}</div>;}

