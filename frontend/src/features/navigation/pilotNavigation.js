export function distanceMetres(a, b) {
  const r = n => n * Math.PI / 180;
  const h = Math.sin(r(b[1] - a[1]) / 2) ** 2 + Math.cos(r(a[1])) * Math.cos(r(b[1])) * Math.sin(r(b[0] - a[0]) / 2) ** 2;
  return 6371008.8 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
}
export function nearDestination(p, target, threshold = 40) {
  return Boolean(p && target && p.accuracy <= 50 && distanceMetres([p.longitude, p.latitude], target) <= threshold);
}
export function startLocationWatch(gps, onPosition, onError) {
  if (!gps) {onError("GPS is unavailable. Your slot remains visible on this map."); return () => {};}
  let stopped = false;
  const id = gps.watchPosition(p => {if (!stopped) onPosition({longitude: p.coords.longitude, latitude: p.coords.latitude, accuracy: p.coords.accuracy});},
    e => {if (!stopped) onError(e.code === 1 ? "Location permission denied. Enable permission to navigate; your slot remains visible." : e.code === 3 ? "GPS timed out. Try outdoors; your slot remains visible." : "GPS unavailable; your slot remains visible.");},
    {enableHighAccuracy: true, maximumAge: 10000, timeout: 20000});
  return () => {if (!stopped) {stopped = true; gps.clearWatch(id);}};
}
export function geographicCenter(geometry) {
  const points = geometry.coordinates[0].slice(0, -1);
  return [points.reduce((s, p) => s + p[0], 0) / points.length, points.reduce((s, p) => s + p[1], 0) / points.length];
}
