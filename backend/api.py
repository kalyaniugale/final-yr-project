"""Read-only research recommendation API. Run with uvicorn api:app --reload."""
from __future__ import annotations
import sys
import json
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request as FastAPIRequest, Response, status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mcda_engine import ROOT, DATA, recommend, CATEGORIES, derive_mcda_weights
from database import (
    DATABASE_PATH,
    OperationalConflictError,
    OperationalNotFoundError,
    OperationalValidationError,
    approve_allocation_request,
    cancel_allocation_request,
    create_allocation_request,
    get_allocation,
    get_admin_overview,
    get_allocation_request,
    get_active_allocation_for_vendor,
    get_zone_live_status,
    get_live_zone_status_map,
    get_vendor_dashboard_activity,
    list_allocations,
    list_allocation_requests,
    reject_allocation_request,
    update_zone_live_status,
)
from bootstrap import initialize_application
from vendor_service import (
    get_vendor_profile,
    register_vendor,
    update_vendor_profile,
)
from auth_service import (
    AuthError,
    SESSION_COOKIE_NAME,
    bind_onboarding_session,
    cookie_secure,
    create_admin_session,
    create_otp_challenge,
    get_session,
    revoke_session,
    verify_otp_challenge,
)

def validate_configuration_and_schema() -> None:
    """Fail clearly on invalid auth config and safely bootstrap existing data."""
    initialize_application(DATABASE_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_configuration_and_schema()
    yield


app=FastAPI(title="Nashik Vendor Zoning Research API",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],
                   allow_credentials=True,allow_methods=["GET","POST","PATCH"],allow_headers=["Content-Type"])

# Explicitly patched by legacy tests only. Production never enables this flag.
AUTH_TEST_BYPASS = False

def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(np.floating,)):return None if not np.isfinite(value) else float(value)
    if isinstance(value,(np.bool_,)):return bool(value)
    if value is None or value is pd.NA:return None
    if isinstance(value,float) and not np.isfinite(value):return None
    try:
        if pd.isna(value):return None
    except (TypeError,ValueError):pass
    return value

class Request(BaseModel):
    business: str=""
    division: str=""
    vendor_id: str=""
    exclude_zone: str=""
    top_n: int=Field(default=3,ge=1,le=20)
    require_verified: bool=False


class AllocationRequestCreate(BaseModel):
    vendor_id: str
    zone_id: str
    request_type: Literal["NEW_ALLOCATION", "RELOCATION"]
    business_category: str | None = None
    preferred_division: str | None = None
    notes: str | None = None


class AllocationRequestResponse(BaseModel):
    request_id: str
    vendor_id: str
    zone_id: str
    request_type: Literal["NEW_ALLOCATION", "RELOCATION"]
    status: Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"]
    business_category: str | None = None
    preferred_division: str | None = None
    created_at: str
    updated_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None
    vendor_name: str | None = None
    business_name: str | None = None
    application_vendor_id: str | None = None
    vendor_type: Literal["NEW", "EXISTING_IMPORTED"] | None = None


class AllocationRequestListResponse(BaseModel):
    requests: list[AllocationRequestResponse]
    count: int
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"] | None = None


class ApprovalBody(BaseModel):
    notes: str | None = None
    approved_by: str | None = None  # Backward-compatible input; session identity is authoritative.


class RejectionBody(BaseModel):
    rejection_reason: str
    notes: str | None = None
    reviewed_by: str | None = None  # Backward-compatible input; session identity is authoritative.


class AllocationResponse(BaseModel):
    allocation_id: str
    vendor_id: str
    zone_id: str
    request_id: str | None = None
    status: Literal["ACTIVE", "RELEASED"]
    allocated_at: str
    released_at: str | None = None
    approved_by: str | None = None
    created_at: str
    updated_at: str
    application_vendor_id: str | None = None
    vendor_name: str | None = None
    vendor_type: Literal["NEW", "EXISTING_IMPORTED"] | None = None


class AllocationListResponse(BaseModel):
    allocations: list[AllocationResponse]
    count: int
    status_filter: Literal["ACTIVE", "RELEASED"] | None = None


class ApprovalResponse(BaseModel):
    request: AllocationRequestResponse
    allocation: AllocationResponse
    released_allocation: AllocationResponse | None = None


class ZoneLiveStatusResponse(BaseModel):
    zone_id: str
    official_capacity: int | None = None
    current_vendor_count: int
    available_capacity: int | None = None
    status: Literal["OPEN", "FULL", "CLOSED", "SUSPENDED", "RESTRICTED", "NO_VENDING"]
    verified_at: str | None = None
    verified_by: str | None = None
    updated_at: str


class VendorRegistrationBody(BaseModel):
    full_name: str | None = None
    business_name: str | None = None
    business_category: str
    preferred_division: str | None = None
    preferred_locality: str | None = None
    priority_profile: str = "BALANCED"
    parking_preference: StrictBool = False
    transport_preference: StrictBool = False
    market_preference: StrictBool = False
    preferred_language: str = "en"


class VendorProfileUpdateBody(BaseModel):
    full_name: str | None = None
    business_name: str | None = None
    business_category: str | None = None
    preferred_division: str | None = None
    preferred_locality: str | None = None
    priority_profile: str | None = None
    parking_preference: StrictBool | None = None
    transport_preference: StrictBool | None = None
    market_preference: StrictBool | None = None
    preferred_language: str | None = None


class VendorProfileResponse(BaseModel):
    vendor_id: str
    application_vendor_id: str | None = None
    vendor_type: Literal["NEW", "EXISTING_IMPORTED"]
    full_name: str | None = None
    business_name: str | None = None
    business_category: str
    preferred_division: str | None = None
    preferred_locality: str | None = None
    priority_profile: Literal["BALANCED", "COMMERCIAL", "ACCESSIBILITY", "FACILITIES"]
    parking_preference: bool
    transport_preference: bool
    market_preference: bool
    preferred_language: Literal["en", "mr", "hi"]
    status: Literal["ACTIVE", "INACTIVE"]
    created_at: str | None = None
    updated_at: str | None = None


class ActiveVendorAllocationResponse(BaseModel):
    allocation: AllocationResponse | None = None


class AdminZoneStatusBody(BaseModel):
    status: Literal["OPEN", "CLOSED", "SUSPENDED"]
    verified_by: str | None = None  # Backward-compatible input; session identity is authoritative.


class VendorOtpRequestBody(BaseModel):
    mobile: str


class VendorOtpVerifyBody(BaseModel):
    challenge_id: str
    otp: str


class AdminLoginBody(BaseModel):
    username: str
    password: str


ALLOCATION_REQUEST_RESPONSE_FIELDS = [
    "request_id", "vendor_id", "zone_id", "request_type", "status",
    "business_category", "preferred_division", "created_at", "updated_at",
    "reviewed_at", "reviewed_by", "rejection_reason",
]

ALLOCATION_RESPONSE_FIELDS = [
    "allocation_id", "vendor_id", "zone_id", "request_id", "status",
    "allocated_at", "released_at", "approved_by", "created_at", "updated_at",
]

ZONE_LIVE_STATUS_RESPONSE_FIELDS = [
    "zone_id", "official_capacity", "current_vendor_count", "available_capacity",
    "status", "verified_at", "verified_by", "updated_at",
]


def allocation_request_response(row):
    response = {field: row[field] for field in ALLOCATION_REQUEST_RESPONSE_FIELDS}
    profile = get_vendor_profile(row["vendor_id"], database_path=DATABASE_PATH)
    response["vendor_name"] = profile.get("full_name") if profile else None
    response["business_name"] = profile.get("business_name") if profile else None
    response["application_vendor_id"] = profile.get("application_vendor_id") if profile else None
    response["vendor_type"] = profile.get("vendor_type") if profile else None
    return response


def allocation_response(row):
    response = {field: row[field] for field in ALLOCATION_RESPONSE_FIELDS}
    profile = get_vendor_profile(row["vendor_id"], database_path=DATABASE_PATH)
    response["application_vendor_id"] = profile.get("application_vendor_id") if profile else None
    response["vendor_name"] = profile.get("full_name") if profile else None
    response["vendor_type"] = profile.get("vendor_type") if profile else None
    return response


def operational_error(exc: ValueError):
    if isinstance(exc, OperationalNotFoundError):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if isinstance(exc, OperationalConflictError):
        raise HTTPException(http_status.HTTP_409_CONFLICT, str(exc)) from exc
    raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def auth_error(exc: AuthError):
    raise HTTPException(exc.status_code, str(exc)) from exc


def request_session(request: FastAPIRequest, *roles: str) -> dict:
    if AUTH_TEST_BYPASS:
        return {"session_id": "TEST", "role": "ADMIN", "admin_id": "test_admin", "vendor_id": None}
    session = get_session(request.cookies.get(SESSION_COOKIE_NAME), database_path=DATABASE_PATH)
    if session is None:
        raise HTTPException(http_status.HTTP_401_UNAUTHORIZED, "Authentication required")
    if roles and session["role"] not in roles:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "You do not have permission to perform this action")
    return session


def require_vendor_owner(request: FastAPIRequest, vendor_id: str, *, allow_admin: bool = True) -> dict:
    session = request_session(request, "VENDOR", *(('ADMIN',) if allow_admin else ()))
    if session["role"] == "VENDOR" and session["vendor_id"] != vendor_id:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "You may only access your own vendor record")
    return session


def require_request_owner(request: FastAPIRequest, row) -> dict:
    session = request_session(request, "VENDOR", "ADMIN")
    if session["role"] == "VENDOR" and session["vendor_id"] != row["vendor_id"]:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "You may only access your own request")
    return session


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )


def session_payload(session: dict) -> dict:
    payload = {"authenticated": True, "role": session["role"]}
    if session["role"] == "VENDOR":
        payload["vendor_id"] = session["vendor_id"]
        payload["vendor_profile"] = get_vendor_profile(
            session["vendor_id"], database_path=DATABASE_PATH
        )
    elif session["role"] == "ADMIN":
        payload["admin_id"] = session["admin_id"]
    return payload


@lru_cache(maxsize=1)
def official_zone_descriptions() -> dict[str, str]:
    zones = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id": str})
    return dict(zip(zones["zone_id"], zones["official_description"]))


FACTOR_WEIGHTS={"business":25,"commercial":20,"access":20,"facilities":15,"preference":10,"historical":10}
def metric(r,name,digits=0):
    value=r.get(name)
    try:
        x=float(value)
        if np.isfinite(x):return f"{x:,.{digits}f}"
    except (TypeError,ValueError):pass
    return None

def explain(r,factor_weights=None):
    """Source-grounded, deterministic explanations; no generated suitability claims."""
    def count(name):
        x=metric(r,name)
        return x if x is not None else "unknown"
    def distance(name):
        x=metric(r,name)
        return f"{x} m" if x is not None else "unknown"
    n=metric(r,"evidence_count")
    same=metric(r,"same_business_count")
    items={
      "business":{
        "title":"Business compatibility",
        "summary":f"{same or '0'} same-business records among {n or '0'} historical associations.",
        "details":"The score compares the business's historical concentration with its citywide share, using smoothing to reduce the influence of small samples. Presence is not evidence of successful sales.",
        "evidence":[{"label":"Same-business records","value":same or "0"},
                    {"label":"Historical associations","value":n or "0"},
                    {"label":"Evidence source","value":"Text-associated vendor records"}]},
      "commercial":{
        "title":"Commercial surroundings",
        "summary":f"{count('commercial_poi_count_250m')} mapped commercial POIs within 250 m; {count('market_poi_count_500m')} markets within 500 m.",
        "details":"Nearby mapped commercial activity provides context for possible customer activity. It is not measured footfall, sales, or a guarantee of demand.",
        "evidence":[{"label":"Commercial POIs · 250 m","value":count("commercial_poi_count_250m")},
                    {"label":"Markets · 500 m","value":count("market_poi_count_500m")},
                    {"label":"Food POIs · 250 m","value":count("food_poi_count_250m")}]},
      "access":{
        "title":"Road and transport access",
        "summary":f"{distance('distance_to_major_road_m')} from a major road and {distance('distance_to_bus_access_m')} from mapped bus access.",
        "details":"Distances are measured from an approximate analytical reference point. Road density and transport proximity describe access, not pedestrian footfall or traffic safety.",
        "evidence":[{"label":"Major-road distance","value":distance("distance_to_major_road_m")},
                    {"label":"Bus-access distance","value":distance("distance_to_bus_access_m")},
                    {"label":"Pedestrian-road density","value":(metric(r,"pedestrian_road_density_250m_per_km2") or "unknown")+" m/km²"}]},
      "facilities":{
        "title":"Nearby facilities",
        "summary":f"{count('healthcare_count_500m')} healthcare and {count('education_count_500m')} education features mapped within 500 m.",
        "details":"Infrastructure counts describe the surrounding environment. Missing OSM records should not be interpreted as proof that facilities do not exist.",
        "evidence":[{"label":"Healthcare · 500 m","value":count("healthcare_count_500m")},
                    {"label":"Education · 500 m","value":count("education_count_500m")},
                    {"label":"Public toilets · 500 m","value":count("toilet_count_500m")},
                    {"label":"Parking · 500 m","value":count("parking_count_500m")}]},
      "preference":{
        "title":"Preferred division",
        "summary":f"Located in {r.get('zone_division') or 'an unspecified division'}.",
        "details":"A preferred-division match receives a higher preference score. When fewer than three local candidates qualify, the system can show clearly identified alternatives outside the division.",
        "evidence":[{"label":"Zone division","value":r.get("zone_division")},
                    {"label":"Fallback","value":"Yes" if r.get("fallback_used") else "No"}]},
      "historical":{
        "title":"Historical evidence",
        "summary":f"{n or '0'} text-associated vendor records contribute to the evidence-density factor.",
        "details":"This measures the volume of historical association evidence, not current occupancy, available capacity, or commercial success. For an existing vendor, the recorded location group is excluded from its own evidence.",
        "evidence":[{"label":"Association records","value":n or "0"},
                    {"label":"Evidence method","value":r.get("evidence_method")}]} }
    result=[]
    weights=factor_weights or {key:value/100 for key,value in FACTOR_WEIGHTS.items()}
    for key in FACTOR_WEIGHTS:
        item=items[key]
        score=r.get(key+"_score")
        contribution=r.get(key+"_contribution")
        result.append({"key":key,"label":item["title"],"score":score,
            "weight":weights[key]*100,"contribution":contribution,
            "summary":item["summary"],"details":item["details"],"evidence":item["evidence"]})
    return result

@app.get("/api/health")
def health():return {"status":"ok","mode":"research"}


@app.post("/api/auth/vendor/request-otp", tags=["Authentication"])
def request_vendor_otp(payload: VendorOtpRequestBody):
    try:
        return create_otp_challenge(payload.mobile, database_path=DATABASE_PATH)
    except AuthError as exc:
        auth_error(exc)
    except RuntimeError as exc:
        raise HTTPException(503, "Authentication service is not configured") from exc


@app.post("/api/auth/vendor/verify-otp", tags=["Authentication"])
def verify_vendor_otp(payload: VendorOtpVerifyBody, response: Response):
    try:
        token, session = verify_otp_challenge(
            payload.challenge_id, payload.otp, database_path=DATABASE_PATH
        )
    except AuthError as exc:
        auth_error(exc)
    except RuntimeError as exc:
        raise HTTPException(503, "Authentication service is not configured") from exc
    set_session_cookie(response, token)
    return session_payload(session)


@app.post("/api/auth/admin/login", tags=["Authentication"])
def admin_login(payload: AdminLoginBody, response: Response):
    try:
        token, session = create_admin_session(
            payload.username, payload.password, database_path=DATABASE_PATH
        )
    except AuthError as exc:
        auth_error(exc)
    set_session_cookie(response, token)
    return session_payload(session)


@app.get("/api/auth/me", tags=["Authentication"])
def current_user(request: FastAPIRequest):
    session = request_session(request, "VENDOR", "ADMIN", "NEW_VENDOR_ONBOARDING")
    return session_payload(session)


@app.post("/api/auth/logout", tags=["Authentication"])
def logout(request: FastAPIRequest, response: Response):
    revoke_session(request.cookies.get(SESSION_COOKIE_NAME), database_path=DATABASE_PATH)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"authenticated": False}


@app.post(
    "/api/vendors",
    status_code=http_status.HTTP_201_CREATED,
    response_model=VendorProfileResponse,
    tags=["Vendors"],
)
def register_operational_vendor(payload: VendorRegistrationBody, request: FastAPIRequest):
    session = request_session(request, "NEW_VENDOR_ONBOARDING")
    try:
        profile = register_vendor(payload.model_dump(), database_path=DATABASE_PATH)
        if not AUTH_TEST_BYPASS:
            bind_onboarding_session(session["session_id"], profile["vendor_id"], database_path=DATABASE_PATH)
        return profile
    except AuthError as exc:
        auth_error(exc)
    except (OperationalConflictError, OperationalNotFoundError, OperationalValidationError) as exc:
        operational_error(exc)


@app.get("/api/vendors/me/dashboard", tags=["Vendors"])
def vendor_dashboard(request: FastAPIRequest):
    session = request_session(request, "VENDOR")
    vendor_id = session["vendor_id"]
    profile = get_vendor_profile(vendor_id, database_path=DATABASE_PATH)
    if profile is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Vendor profile not found")

    activity = get_vendor_dashboard_activity(vendor_id, DATABASE_PATH)
    descriptions = official_zone_descriptions()
    active_row = activity["active_allocation"]
    active_allocation = None
    if active_row is not None:
        active_allocation = {
            "allocation_id": active_row["allocation_id"],
            "zone_id": active_row["zone_id"],
            "zone_description": descriptions.get(active_row["zone_id"]),
            "allocation_type": active_row["allocation_type"],
            "allocated_at": active_row["allocated_at"],
            "status": active_row["status"],
            "live_zone_status": active_row["live_zone_status"],
            "official_capacity": active_row["official_capacity"],
            "current_vendor_count": active_row["current_vendor_count"],
            "available_capacity": active_row["available_capacity"],
        }

    requests = []
    counts = {status: 0 for status in ("PENDING", "APPROVED", "REJECTED", "CANCELLED")}
    for row in activity["requests"]:
        counts[row["status"]] += 1
        previous_zone_id = activity["previous_zone_by_request"].get(row["request_id"])
        if (
            previous_zone_id is None
            and row["request_type"] == "RELOCATION"
            and row["status"] == "PENDING"
            and active_row is not None
        ):
            previous_zone_id = active_row["zone_id"]
        requests.append({
            "request_id": row["request_id"],
            "request_type": row["request_type"],
            "requested_zone_id": row["zone_id"],
            "zone_description": descriptions.get(row["zone_id"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "reviewed_at": row["reviewed_at"],
            "rejection_reason": row["rejection_reason"],
            "previous_zone_id": previous_zone_id,
            "previous_zone_description": descriptions.get(previous_zone_id),
        })

    has_pending = counts["PENDING"] > 0
    profile_active = profile["status"] == "ACTIVE"
    blocked_reason = None
    if not profile_active:
        blocked_reason = "Vendor profile is inactive"
    elif has_pending:
        blocked_reason = "Pending request already exists"
    return {
        "profile": {
            "vendor_id": profile["vendor_id"],
            "application_vendor_id": profile["application_vendor_id"],
            "vendor_type": profile["vendor_type"],
            "full_name": profile["full_name"],
            "business_name": profile["business_name"],
            "business_category": profile["business_category"],
            "preferred_division": profile["preferred_division"],
            "preferred_locality": profile["preferred_locality"],
            "priority_profile": profile["priority_profile"],
            "prefer_parking": profile["parking_preference"],
            "prefer_transport": profile["transport_preference"],
            "prefer_market": profile["market_preference"],
            "language": profile["preferred_language"],
            "status": profile["status"],
            "created_at": profile["created_at"],
            "updated_at": profile["updated_at"],
        },
        "active_allocation": active_allocation,
        "requests": requests,
        "request_summary": {
            "total_requests": len(requests),
            "pending_count": counts["PENDING"],
            "approved_count": counts["APPROVED"],
            "rejected_count": counts["REJECTED"],
            "cancelled_count": counts["CANCELLED"],
        },
        "action_state": {
            "has_active_allocation": active_allocation is not None,
            "has_pending_request": has_pending,
            "can_submit_request": profile_active and not has_pending,
            "blocked_reason": blocked_reason,
        },
    }


@app.get(
    "/api/vendors/{vendor_id}",
    response_model=VendorProfileResponse,
    tags=["Vendors"],
)
def unified_vendor_profile(vendor_id: str, request: FastAPIRequest):
    require_vendor_owner(request, vendor_id)
    profile = get_vendor_profile(vendor_id, database_path=DATABASE_PATH)
    if profile is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown vendor_id: {vendor_id}")
    return profile


@app.patch(
    "/api/vendors/{vendor_id}",
    response_model=VendorProfileResponse,
    tags=["Vendors"],
)
def patch_vendor_profile(vendor_id: str, payload: VendorProfileUpdateBody, request: FastAPIRequest):
    require_vendor_owner(request, vendor_id)
    try:
        return update_vendor_profile(
            vendor_id,
            payload.model_dump(exclude_unset=True),
            database_path=DATABASE_PATH,
        )
    except (OperationalConflictError, OperationalNotFoundError, OperationalValidationError) as exc:
        operational_error(exc)


@app.get(
    "/api/vendors/{vendor_id}/active-allocation",
    response_model=ActiveVendorAllocationResponse,
    tags=["Vendors"],
)
def vendor_active_allocation(vendor_id: str, request: FastAPIRequest):
    require_vendor_owner(request, vendor_id)
    if get_vendor_profile(vendor_id, database_path=DATABASE_PATH) is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown vendor_id: {vendor_id}")
    row = get_active_allocation_for_vendor(vendor_id, database_path=DATABASE_PATH)
    return {"allocation": allocation_response(row) if row is not None else None}


@app.get("/api/vendors/me/eligible-zones", tags=["Vendors"])
def vendor_eligible_zones(request: FastAPIRequest):
    """Return map context without changing or duplicating recommendation scoring."""
    session = request_session(request, "VENDOR")
    profile = get_vendor_profile(session["vendor_id"], database_path=DATABASE_PATH)
    zones = pd.read_csv(DATA / "candidate_zone_snapshot.csv", dtype={"zone_id": str})
    live = get_live_zone_status_map(DATABASE_PATH)
    zones = zones.loc[
        zones.zone_type.eq("FREE")
        & zones.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true", "1", "yes"])
    ].copy()
    activity = get_vendor_dashboard_activity(session["vendor_id"], DATABASE_PATH)
    pending = next((item for item in activity["requests"] if item["status"] == "PENDING"), None)
    active = activity["active_allocation"]
    current_zone_id = active["zone_id"] if active else None
    pending_zone_id = pending["zone_id"] if pending else None
    highlighted_ids = {zone_id for zone_id in (current_zone_id, pending_zone_id) if zone_id}
    records = []
    for row in zones.itertuples(index=False):
        state = live.get(row.zone_id)
        if state is None:
            continue
        available = state["available_capacity"]
        eligible = state["status"] == "OPEN" and (available is None or available > 0)
        if not eligible and row.zone_id not in highlighted_ids:
            continue
        records.append({
            "zone_id": row.zone_id,
            "zone_division": row.zone_division,
            "zone_type": row.zone_type,
            "official_description": row.official_description,
            "official_capacity": state["official_capacity"],
            "current_vendor_count": state["current_vendor_count"],
            "available_capacity": available,
            "live_status": state["status"],
            "eligible": eligible,
            "preferred_division_match": bool(
                profile and profile.get("preferred_division")
                and row.zone_division == profile["preferred_division"]
            ),
        })
    return {
        "zones": records,
        "count": len(records),
        "current_zone_id": current_zone_id,
        "pending_zone_id": pending_zone_id,
    }


@app.post(
    "/api/allocation-requests",
    status_code=http_status.HTTP_201_CREATED,
    response_model=AllocationRequestResponse,
    tags=["Allocation Requests"],
)
def submit_allocation_request(payload: AllocationRequestCreate, request: FastAPIRequest):
    vendor_id = payload.vendor_id.strip()
    zone_id = payload.zone_id.strip()
    if not vendor_id:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "vendor_id must not be empty")
    if not zone_id:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, "zone_id must not be empty")
    require_vendor_owner(request, vendor_id, allow_admin=False)
    if get_vendor_profile(vendor_id, database_path=DATABASE_PATH) is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown vendor_id: {vendor_id}")
    try:
        row = create_allocation_request(
            vendor_id=vendor_id,
            zone_id=zone_id,
            request_type=payload.request_type,
            business_category=payload.business_category,
            preferred_division=payload.preferred_division,
            notes=payload.notes,
            database_path=DATABASE_PATH,
        )
    except (OperationalNotFoundError, OperationalConflictError, OperationalValidationError) as exc:
        operational_error(exc)
    return allocation_request_response(row)


@app.get(
    "/api/allocation-requests",
    response_model=AllocationRequestListResponse,
    tags=["Allocation Requests"],
)
def allocation_request_list(
    request: FastAPIRequest,
    request_status: Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"] | None = Query(
        default=None, alias="status"
    ),
):
    request_session(request, "ADMIN")
    rows = list_allocation_requests(status=request_status, database_path=DATABASE_PATH)
    return {
        "requests": [allocation_request_response(row) for row in rows],
        "count": len(rows),
        "status_filter": request_status,
    }


@app.get(
    "/api/allocation-requests/{request_id}",
    response_model=AllocationRequestResponse,
    tags=["Allocation Requests"],
)
def allocation_request_detail(request_id: str, request: FastAPIRequest):
    row = get_allocation_request(request_id, database_path=DATABASE_PATH)
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown allocation request: {request_id}")
    require_request_owner(request, row)
    return allocation_request_response(row)


@app.post(
    "/api/allocation-requests/{request_id}/cancel",
    response_model=AllocationRequestResponse,
    tags=["Allocation Requests"],
)
def cancel_request(request_id: str, request: FastAPIRequest):
    existing = get_allocation_request(request_id, database_path=DATABASE_PATH)
    if existing is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown allocation request: {request_id}")
    require_request_owner(request, existing)
    try:
        row = cancel_allocation_request(request_id, database_path=DATABASE_PATH)
    except (OperationalNotFoundError, OperationalConflictError, OperationalValidationError) as exc:
        operational_error(exc)
    return allocation_request_response(row)


@app.post(
    "/api/allocation-requests/{request_id}/approve",
    response_model=ApprovalResponse,
    tags=["Allocation Requests"],
)
def approve_request(request_id: str, payload: ApprovalBody, request: FastAPIRequest):
    session = request_session(request, "ADMIN")
    try:
        result = approve_allocation_request(
            request_id=request_id,
            approved_by=(payload.approved_by if AUTH_TEST_BYPASS and payload.approved_by else session["admin_id"]),
            notes=payload.notes,
            database_path=DATABASE_PATH,
        )
    except (OperationalNotFoundError, OperationalConflictError, OperationalValidationError) as exc:
        operational_error(exc)
    return {
        "request": allocation_request_response(result["request"]),
        "allocation": allocation_response(result["allocation"]),
        "released_allocation": (
            allocation_response(result["released_allocation"])
            if result["released_allocation"] is not None
            else None
        ),
    }


@app.post(
    "/api/allocation-requests/{request_id}/reject",
    response_model=AllocationRequestResponse,
    tags=["Allocation Requests"],
)
def reject_request(request_id: str, payload: RejectionBody, request: FastAPIRequest):
    session = request_session(request, "ADMIN")
    try:
        row = reject_allocation_request(
            request_id=request_id,
            reviewed_by=(payload.reviewed_by if AUTH_TEST_BYPASS and payload.reviewed_by else session["admin_id"]),
            rejection_reason=payload.rejection_reason,
            notes=payload.notes,
            database_path=DATABASE_PATH,
        )
    except (OperationalNotFoundError, OperationalConflictError, OperationalValidationError) as exc:
        operational_error(exc)
    return allocation_request_response(row)


@app.get(
    "/api/allocations",
    response_model=AllocationListResponse,
    tags=["Allocations"],
)
def allocation_list(
    request: FastAPIRequest,
    allocation_status: Literal["ACTIVE", "RELEASED"] | None = Query(
        default=None, alias="status"
    ),
):
    request_session(request, "ADMIN")
    rows = list_allocations(status=allocation_status, database_path=DATABASE_PATH)
    return {
        "allocations": [allocation_response(row) for row in rows],
        "count": len(rows),
        "status_filter": allocation_status,
    }


@app.get(
    "/api/allocations/{allocation_id}",
    response_model=AllocationResponse,
    tags=["Allocations"],
)
def allocation_detail(allocation_id: str, request: FastAPIRequest):
    request_session(request, "ADMIN")
    row = get_allocation(allocation_id, database_path=DATABASE_PATH)
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown allocation: {allocation_id}")
    return allocation_response(row)


@app.get(
    "/api/zones/{zone_id}/live-status",
    response_model=ZoneLiveStatusResponse,
    tags=["Zone Live Status"],
)
def zone_live_status(zone_id: str):
    row = get_zone_live_status(zone_id, database_path=DATABASE_PATH)
    if row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Unknown zone_id: {zone_id}")
    return {field: row[field] for field in ZONE_LIVE_STATUS_RESPONSE_FIELDS}

@app.get("/api/options")
def options():
    z=pd.read_csv(DATA/"candidate_zone_snapshot.csv",usecols=["zone_division"])
    divisions=sorted(x for x in z.zone_division.dropna().unique() if x!="Citywide")
    return {"categories":CATEGORIES,"divisions":divisions,"mode":"exploratory",
            "notice":"No live municipal availability is inferred from historical records."}


@app.get("/api/admin/overview", tags=["Admin"])
def admin_overview(request: FastAPIRequest):
    request_session(request, "ADMIN")
    return get_admin_overview(database_path=DATABASE_PATH)


@app.get("/api/admin/zones", tags=["Admin"])
def admin_zones(
    request: FastAPIRequest,
    division: str = "",
    zone_type: str = "",
    live_status: str = "",
    q: str = "",
):
    request_session(request, "ADMIN")
    zones = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id": str})
    live = pd.DataFrame(get_live_zone_status_map(DATABASE_PATH).values())
    if live.empty:
        live = pd.DataFrame(columns=["zone_id", "official_capacity", "current_vendor_count",
                                     "available_capacity", "status", "verified_at", "verified_by", "updated_at"])
    live = live.rename(columns={"status": "live_status"})
    zones = zones.merge(live, on="zone_id", how="left", suffixes=("_canonical", ""), validate="one_to_one")
    audit_path = ROOT/"reports/data_quality/geometry_duplicates/zone_reference_audit.csv"
    if audit_path.exists():
        audit = pd.read_csv(audit_path, dtype={"zone_id": str})
        audit_columns = [column for column in
                         ["zone_id", "reference_group_id", "shared_reference", "reference_audit_status"]
                         if column in audit]
        zones = zones.merge(audit[audit_columns], on="zone_id", how="left", validate="one_to_one")
    if division:
        zones = zones.loc[zones.division.eq(division)]
    if zone_type:
        zones = zones.loc[zones.zone_type.eq(zone_type)]
    if live_status:
        zones = zones.loc[zones.live_status.eq(live_status)]
    if q:
        term = q.strip()
        zones = zones.loc[
            zones.zone_id.str.contains(term, case=False, na=False, regex=False)
            | zones.official_description.str.contains(term, case=False, na=False, regex=False)
        ]
    fields = [column for column in [
        "zone_id", "division", "zone_type", "official_description", "official_capacity",
        "current_vendor_count", "available_capacity", "live_status", "verified_at",
        "verified_by", "updated_at", "reference_group_id", "shared_reference",
        "reference_audit_status",
    ] if column in zones]
    records = [clean(row) for row in zones[fields].sort_values("zone_id").to_dict("records")]
    return {"zones": records, "count": len(records)}


@app.patch(
    "/api/zones/{zone_id}/live-status",
    response_model=ZoneLiveStatusResponse,
    tags=["Admin", "Zone Live Status"],
)
def patch_zone_live_status(zone_id: str, payload: AdminZoneStatusBody, request: FastAPIRequest):
    session = request_session(request, "ADMIN")
    try:
        row = update_zone_live_status(
            zone_id,
            payload.status,
            (payload.verified_by if AUTH_TEST_BYPASS else session["admin_id"]),
            database_path=DATABASE_PATH,
        )
    except (OperationalNotFoundError, OperationalConflictError, OperationalValidationError) as exc:
        operational_error(exc)
    return {field: row[field] for field in ZONE_LIVE_STATUS_RESPONSE_FIELDS}

@app.get("/api/vendor/{vendor_id}")
def vendor(vendor_id:str):
    # Return only non-identifying model fields. This is not an identity-verification endpoint.
    v=pd.read_csv(DATA/"vendor_training_registry.csv",dtype={"vendor_id":str})
    found=v.loc[v.vendor_id.eq(vendor_id)]
    if found.empty:raise HTTPException(404,"Vendor ID not found")
    r=found.iloc[0]
    return clean({"vendor_id":r.vendor_id,"business_category":r.business_category,
        "division":r.vendor_division,"historical_proposed_zone_id":r.proposed_zone_id,
        "current_zone_verified":r.current_zone_verified,
        "notice":"A historical proposed zone is not a verified current vending location."})

@app.post("/api/recommendations")
def recommendations(req:Request, request: FastAPIRequest):
    business=req.business
    division=req.division
    engine_vendor_id=req.vendor_id
    profile=None
    if req.vendor_id:
        require_vendor_owner(request, req.vendor_id, allow_admin=True)
        profile=get_vendor_profile(req.vendor_id,database_path=DATABASE_PATH)
        if profile is None:
            raise HTTPException(404,f"Unknown vendor_id: {req.vendor_id}")
        if not business:business=profile["business_category"]
        if not division:division=profile["preferred_division"] or ""
        # New operational vendors have no historical evidence row to remove.
        if profile["vendor_type"] == "NEW":engine_vendor_id=""
    weight_profile=derive_mcda_weights(profile)
    effective_weights=weight_profile["final_weights"]
    try:
        result=recommend(business,division,engine_vendor_id,req.top_n,
                         req.exclude_zone,req.require_verified,
                         use_live_status=True,database_path=DATABASE_PATH,
                         factor_weights=effective_weights)
    except ValueError as exc:raise HTTPException(422,str(exc))
    metadata={
        "candidate_count_before_live_filter":result.attrs.get("candidate_count_before_live_filter",0),
        "candidate_count_after_live_filter":result.attrs.get("candidate_count_after_live_filter",0),
        "live_filter_applied":result.attrs.get("live_filter_applied",True),
        "personalization_applied":bool(req.vendor_id),
        "priority_profile":profile["priority_profile"] if profile else "BALANCED",
        "preference_flags":{
            "parking":bool(profile and profile["parking_preference"]),
            "transport":bool(profile and profile["transport_preference"]),
            "market":bool(profile and profile["market_preference"]),
        },
        "base_factor_weights":weight_profile["base_weights"],
        "effective_factor_weights":effective_weights,
        "weight_modifiers":weight_profile["multipliers"],
    }
    if result.empty:
        return {"recommendations":[],"count":0,"mode":"research",
                "notice":"No operationally available zones meet the selected filters. No allocation is inferred.",
                **metadata}
    fields=["rank","zone_id","zone_division","official_description","official_capacity",
        "score","score_type","candidate_status","fallback_used","reference_group_id",
        "shared_reference","shared_reference_group_size","reference_warning",
        "geometry_method","source_confidence","environment_cluster","evidence_count",
        "same_business_count","score_coverage","limitations","reason",
        "verified_available_capacity","verified_at","live_verified","evidence_method",
        "distance_to_major_road_m","distance_to_bus_access_m",
        "pedestrian_road_density_250m_per_km2","commercial_poi_count_250m",
        "market_poi_count_500m","food_poi_count_250m","healthcare_count_500m",
        "education_count_500m","toilet_count_500m","parking_count_500m"]
    fields.extend(["live_status","current_vendor_count","available_capacity"])
    records=[]
    for _,r in result.iterrows():
        item={k:r.get(k) for k in fields}
        item["factors"]=explain(r,effective_weights)
        records.append(clean(item))
    return {"recommendations":records,"count":len(records),"mode":"research",
            "notice":"Illustrative decision-support scores, not probabilities, vacancies, or permits.",
            **metadata}

@app.get("/api/zones/geometry")
def geometry():
    """Reference points only: do not draw draft shared polygons as official areas."""
    path=ROOT/"reports/data_quality/geometry_duplicates/reference_points.geojson"
    if not path.exists():raise HTTPException(503,"Run geometry_duplicate_audit.py first.")
    import json
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

@app.get("/api/zone/{zone_id}")
def zone(zone_id:str):
    z=pd.read_csv(DATA/"candidate_zone_snapshot.csv",dtype={"zone_id":str})
    r=z.loc[z.zone_id.eq(zone_id)]
    if r.empty:raise HTTPException(404,"Zone not found")
    return clean(r.iloc[0].to_dict())


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

@app.get("/api/implementation/summary")
def implementation_summary():
    """Non-sensitive implementation metrics for the local project dashboard."""
    zones = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id":str})
    vendors = pd.read_csv(DATA/"vendor_training_registry.csv", dtype={"vendor_id":str})
    candidate = pd.read_csv(DATA/"candidate_zone_snapshot.csv", dtype={"zone_id":str})
    geom = _read_json(ROOT/"reports/data_quality/geometry_duplicates/audit_summary.json")
    train = _read_json(ROOT/"reports/data_quality/training_data_metrics.json")
    kmeans_meta = _read_json(ROOT/"reports/metrics/kmeans_run.json")
    eval_path = ROOT/"data/model_outputs/kmeans/k_evaluation.csv"
    k_eval = pd.read_csv(eval_path).replace({np.nan: None}).to_dict("records") if eval_path.exists() else []
    return clean({
        "counts":{
            "official_zones":len(zones),
            "registered_vendors":len(vendors),
            "candidate_reference_zones":len(candidate),
            "historical_pairs":train.get("historical_proposed_pairs"),
            "usable_references":geom.get("usable_reference_count"),
            "unique_reference_groups":geom.get("unique_reference_groups"),
            "shared_reference_groups":geom.get("shared_reference_groups")
        },
        "kmeans":{
            "selected_k":kmeans_meta.get("selected_k",2),
            "training_rows":kmeans_meta.get("training_rows"),
            "variant":kmeans_meta.get("variant"),
            "evaluation":k_eval
        },
        "pipeline":[
            {"stage":"01","name":"Data validation","status":"complete","detail":"Schema, IDs, joins and source consistency"},
            {"stage":"02","name":"GIS feature engineering","status":"complete","detail":"Fixed-radius environmental features"},
            {"stage":"03","name":"Vendor-zone evidence","status":"complete","detail":"Historical pair registry and candidate snapshot"},
            {"stage":"04","name":"Environmental clustering","status":"complete","detail":"K-Means baseline and K comparison"},
            {"stage":"05","name":"Recommendation engine","status":"complete","detail":"Transparent weighted MCDA baseline"},
            {"stage":"06","name":"Expert relevance labels","status":"in_progress","detail":"Independent review workflow for supervised evaluation"}
        ],
        "model":{
            "ranking_model":"Weighted MCDA baseline",
            "environment_model":"K-Means environmental profiling",
            "explainability":"Exact weighted factor contributions",
            "shap_used":False
        }
    })

@app.get("/api/official-zones")
def official_zones(division: str = "", zone_type: str = "", limit: int = Query(308, ge=1, le=500)):
    z = pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv", dtype={"zone_id":str})
    if division:
        z = z.loc[z.division.eq(division)]
    if zone_type:
        z = z.loc[z.zone_type.eq(zone_type)]
    audit_path = ROOT/"reports/data_quality/geometry_duplicates/zone_reference_audit.csv"
    if audit_path.exists():
        a = pd.read_csv(audit_path, dtype={"zone_id":str})
        cols=[c for c in ["zone_id","reference_group_id","shared_reference_group_size",
                          "shared_reference","reference_audit_status"] if c in a]
        z=z.merge(a[cols],on="zone_id",how="left",validate="one_to_one")
    cluster_path=ROOT/"data/model_outputs/kmeans/zones_with_clusters.csv"
    if cluster_path.exists():
        c=pd.read_csv(cluster_path,dtype={"zone_id":str})
        if "cluster" in c:
            z=z.merge(c[["zone_id","cluster"]].rename(columns={"cluster":"environment_cluster"}),
                      on="zone_id",how="left",validate="one_to_one")
    fields=[c for c in ["zone_id","division","zone_type","official_description","capacity","category",
                        "environment_cluster","reference_group_id","shared_reference_group_size",
                        "shared_reference","reference_audit_status"] if c in z]
    return {"zones":[clean(r) for r in z[fields].head(limit).to_dict("records")],
            "count":int(min(len(z),limit)),"total_matching":int(len(z))}


@app.get("/api/catalog")
def catalog(zone_type: str="",division: str="",q: str="",limit: int=308):
    """Official record catalogue; geometry and live status remain separate."""
    path=ROOT/"data/raw/nmc/official_zones.csv"
    d=pd.read_csv(path,dtype={"zone_id":str})
    if zone_type:d=d.loc[d.zone_type.eq(zone_type)]
    if division:d=d.loc[d.division.eq(division)]
    if q:
        words=q.strip()
        d=d.loc[d.zone_id.str.contains(words,case=False,na=False,regex=False) |
                d.official_description.str.contains(words,case=False,na=False,regex=False)]
    columns=["zone_id","division","zone_type","official_description","capacity","category"]
    return {"total":len(d),"zones":clean(d[columns].head(max(1,min(limit,308))).to_dict("records"))}

@app.get("/api/overview")
def overview():
    master=pd.read_csv(ROOT/"data/raw/nmc/official_zones.csv")
    vendors=pd.read_csv(DATA/"vendor_training_registry.csv")
    features=pd.read_csv(DATA/"zone_features.csv")
    groups=master.zone_type.value_counts()
    audit=ROOT/"reports/data_quality/geometry_duplicates/audit_summary.json"
    audit_data=json.loads(audit.read_text()) if audit.exists() else {}
    return clean({"official_zones":len(master),"vendor_records":len(vendors),
        "reference_ready":int(features.geometry_usable_for_reference_model.astype(str).str.lower().isin(["true","1","yes"]).sum()),
        "zone_types":groups.to_dict(),"reference_groups":audit_data.get("unique_reference_groups"),
        "shared_reference_zones":audit_data.get("zones_in_shared_reference_groups"),
        "model":{"clustering":"K-Means K=2 baseline","ranking":"Weighted MCDA",
                 "supervised":"Independent relevance collection in progress"}})

@app.get("/api/review-summary")
def review_summary():
    folder=ROOT/"reports/expert_review"
    path=folder/"expert_labels.csv"
    queue=folder/"review_queue.csv"
    if not queue.exists():
        return {"queue_count":0,"judgment_count":0,"reviewer_count":0,"rated_count":0,"abstained_count":0}
    q=pd.read_csv(queue)
    if not path.exists():
        return {"queue_count":len(q),"judgment_count":0,"reviewer_count":0,"rated_count":0,"abstained_count":0}
    d=pd.read_csv(path,dtype=str)
    return {"queue_count":len(q),"judgment_count":len(d),
        "reviewer_count":int(d.reviewer_id.nunique()),
        "rated_count":int(d.relevance.notna().sum()),
        "abstained_count":int(d.relevance.isna().sum())}
