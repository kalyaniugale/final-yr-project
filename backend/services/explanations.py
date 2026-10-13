"""Extracted services explanations helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.decision_policy import FACTOR_ORDER
from backend.decision_policy import RESEARCH_BASELINE_WEIGHTS
from backend.mcda_engine import ROOT
from functools import lru_cache
import numpy as np
import pandas as pd

@lru_cache(
    maxsize=1
)
def official_zone_descriptions() -> dict[
    str,
    str,
]:

    zones = pd.read_csv(
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    return dict(
        zip(
            zones[
                "zone_id"
            ],
            zones[
                "official_description"
            ],
        )
    )

def metric(
    row,
    name: str,
    digits: int = 0,
):

    value = row.get(
        name
    )


    try:

        numeric = float(
            value
        )


        if np.isfinite(
            numeric
        ):

            return (
                f"{numeric:,.{digits}f}"
            )


    except (
        TypeError,
        ValueError,
    ):
        pass


    return None

def explain(
    row,
    factor_weights=None,
):
    """Return deterministic factor-level explanations."""

    def count(
        name: str,
    ):

        value = metric(
            row,
            name,
        )

        return (
            value
            if value
            is not None
            else "unknown"
        )


    def distance(
        name: str,
    ):

        value = metric(
            row,
            name,
        )

        return (
            f"{value} m"
            if value
            is not None
            else "unknown"
        )


    evidence_count = metric(
        row,
        "evidence_count",
    )


    same_business = metric(
        row,
        "same_business_count",
    )


    items = {

        "business": {
            "title":
                "Business compatibility",

            "summary":
                (
                    f"{same_business or '0'} same-business records "
                    f"among {evidence_count or '0'} historical "
                    "associations."
                ),

            "details":
                (
                    "The score compares the business's historical "
                    "concentration with its citywide share, using "
                    "smoothing to reduce the influence of small samples. "
                    "Presence is not evidence of successful sales."
                ),

            "evidence": [
                {
                    "label":
                        "Same-business records",

                    "value":
                        same_business
                        or "0",
                },
                {
                    "label":
                        "Historical associations",

                    "value":
                        evidence_count
                        or "0",
                },
                {
                    "label":
                        "Evidence source",

                    "value":
                        "Text-associated vendor records",
                },
            ],
        },


        "commercial": {
            "title":
                "Commercial surroundings",

            "summary":
                (
                    f"{count('commercial_poi_count_250m')} mapped "
                    "commercial POIs within 250 m; "
                    f"{count('market_poi_count_500m')} markets "
                    "within 500 m."
                ),

            "details":
                (
                    "Nearby mapped commercial activity provides "
                    "context for possible customer activity. "
                    "It is not measured footfall, sales, or "
                    "a guarantee of demand."
                ),

            "evidence": [
                {
                    "label":
                        "Commercial POIs · 250 m",

                    "value":
                        count(
                            "commercial_poi_count_250m"
                        ),
                },
                {
                    "label":
                        "Markets · 500 m",

                    "value":
                        count(
                            "market_poi_count_500m"
                        ),
                },
                {
                    "label":
                        "Food POIs · 250 m",

                    "value":
                        count(
                            "food_poi_count_250m"
                        ),
                },
            ],
        },


        "access": {
            "title":
                "Road and transport access",

            "summary":
                (
                    f"{distance('distance_to_major_road_m')} "
                    "from a major road and "
                    f"{distance('distance_to_bus_access_m')} "
                    "from mapped bus access."
                ),

            "details":
                (
                    "Distances are measured from an approximate "
                    "analytical reference point. Road density and "
                    "transport proximity describe access, not "
                    "pedestrian footfall or traffic safety."
                ),

            "evidence": [
                {
                    "label":
                        "Major-road distance",

                    "value":
                        distance(
                            "distance_to_major_road_m"
                        ),
                },
                {
                    "label":
                        "Bus-access distance",

                    "value":
                        distance(
                            "distance_to_bus_access_m"
                        ),
                },
                {
                    "label":
                        "Pedestrian-road density",

                    "value":
                        (
                            metric(
                                row,
                                "pedestrian_road_density_250m_per_km2",
                            )
                            or "unknown"
                        )
                        + " m/km²",
                },
            ],
        },


        "facilities": {
            "title":
                "Nearby facilities",

            "summary":
                (
                    f"{count('healthcare_count_500m')} healthcare "
                    f"and {count('education_count_500m')} education "
                    "features mapped within 500 m."
                ),

            "details":
                (
                    "Infrastructure counts describe the surrounding "
                    "environment. Missing OSM records should not be "
                    "interpreted as proof that facilities do not exist."
                ),

            "evidence": [
                {
                    "label":
                        "Healthcare · 500 m",

                    "value":
                        count(
                            "healthcare_count_500m"
                        ),
                },
                {
                    "label":
                        "Education · 500 m",

                    "value":
                        count(
                            "education_count_500m"
                        ),
                },
                {
                    "label":
                        "Public toilets · 500 m",

                    "value":
                        count(
                            "toilet_count_500m"
                        ),
                },
                {
                    "label":
                        "Parking · 500 m",

                    "value":
                        count(
                            "parking_count_500m"
                        ),
                },
            ],
        },


        "preference": {
            "title":
                "Preferred division",

            "summary":
                (
                    "Located in "
                    f"{row.get('zone_division') or 'an unspecified division'}."
                ),

            "details":
                (
                    "A preferred-division match receives a higher "
                    "preference score. When fewer than the requested "
                    "number of local candidates qualify, clearly "
                    "identified alternatives outside the division "
                    "may be returned."
                ),

            "evidence": [
                {
                    "label":
                        "Zone division",

                    "value":
                        row.get(
                            "zone_division"
                        ),
                },
                {
                    "label":
                        "Fallback",

                    "value":
                        (
                            "Yes"
                            if row.get(
                                "fallback_used"
                            )
                            else "No"
                        ),
                },
            ],
        },


        "historical": {
            "title":
                "Historical evidence",

            "summary":
                (
                    f"{evidence_count or '0'} text-associated "
                    "vendor records contribute to the "
                    "evidence-density factor."
                ),

            "details":
                (
                    "This measures the volume of historical "
                    "association evidence, not current occupancy, "
                    "available capacity, or commercial success. "
                    "For an existing historical vendor, its recorded "
                    "location group is excluded from its own evidence."
                ),

            "evidence": [
                {
                    "label":
                        "Association records",

                    "value":
                        evidence_count
                        or "0",
                },
                {
                    "label":
                        "Evidence method",

                    "value":
                        row.get(
                            "evidence_method"
                        ),
                },
            ],
        },
    }


    weights = (
        factor_weights

        or RESEARCH_BASELINE_WEIGHTS
    )


    result = []


    for key in (
        FACTOR_ORDER
    ):

        item = items[
            key
        ]


        result.append(
            {
                "key":
                    key,

                "label":
                    item[
                        "title"
                    ],

                "score":
                    row.get(
                        f"{key}_score"
                    ),

                "weight":
                    (
                        float(
                            weights[
                                key
                            ]
                        )
                        * 100.0
                    ),

                "contribution":
                    row.get(
                        f"{key}_contribution"
                    ),

                "summary":
                    item[
                        "summary"
                    ],

                "details":
                    item[
                        "details"
                    ],

                "evidence":
                    item[
                        "evidence"
                    ],
            }
        )


    return result
