"""Pilot Slots HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.schemas.api import PilotGeometryEdit
from backend.schemas.api import PilotGeometryPreview
from backend.schemas.api import PilotGeometrySave
from backend.schemas.api import PilotSlotUpdate
from backend.services.pilot_access import authorized_pilot_layout
from backend.services.pilot_access import pilot_operation
import backend.services.pilot_slots as pilot_slots
from backend.core.security import request_session
from fastapi import APIRouter
router = APIRouter()

@router.get("/api/pilot/layout")
def get_pilot_layout(request: FastAPIRequest):
    return authorized_pilot_layout(request)

@router.post("/api/pilot/initialize")
def initialize_pilot_layout(request: FastAPIRequest):
    request_session(request, "ADMIN")
    return pilot_operation(lambda: pilot_slots.initialize_demo(dependencies.DATABASE_PATH))

@router.get("/api/pilot/slots/{slot_id}")
def get_pilot_slot(slot_id: str, request: FastAPIRequest):
    layout = authorized_pilot_layout(request)
    slot = next((s for s in layout["slots"] if s["slot_id"] == slot_id), None)
    if slot is None:
        raise HTTPException(404, "Unknown pilot slot")
    return slot

@router.patch("/api/pilot/slots/{slot_id}")
def patch_pilot_slot(slot_id: str, body: PilotSlotUpdate, request: FastAPIRequest):
    session = request_session(request, "ADMIN")
    return pilot_operation(lambda: pilot_slots.update_slot(
        slot_id, body.status, body.assigned_vendor_id, actor=session["admin_id"],
        expected_updated_at=body.expected_updated_at, database_path=dependencies.DATABASE_PATH))

@router.post("/api/pilot/preview")
def preview_pilot_geometry(body: PilotGeometryPreview, request: FastAPIRequest):
    request_session(request, "ADMIN")
    return pilot_operation(lambda: pilot_slots.preview_geographic(body.config, dependencies.DATABASE_PATH, body.obstructions))

@router.post("/api/pilot/validate")
def validate_pilot_edit(body: PilotGeometryEdit, request: FastAPIRequest):
    request_session(request, "ADMIN")
    return pilot_operation(lambda: pilot_slots.preview_edit(body.layout, body.poses, dependencies.DATABASE_PATH))

@router.patch("/api/pilot/layout")
def save_pilot_geometry(body: PilotGeometrySave, request: FastAPIRequest):
    session = request_session(request, "ADMIN")
    return pilot_operation(lambda: pilot_slots.save_geographic(body.layout, actor=session["admin_id"],
        review_confirmed=body.review_confirmed, database_path=dependencies.DATABASE_PATH))
