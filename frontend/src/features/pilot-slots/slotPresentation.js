export function publicSlotCategory(slot, ownSlotId, ownCategory) {
  if (slot?.slot_id === ownSlotId && ownCategory) return ownCategory;
  return typeof slot?.public_business_category === "string" ? slot.public_business_category : null;
}
export function googleWalkingLink(destination, assignedSlotId) {
  const p = destination?.requested_access_point;
  if (!assignedSlotId || destination?.slot_id !== assignedSlotId || destination?.approach_observed !== true
    || !Array.isArray(p) || p.length !== 2 || !p.every(Number.isFinite)
    || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) return null;
  return `https://www.google.com/maps/dir/?api=1&destination=${p[1]},${p[0]}&travelmode=walking`;
}
