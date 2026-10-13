import test from "node:test";
import assert from "node:assert/strict";
import {buildAdminMapModel, buildRecommendationMapModel, buildVendorExplorerMapModel, uniqueMapPositions, vendorVisibleContextZones} from "./mapGrouping.js";

const recommendations = [1, 2, 3].map(rank => ({
  zone_id: `ZONE_${rank}`, rank, score: 60 - rank,
}));
const geometry = coordinates => ({
  type: "FeatureCollection",
  features: Object.entries(coordinates).map(([zone_id, point]) => ({
    type: "Feature",
    properties: {zone_id, reference_group_id: `REF_${point.join("_")}`},
    geometry: {type: "Point", coordinates: point},
  })),
});

test("three recommendation coordinates create three visible locations", () => {
  const model = buildRecommendationMapModel(recommendations, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.2, 19.2], ZONE_3: [73.3, 19.3],
  }));
  assert.equal(model.groups.length, 3);
  assert.equal(model.representedZoneCount, 3);
  assert.equal(uniqueMapPositions(model.groups).length, 3);
});

test("three recommendations at one coordinate stay separate inside one marker", () => {
  const model = buildRecommendationMapModel(recommendations, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.1, 19.1], ZONE_3: [73.1, 19.1],
  }));
  assert.equal(model.groups.length, 1);
  assert.deepEqual(model.groups[0].zones.map(zone => zone.zone_id), ["ZONE_1", "ZONE_2", "ZONE_3"]);
  assert.equal(model.groups[0].shared, true);
  assert.equal(model.representedZoneCount, recommendations.length);
});

test("two shared and one unique create two locations and preserve all zones", () => {
  const model = buildRecommendationMapModel(recommendations, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.1, 19.1], ZONE_3: [73.3, 19.3],
  }));
  assert.equal(model.groups.length, 2);
  assert.equal(model.representedZoneCount, 3);
  assert.deepEqual(model.groups.map(group => group.zones.length).sort(), [1, 2]);
});

test("missing geometry is reported without removing the recommendation record", () => {
  const model = buildRecommendationMapModel(recommendations, geometry({ZONE_1: [73.1, 19.1]}));
  assert.equal(recommendations.length, 3);
  assert.deepEqual(model.unavailableZoneIds.sort(), ["ZONE_2", "ZONE_3"]);
  assert.equal(model.representedZoneCount, 1);
});

test("shared popup members retain zone identity for the selection callback", () => {
  const model = buildRecommendationMapModel(recommendations, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.1, 19.1], ZONE_3: [73.1, 19.1],
  }));
  const selected = model.groups[0].zones[1];
  assert.equal(selected.zone_id, "ZONE_2");
  assert.equal(selected.rank, 2);
});

test("changed recommendations produce changed fit positions", () => {
  const geo = geometry({ZONE_1: [73.1, 19.1], ZONE_2: [73.2, 19.2], ZONE_3: [73.3, 19.3]});
  const first = uniqueMapPositions(buildRecommendationMapModel(recommendations.slice(0, 2), geo).groups);
  const refreshed = uniqueMapPositions(buildRecommendationMapModel(recommendations.slice(1), geo).groups);
  assert.notDeepEqual(first, refreshed);
});

test("admin shared marker preserves each zone's independent live status", () => {
  const zones = [
    {zone_id: "ZONE_1", live_status: "OPEN", available_capacity: 12},
    {zone_id: "ZONE_2", live_status: "FULL", available_capacity: 0},
    {zone_id: "ZONE_3", live_status: "SUSPENDED", available_capacity: null},
  ];
  const model = buildAdminMapModel(zones, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.1, 19.1], ZONE_3: [73.1, 19.1],
  }));
  assert.deepEqual(model.groups[0].zones.map(zone => [zone.zone_id, zone.live_status, zone.available_capacity]), [
    ["ZONE_1", "OPEN", 12], ["ZONE_2", "FULL", 0], ["ZONE_3", "SUSPENDED", null],
  ]);
});

test("vendor explorer keeps all eligible zones and promotes Top-3 records", () => {
  const context = [
    {zone_id: "ZONE_1", live_status: "OPEN"},
    {zone_id: "ZONE_2", live_status: "OPEN"},
    {zone_id: "ZONE_4", live_status: "OPEN"},
  ];
  const model = buildVendorExplorerMapModel(recommendations, context, geometry({
    ZONE_1: [73.1, 19.1], ZONE_2: [73.2, 19.2], ZONE_3: [73.3, 19.3], ZONE_4: [73.4, 19.4],
  }));
  assert.equal(model.representedZoneCount, 4);
  assert.equal(model.groups.flatMap(group => group.zones).filter(zone => zone.is_recommendation).length, 3);
});

test("vendor map defaults to current and pending context until all zones is enabled", () => {
  const context = {
    current_zone_id: "ZONE_2", pending_zone_id: "ZONE_3",
    zones: [{zone_id: "ZONE_1"}, {zone_id: "ZONE_2"}, {zone_id: "ZONE_3"}, {zone_id: "ZONE_4"}],
  };
  assert.deepEqual(vendorVisibleContextZones(context).map(zone => zone.zone_id), ["ZONE_2", "ZONE_3"]);
  assert.equal(vendorVisibleContextZones(context, true).length, 4);
});
