export function profileDisplayName(profile, fallbacks = {}) {
  const name = profile?.full_name?.trim();
  if (name) return name;
  return profile?.vendor_type === "EXISTING_IMPORTED"
    ? (fallbacks.registered || "Registered Vendor")
    : (fallbacks.application || "Application Vendor");
}

export function publicVendorId(profile) {
  if (!profile) return "";
  if (profile.vendor_type === "NEW") return profile.application_vendor_id || "Application ID pending";
  return profile.vendor_id || "";
}
