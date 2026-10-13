import {useState, useRef, useEffect} from "react";
import {getPilotRoute} from "../../services/api.js";
import {nearDestination, startLocationWatch} from "./pilotNavigation.js";

export default function usePilotNavigation({visible,moveMap}) {
  const [destination, setDestination] = useState(null), [position, setPosition] = useState(null), [route, setRoute] = useState(null);
  const [navigating, setNavigating] = useState(false), [follow, setFollow] = useState(false), [gpsError, setGpsError] = useState("");
  const stopWatch = useRef(null), active = useRef(false), routed = useRef(false), epoch = useRef(0);
  const near = nearDestination(position, route?.access_endpoint || destination?.requested_access_point, destination?.proximity_threshold_m || 40);
  const stop = () => {active.current = false; epoch.current++; stopWatch.current?.(); stopWatch.current = null; setNavigating(false); setFollow(false);};
  useEffect(() => {if (!visible) stop();}, [visible]);
  useEffect(() => () => {active.current = false; epoch.current++; stopWatch.current?.();}, []);
  const requestRoute = async p => {
    const version = epoch.current;
    try {const data = await getPilotRoute(p); if (!active.current || version !== epoch.current) return; setRoute(data); if (data.available) moveMap("route");}
    catch (e) {if (active.current && version === epoch.current) setRoute({available: false, reason: e.message});}
  };
  const start = () => {
    if (!window.isSecureContext) {setGpsError("GPS requires HTTPS outside localhost. Your slot remains visible."); return;}
    stopWatch.current?.(); epoch.current++; active.current = true; routed.current = false; setGpsError(""); setNavigating(true); setFollow(true); setRoute(null);
    stopWatch.current = startLocationWatch(navigator.geolocation, p => {setPosition(p); setGpsError(p.accuracy > 50 ? `GPS accuracy ±${Math.round(p.accuracy)} m. Close-up guidance paused; GPS cannot identify a 2 m slot.` : ""); if (!routed.current) {routed.current = true; requestRoute(p);}}, message => {setGpsError(message); stop();});
  };
  return {destination,setDestination,position,route,navigating,follow,setFollow,gpsError,near,start,stop,requestRoute};
}
