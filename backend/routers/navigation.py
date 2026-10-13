"""Navigation HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import Request as FastAPIRequest
from backend.schemas.api import PilotRouteRequest
from backend.services.pilot_access import authorized_pilot_layout
import backend.services.navigation as pilot_navigation
from backend.services.pilot_access import pilot_operation
from backend.core.security import request_session
from fastapi import APIRouter
router = APIRouter()

@router.get("/api/pilot/navigation")
def pilot_navigation_destination(request: FastAPIRequest):
    request_session(request, "VENDOR")
    return pilot_navigation.destination(authorized_pilot_layout(request))

@router.post("/api/pilot/route")
def pilot_walking_route(body: PilotRouteRequest, request: FastAPIRequest):
    session = request_session(request, "VENDOR")
    target = pilot_navigation.destination(authorized_pilot_layout(request))
    return pilot_operation(lambda: pilot_navigation.walking_route([body.longitude, body.latitude], target,
        identity=session["vendor_id"]))
