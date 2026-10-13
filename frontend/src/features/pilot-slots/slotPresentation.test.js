import test from "node:test";
import assert from "node:assert/strict";
import {googleWalkingLink,publicSlotCategory} from "./slotPresentation.js";
test("external walking directions require own slot and observed access, never fallback centroid", () => {
  const d={slot_id:"S002",approach_observed:true,requested_access_point:[73.77,19.97]};
  assert.match(googleWalkingLink(d,"S002"),/destination=19.97,73.77&travelmode=walking/);
  assert.equal(googleWalkingLink(d,"S009"),null);
  assert.equal(googleWalkingLink({...d,approach_observed:false},"S002"),null);
  assert.equal(googleWalkingLink({...d,requested_access_point:[NaN,19]},"S002"),null);
  assert.equal(googleWalkingLink(null,"S002"),null);
});
test("other-slot presentation uses explicitly public category, not private vendor fields", () => {
  const s={slot_id:"S009",business_category:"food",vendor_name:"Private vendor",assigned_vendor_id:"private-id"};
  assert.equal(publicSlotCategory(s,"S002","flower"),null);
  assert.equal(publicSlotCategory({...s,public_business_category:"vegetable_fruit"},"S002","flower"),"vegetable_fruit");
  assert.equal(publicSlotCategory({...s,slot_id:"S002"},"S002","flower"),"flower");
});
