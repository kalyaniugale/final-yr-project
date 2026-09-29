import test from "node:test";
import assert from "node:assert/strict";
import {toastDuration} from "./feedback.js";

test("success feedback auto-dismisses sooner than errors", () => {
  assert.ok(toastDuration("success") < toastDuration("error"));
  assert.ok(toastDuration("error") >= 8000);
});
