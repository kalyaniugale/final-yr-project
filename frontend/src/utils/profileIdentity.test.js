import test from "node:test";
import assert from "node:assert/strict";
import {profileDisplayName, publicVendorId} from "./profileIdentity.js";

test("historical vendor name is primary when available", () => {
  assert.equal(profileDisplayName({vendor_type: "EXISTING_IMPORTED", full_name: "Anjala Mahesh Jagtap"}), "Anjala Mahesh Jagtap");
});

test("vendor identity has safe type-specific fallbacks", () => {
  assert.equal(profileDisplayName({vendor_type: "EXISTING_IMPORTED"}), "Registered Vendor");
  assert.equal(profileDisplayName({vendor_type: "NEW"}), "Application Vendor");
});

test("public vendor identity hides the internal UUID for new vendors", () => {
  assert.equal(publicVendorId({vendor_type: "NEW", vendor_id: "NV_internal", application_vendor_id: "NV-2026-000001"}), "NV-2026-000001");
  assert.equal(publicVendorId({vendor_type: "EXISTING_IMPORTED", vendor_id: "V2024_00001"}), "V2024_00001");
});
