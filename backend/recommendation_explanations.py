"""Shared deterministic recommendation explanations for every delivery channel."""
from __future__ import annotations

import numpy as np


FACTOR_WEIGHTS = {
    "business": 25, "commercial": 20, "access": 20,
    "facilities": 15, "preference": 10, "historical": 10,
}


def metric(record, name, digits=0):
    value = record.get(name)
    try:
        numeric = float(value)
        if np.isfinite(numeric):
            return f"{numeric:,.{digits}f}"
    except (TypeError, ValueError):
        pass
    return None


def explain(record, factor_weights=None):
    """Return source-grounded explanations without generated suitability claims."""
    def count(name):
        value = metric(record, name)
        return value if value is not None else "unknown"

    def distance(name):
        value = metric(record, name)
        return f"{value} m" if value is not None else "unknown"

    evidence_count = metric(record, "evidence_count")
    same_business = metric(record, "same_business_count")
    items = {
        "business": {
            "title": "Business compatibility",
            "summary": f"{same_business or '0'} same-business records among {evidence_count or '0'} historical associations.",
            "details": "The score compares the business's historical concentration with its citywide share, using smoothing to reduce the influence of small samples. Presence is not evidence of successful sales.",
            "evidence": [
                {"label": "Same-business records", "value": same_business or "0"},
                {"label": "Historical associations", "value": evidence_count or "0"},
                {"label": "Evidence source", "value": "Text-associated vendor records"},
            ],
        },
        "commercial": {
            "title": "Commercial surroundings",
            "summary": f"{count('commercial_poi_count_250m')} mapped commercial POIs within 250 m; {count('market_poi_count_500m')} markets within 500 m.",
            "details": "Nearby mapped commercial activity provides context for possible customer activity. It is not measured footfall, sales, or a guarantee of demand.",
            "evidence": [
                {"label": "Commercial POIs · 250 m", "value": count("commercial_poi_count_250m")},
                {"label": "Markets · 500 m", "value": count("market_poi_count_500m")},
                {"label": "Food POIs · 250 m", "value": count("food_poi_count_250m")},
            ],
        },
        "access": {
            "title": "Road and transport access",
            "summary": f"{distance('distance_to_major_road_m')} from a major road and {distance('distance_to_bus_access_m')} from mapped bus access.",
            "details": "Distances are measured from an approximate analytical reference point. Road density and transport proximity describe access, not pedestrian footfall or traffic safety.",
            "evidence": [
                {"label": "Major-road distance", "value": distance("distance_to_major_road_m")},
                {"label": "Bus-access distance", "value": distance("distance_to_bus_access_m")},
                {"label": "Pedestrian-road density", "value": (metric(record, "pedestrian_road_density_250m_per_km2") or "unknown") + " m/km²"},
            ],
        },
        "facilities": {
            "title": "Nearby facilities",
            "summary": f"{count('healthcare_count_500m')} healthcare and {count('education_count_500m')} education features mapped within 500 m.",
            "details": "Infrastructure counts describe the surrounding environment. Missing OSM records should not be interpreted as proof that facilities do not exist.",
            "evidence": [
                {"label": "Healthcare · 500 m", "value": count("healthcare_count_500m")},
                {"label": "Education · 500 m", "value": count("education_count_500m")},
                {"label": "Public toilets · 500 m", "value": count("toilet_count_500m")},
                {"label": "Parking · 500 m", "value": count("parking_count_500m")},
            ],
        },
        "preference": {
            "title": "Preferred division",
            "summary": f"Located in {record.get('zone_division') or 'an unspecified division'}.",
            "details": "A preferred-division match receives a higher preference score. When fewer than three local candidates qualify, the system can show clearly identified alternatives outside the division.",
            "evidence": [
                {"label": "Zone division", "value": record.get("zone_division")},
                {"label": "Fallback", "value": "Yes" if record.get("fallback_used") else "No"},
            ],
        },
        "historical": {
            "title": "Historical evidence",
            "summary": f"{evidence_count or '0'} text-associated vendor records contribute to the evidence-density factor.",
            "details": "This measures the volume of historical association evidence, not current occupancy, available capacity, or commercial success. For an existing vendor, the recorded location group is excluded from its own evidence.",
            "evidence": [
                {"label": "Association records", "value": evidence_count or "0"},
                {"label": "Evidence method", "value": record.get("evidence_method")},
            ],
        },
    }
    weights = factor_weights or {key: value / 100 for key, value in FACTOR_WEIGHTS.items()}
    return [{
        "key": key,
        "label": items[key]["title"],
        "score": record.get(key + "_score"),
        "weight": weights[key] * 100,
        "contribution": record.get(key + "_contribution"),
        "summary": items[key]["summary"],
        "details": items[key]["details"],
        "evidence": items[key]["evidence"],
    } for key in FACTOR_WEIGHTS]
