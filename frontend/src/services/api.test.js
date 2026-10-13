import test from "node:test";
import assert from "node:assert/strict";
import {apiRequest, getRecommendations, getPilotRoute, savePilotGeometry} from "./api.js";

test("shared client includes the session cookie and preserves the endpoint", async t => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "http://127.0.0.1:8000/api/catalog");
    assert.equal(options.credentials, "include");
    return new Response(JSON.stringify({zones: []}));
  });
  assert.deepEqual(await apiRequest("/api/catalog"), {zones: []});
});

test("recommendation request preserves vendor ownership context and preferences", async t => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.ok(url.endsWith("/api/recommendations"));
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "include");
    assert.deepEqual(JSON.parse(options.body), {
      vendor_id: "V1", exclude_zone: "Z1", business: "food", division: "New Nashik", top_n: 3,
    });
    return new Response(JSON.stringify({recommendations: []}));
  });
  await getRecommendations("V1", "Z1", {business: "food", division: "New Nashik"});
});

test("routing preserves WGS84 longitude/latitude and reviewed geometry payloads", async t => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.endsWith("/route")) assert.deepEqual(body, {longitude: 73.77, latitude: 19.97});
    else assert.deepEqual(body, {layout: {slots: []}, review_confirmed: true});
    return new Response(JSON.stringify({available: false}));
  });
  await getPilotRoute({longitude: 73.77, latitude: 19.97});
  await savePilotGeometry({slots: []});
});

test("shared client reports an unavailable service", async t => {
  t.mock.method(globalThis, "fetch", async () => {throw new TypeError("offline");});
  await assert.rejects(apiRequest("/api/catalog"), /Unable to reach/);
});

test("shared client retains server error detail", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({detail: "Not authorized"}), {status: 403}));
  await assert.rejects(apiRequest("/api/catalog"), /Not authorized/);
});

test("shared client reports malformed responses", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response("not JSON", {status: 502}));
  await assert.rejects(apiRequest("/api/catalog"), /unreadable response \(502\)/);
});
