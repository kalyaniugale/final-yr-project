import test from "node:test";
import assert from "node:assert/strict";
import {distanceMetres, nearDestination, startLocationWatch, geographicCenter} from "./pilotNavigation.js";

test("proximity zoom requires both a nearby position and usable GPS accuracy", () => {
  const target = [73.7732, 19.9733];
  assert.equal(nearDestination({longitude: target[0], latitude: target[1], accuracy: 8}, target), true);
  assert.equal(nearDestination({longitude: target[0], latitude: target[1], accuracy: 100}, target), false);
  assert.equal(nearDestination({longitude: 73.77, latitude: 19.97, accuracy: 8}, target), false);
  assert.equal(nearDestination(null, target), false);
  assert.ok(distanceMetres(target, [target[0], target[1] + .001]) > 100);
});
test("GPS watcher is explicitly stopped once and ignores late updates", () => {
  let success, clearCount = 0, seen = 0;
  const stop = startLocationWatch({watchPosition: (s, e, options) => {success = s; assert.equal(options.maximumAge, 10000); return 17;}, clearWatch: id => {assert.equal(id, 17); clearCount++;}}, () => seen++, () => {});
  success({coords: {longitude: 73, latitude: 20, accuracy: 5}}); stop(); stop();
  success({coords: {longitude: 73, latitude: 20, accuracy: 5}});
  assert.equal(clearCount, 1); assert.equal(seen, 1);
});
test("permission errors and missing GPS produce usable fallback messages", () => {
  let message;
  startLocationWatch(null, () => {}, m => {message = m;});
  assert.match(message, /slot remains visible/);
  startLocationWatch({watchPosition: (s, e) => {e({code: 1}); return 1;}, clearWatch: () => {}}, () => {}, m => {message = m;});
  assert.match(message, /permission denied/);
});
test("slot display centre uses longitude latitude without reversing GeoJSON", () => {
  assert.deepEqual(geographicCenter({coordinates: [[[73, 19], [75, 19], [75, 21], [73, 21], [73, 19]]]}), [74, 20]);
});
