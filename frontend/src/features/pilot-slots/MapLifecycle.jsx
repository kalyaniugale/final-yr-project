import {useEffect, useRef, useState} from "react";
import {useMap, useMapEvents} from "react-leaflet";
import L from "leaflet";
export default function MapLifecycle({visible, boundaries, slots, command, selected, assigned, boundaryId, position, follow, near, onPan, onClick, route}) {
  const map = useMap(), fitted = useRef(false), wasNear = useRef(false);
  const [zoom, setZoom] = useState(map.getZoom());
  useMapEvents({dragstart: onPan, click: e => onClick(e.latlng), zoomend: () => setZoom(map.getZoom())});
  useEffect(() => {map.getContainer().dataset.slotLabels = zoom >= 19 ? "visible" : "hidden";}, [map, zoom]);
  useEffect(() => {
    if (!visible) return;
    const resize = () => map.invalidateSize({pan: false});
    const observer = new ResizeObserver(resize); observer.observe(map.getContainer());
    const timer = setTimeout(() => {resize(); if (!fitted.current && boundaries?.features.length) {const target = slots.length ? {type: "FeatureCollection", features: slots.map(s => ({type: "Feature", properties: {}, geometry: s.geometry}))} : boundaries; map.fitBounds(L.geoJSON(target).getBounds(), {padding: [35, 35], maxZoom: 21}); fitted.current = true;}}, 0);
    return () => {observer.disconnect(); clearTimeout(timer);};
  }, [map, visible, boundaries]);
  useEffect(() => {
    if (!command) return;
    if (command.kind === "own" && assigned?.geometry) map.flyToBounds(L.geoJSON(assigned.geometry).getBounds(), {padding:[70,70],maxZoom:22});
    else if (command.kind === "location" && position) map.flyTo([position.latitude, position.longitude], near ? 21 : 17);
    else if (command.kind === "slot" && selected?.geometry) map.flyToBounds(L.geoJSON(selected.geometry).getBounds(), {padding: [70, 70], maxZoom: 22});
    else if (command.kind === "route" && route?.geometry) map.flyToBounds(L.geoJSON(route.geometry).getBounds(), {padding: [45, 45], maxZoom: 19});
    else if (command.kind === "slots" && slots.length) map.flyToBounds(L.geoJSON({type: "FeatureCollection", features: slots.map(s => ({type: "Feature", properties: {}, geometry: s.geometry}))}).getBounds(), {padding: [45, 45], maxZoom: 21});
    else {const features = command.kind === "boundary" ? boundaries.features.filter(f => f.properties.boundary_id === boundaryId) : boundaries.features; if (features.length) map.flyToBounds(L.geoJSON({type: "FeatureCollection", features}).getBounds(), {padding: [35, 35], maxZoom: 20});}
  }, [command]);
  useEffect(() => {
    if (!visible || !position || !follow) return;
    if (near && !wasNear.current && selected?.geometry) map.flyToBounds(L.geoJSON(selected.geometry).getBounds().pad(4), {maxZoom: 21, padding: [55, 55]});
    else if (!near) map.panTo([position.latitude, position.longitude]);
    wasNear.current = near;
  }, [position, follow, near, visible]);
  return null;
}

