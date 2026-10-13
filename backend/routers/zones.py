"""Zones HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.schemas.api import AdminZoneStatusBody
from backend.mcda_engine import CATEGORIES
from backend.mcda_engine import DATA
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from backend.repositories.database import OperationalConflictError
from backend.repositories.database import OperationalNotFoundError
from backend.repositories.database import OperationalValidationError
from fastapi import Query
from backend.mcda_engine import ROOT
from backend.schemas.response_fields import ZONE_LIVE_STATUS_RESPONSE_FIELDS
from backend.schemas.api import ZoneLiveStatusResponse
from backend.core.serialization import clean
from backend.repositories.database import get_live_zone_status_map
from backend.repositories.database import get_zone_live_status
from fastapi import status as http_status
import json
from backend.decision_policy import load_base_weight_policy
from backend.core.security import operational_error
import pandas as pd
from backend.core.security import request_session
from backend.repositories.database import update_zone_live_status
from fastapi import APIRouter
router = APIRouter()

@router.get(
    "/api/zones/{zone_id}/live-status",
    response_model=(
        ZoneLiveStatusResponse
    ),
    tags=[
        "Zone Live Status"
    ],
)
def zone_live_status(
    zone_id: str,
):

    row = get_zone_live_status(
        zone_id,
        database_path=dependencies.DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown zone_id: {zone_id}",
        )


    return {
        field:
            row[
                field
            ]

        for field
        in ZONE_LIVE_STATUS_RESPONSE_FIELDS
    }

@router.patch(
    "/api/zones/{zone_id}/live-status",
    response_model=(
        ZoneLiveStatusResponse
    ),
    tags=[
        "Admin",
        "Zone Live Status",
    ],
)
def patch_zone_live_status(
    zone_id: str,
    payload: AdminZoneStatusBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    verified_by = (
        payload.verified_by

        if (
            dependencies.AUTH_TEST_BYPASS
            and payload.verified_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        row = update_zone_live_status(
            zone_id,
            payload.status,
            verified_by,
            database_path=dependencies.DATABASE_PATH,
        )


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    return {
        field:
            row[
                field
            ]

        for field
        in ZONE_LIVE_STATUS_RESPONSE_FIELDS
    }

@router.get(
    "/api/options"
)
def options():

    zones = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        usecols=[
            "zone_division"
        ],
    )


    divisions = sorted(
        value

        for value
        in zones[
            "zone_division"
        ]
        .dropna()
        .unique()

        if value
        != "Citywide"
    )


    policy = (
        load_base_weight_policy()
    )


    return {
        "categories":
            CATEGORIES,

        "divisions":
            divisions,

        "mode":
            "research",

        "weight_source":
            policy[
                "source"
            ],

        "notice":
            (
                "Recommendations use operational "
                "zone status when available. "
                "Historical vendor evidence is not "
                "treated as current occupancy, "
                "vacancy, demand, or business success."
            ),
    }

@router.get(
    "/api/zones/geometry"
)
def geometry():
    """Return analytical reference points only."""

    path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "reference_points.geojson"
    )


    if not path.exists():

        raise HTTPException(
            503,
            (
                "Run geometry_duplicate_audit.py "
                "first."
            ),
        )


    return JSONResponse(
        json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    )

@router.get(
    "/api/zone/{zone_id}"
)
def zone(
    zone_id: str,
):

    zones = pd.read_csv(
        DATA
        / "candidate_zone_snapshot.csv",
        dtype={
            "zone_id":
                str,
        },
    )


    result = zones.loc[
        zones.zone_id.eq(
            zone_id
        )
    ]


    if result.empty:

        raise HTTPException(
            404,
            "Zone not found",
        )


    return clean(
        result.iloc[
            0
        ].to_dict()
    )

@router.get(
    "/api/admin/zones",
    tags=[
        "Admin"
    ],
)
def admin_zones(
    request: FastAPIRequest,
    division: str = "",
    zone_type: str = "",
    live_status: str = "",
    q: str = "",
):

    request_session(
        request,
        "ADMIN",
    )


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


    live = pd.DataFrame(
        get_live_zone_status_map(
            dependencies.DATABASE_PATH
        ).values()
    )


    if live.empty:

        live = pd.DataFrame(
            columns=[
                "zone_id",
                "official_capacity",
                "current_vendor_count",
                "available_capacity",
                "status",
                "verified_at",
                "verified_by",
                "updated_at",
            ]
        )


    live = live.rename(
        columns={
            "status":
                "live_status",
        }
    )


    zones = zones.merge(
        live,
        on="zone_id",
        how="left",
        suffixes=(
            "_canonical",
            "",
        ),
        validate="one_to_one",
    )


    audit_path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "zone_reference_audit.csv"
    )


    if audit_path.exists():

        audit = pd.read_csv(
            audit_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        audit_columns = [
            column

            for column
            in [
                "zone_id",
                "reference_group_id",
                "shared_reference",
                "reference_audit_status",
            ]

            if column
            in audit.columns
        ]


        zones = zones.merge(
            audit[
                audit_columns
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    if division:

        zones = zones.loc[
            zones.division.eq(
                division
            )
        ]


    if zone_type:

        zones = zones.loc[
            zones.zone_type.eq(
                zone_type
            )
        ]


    if live_status:

        zones = zones.loc[
            zones.live_status.eq(
                live_status
            )
        ]


    if q:

        term = q.strip()


        zones = zones.loc[
            zones.zone_id.str.contains(
                term,
                case=False,
                na=False,
                regex=False,
            )
            | zones[
                "official_description"
            ].str.contains(
                term,
                case=False,
                na=False,
                regex=False,
            )
        ]


    fields = [
        column

        for column
        in [
            "zone_id",
            "division",
            "zone_type",
            "official_description",
            "official_capacity",
            "current_vendor_count",
            "available_capacity",
            "live_status",
            "verified_at",
            "verified_by",
            "updated_at",
            "reference_group_id",
            "shared_reference",
            "reference_audit_status",
        ]

        if column
        in zones.columns
    ]


    records = [
        clean(
            row
        )

        for row
        in (
            zones[
                fields
            ]
            .sort_values(
                "zone_id"
            )
            .to_dict(
                "records"
            )
        )
    ]


    return {
        "zones":
            records,

        "count":
            len(
                records
            ),
    }

@router.get(
    "/api/official-zones"
)
def official_zones(
    division: str = "",
    zone_type: str = "",
    limit: int = Query(
        308,
        ge=1,
        le=500,
    ),
):

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


    if division:

        zones = zones.loc[
            zones.division.eq(
                division
            )
        ]


    if zone_type:

        zones = zones.loc[
            zones.zone_type.eq(
                zone_type
            )
        ]


    audit_path = (
        ROOT
        / "reports"
        / "data_quality"
        / "geometry_duplicates"
        / "zone_reference_audit.csv"
    )


    if audit_path.exists():

        audit = pd.read_csv(
            audit_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        columns = [
            column

            for column
            in [
                "zone_id",
                "reference_group_id",
                "shared_reference_group_size",
                "shared_reference",
                "reference_audit_status",
            ]

            if column
            in audit.columns
        ]


        zones = zones.merge(
            audit[
                columns
            ],
            on="zone_id",
            how="left",
            validate="one_to_one",
        )


    cluster_path = (
        ROOT
        / "data"
        / "model_outputs"
        / "kmeans"
        / "zones_with_clusters.csv"
    )


    if cluster_path.exists():

        clusters = pd.read_csv(
            cluster_path,
            dtype={
                "zone_id":
                    str,
            },
        )


        if (
            "cluster"
            in clusters.columns
        ):

            zones = zones.merge(
                clusters[
                    [
                        "zone_id",
                        "cluster",
                    ]
                ].rename(
                    columns={
                        "cluster":
                            "environment_cluster",
                    }
                ),
                on="zone_id",
                how="left",
                validate="one_to_one",
            )


    fields = [
        column

        for column
        in [
            "zone_id",
            "division",
            "zone_type",
            "official_description",
            "capacity",
            "category",
            "environment_cluster",
            "reference_group_id",
            "shared_reference_group_size",
            "shared_reference",
            "reference_audit_status",
        ]

        if column
        in zones.columns
    ]


    records = [
        clean(
            row
        )

        for row
        in (
            zones[
                fields
            ]
            .head(
                limit
            )
            .to_dict(
                "records"
            )
        )
    ]


    return {
        "zones":
            records,

        "count":
            int(
                min(
                    len(
                        zones
                    ),
                    limit,
                )
            ),

        "total_matching":
            int(
                len(
                    zones
                )
            ),
    }

@router.get(
    "/api/catalog"
)
def catalog(
    zone_type: str = "",
    division: str = "",
    q: str = "",
    limit: int = 308,
):
    """Official records only; geometry/live state remain separate."""

    path = (
        ROOT
        / "data"
        / "raw"
        / "nmc"
        / "official_zones.csv"
    )


    data = pd.read_csv(
        path,
        dtype={
            "zone_id":
                str,
        },
    )


    if zone_type:

        data = data.loc[
            data.zone_type.eq(
                zone_type
            )
        ]


    if division:

        data = data.loc[
            data.division.eq(
                division
            )
        ]


    if q:

        words = q.strip()


        data = data.loc[
            data.zone_id.str.contains(
                words,
                case=False,
                na=False,
                regex=False,
            )
            | data[
                "official_description"
            ].str.contains(
                words,
                case=False,
                na=False,
                regex=False,
            )
        ]


    columns = [
        "zone_id",
        "division",
        "zone_type",
        "official_description",
        "capacity",
        "category",
    ]


    safe_limit = max(
        1,
        min(
            limit,
            308,
        ),
    )


    return {
        "total":
            len(
                data
            ),

        "zones":
            clean(
                data[
                    columns
                ]
                .head(
                    safe_limit
                )
                .to_dict(
                    "records"
                )
            ),
    }
