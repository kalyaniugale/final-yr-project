import test from "node:test";
import assert from "node:assert/strict";
import {initialPilotState, pilotReducer} from "./pilotState.js";

test("closing and reopening preserves loaded pilot, selected slot and context view", () => {
  const layout = {slots: [{slot_id: "S004", status: "AVAILABLE"}]};
  let state = pilotReducer(initialPilotState, {type: "open"});
  state = pilotReducer(state, {type: "loaded", layout});
  state = pilotReducer(state, {type: "select", slotId: "S004"});
  state = pilotReducer(state, {type: "view", view: "context"});
  state = pilotReducer(state, {type: "close"});
  assert.equal(state.open, false);
  assert.equal(state.visited, true);
  assert.equal(state.layout, layout);
  state = pilotReducer(state, {type: "open"});
  assert.equal(state.selectedId, "S004");
  assert.equal(state.layout, layout);
  assert.equal(state.view, "context");
});

test("zone drawer actions are independent of pilot state", () => {
  const layout = {slots: [{slot_id: "S001"}]};
  let state = pilotReducer(initialPilotState, {type: "loaded", layout});
  state = pilotReducer(state, {type: "select", slotId: "S001"});
  assert.equal(pilotReducer(state, {type: "close-zone-drawer"}), state);
});

test("vendor starts on their assigned demonstration slot and refresh retains selection", () => {
  let state = pilotReducer(initialPilotState, {type: "loaded", layout: {my_slot_id: "S002", slots: []}});
  assert.equal(state.selectedId, "S002");
  state = pilotReducer(state, {type: "select", slotId: "S005"});
  state = pilotReducer(state, {type: "loaded", layout: {my_slot_id: "S002", slots: []}});
  assert.equal(state.selectedId, "S005");
});

test("saving a slot updates cached data without losing selected slot or adjacent slots", () => {
  const adjacent = {slot_id: "S002", status: "AVAILABLE"};
  let state = pilotReducer(initialPilotState, {type: "loaded", layout: {slots: [{slot_id: "S001", status: "AVAILABLE"}, adjacent]}});
  state = pilotReducer(state, {type: "select", slotId: "S001"});
  state = pilotReducer(state, {type: "updated", slot: {slot_id: "S001", status: "BLOCKED"}});
  assert.equal(state.layout.slots[0].status, "BLOCKED");
  assert.equal(state.layout.slots[1], adjacent);
  assert.equal(state.selectedId, "S001");
});
