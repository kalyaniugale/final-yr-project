const validCoordinate = coordinates => Array.isArray(coordinates)
  && coordinates.length >= 2
  && Number.isFinite(coordinates[0])
  && Number.isFinite(coordinates[1]);

const coordinateKey = position => `${position[0]}|${position[1]}`;

export function indexPointGeometry(geometry) {
  const index = new Map();
  for (const feature of geometry?.features || []) {
    const zoneId = feature?.properties?.zone_id;
    const coordinates = feature?.geometry?.type === "Point" ? feature.geometry.coordinates : null;
    if (zoneId && validCoordinate(coordinates)) index.set(zoneId, feature);
  }
  return index;
}

function groupRecords(records, geometry, sortMembers) {
  const references = indexPointGeometry(geometry);
  const groupsByCoordinate = new Map();
  const unavailableZoneIds = [];
  for (const record of records) {
    const feature = references.get(record.zone_id);
    if (!feature) {
      unavailableZoneIds.push(record.zone_id);
      continue;
    }
    const [longitude, latitude] = feature.geometry.coordinates;
    const position = [latitude, longitude];
    const key = coordinateKey(position);
    if (!groupsByCoordinate.has(key)) {
      groupsByCoordinate.set(key, {
        key,
        position,
        zones: [],
        referenceGroupIds: new Set(),
      });
    }
    const group = groupsByCoordinate.get(key);
    group.zones.push(record);
    if (feature.properties?.reference_group_id) {
      group.referenceGroupIds.add(feature.properties.reference_group_id);
    }
  }
  const groups = [...groupsByCoordinate.values()].map(group => ({
    ...group,
    zones: [...group.zones].sort(sortMembers),
    shared: group.zones.length > 1,
    referenceGroupId: group.referenceGroupIds.size === 1
      ? [...group.referenceGroupIds][0]
      : null,
  }));
  return {
    groups,
    unavailableZoneIds,
    representedZoneCount: groups.reduce((total, group) => total + group.zones.length, 0),
  };
}

export function buildRecommendationMapModel(recommendations, geometry) {
  return groupRecords(recommendations, geometry, (left, right) => left.rank - right.rank);
}

export function buildVendorExplorerMapModel(recommendations, contextZones, geometry) {
  const recommendedById = new Map(recommendations.map(zone => [zone.zone_id, zone]));
  const records = (contextZones || []).map(zone => ({
    ...zone,
    ...(recommendedById.get(zone.zone_id) || {}),
    is_recommendation: recommendedById.has(zone.zone_id),
  }));
  for (const zone of recommendations) {
    if (!records.some(record => record.zone_id === zone.zone_id)) {
      records.push({...zone, is_recommendation: true});
    }
  }
  return groupRecords(records, geometry, (left, right) =>
    Number(Boolean(right.is_recommendation)) - Number(Boolean(left.is_recommendation))
    || (left.rank || 999) - (right.rank || 999)
    || left.zone_id.localeCompare(right.zone_id)
  );
}

export function vendorVisibleContextZones(context, showAll = false) {
  const zones = context?.zones || [];
  if (showAll) return zones;
  return zones.filter(zone =>
    zone.zone_id === context?.current_zone_id || zone.zone_id === context?.pending_zone_id
  );
}

export function buildAdminMapModel(zones, geometry) {
  return groupRecords(zones, geometry, (left, right) => left.zone_id.localeCompare(right.zone_id));
}

export function uniqueMapPositions(groups) {
  return groups.map(group => group.position);
}
