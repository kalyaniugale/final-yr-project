import {useEffect, useState} from "react";
import {apiRequest as get} from "../../services/api.js";
export default function useApiData(path){const [data,setData]=useState(null),[error,setError]=useState("");useEffect(()=>{let live=true;get(path).then(d=>live&&setData(d)).catch(e=>live&&setError(e.message));return()=>{live=false;};},[path]);return {data,error};}
