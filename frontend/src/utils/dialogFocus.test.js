import test from "node:test";
import assert from "node:assert/strict";
import {focusCycleIndex} from "./dialogFocus.js";

test("dialog keyboard focus wraps in both directions", () => {
  assert.equal(focusCycleIndex(2, 3), 0);
  assert.equal(focusCycleIndex(0, 3, true), 2);
  assert.equal(focusCycleIndex(1, 3), 2);
});
