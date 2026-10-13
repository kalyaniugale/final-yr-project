"""Extracted services pilot_access helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.repositories.database import OperationalConflictError
from backend.repositories.database import OperationalNotFoundError
from backend.repositories.database import OperationalValidationError
import backend.services.pilot_slots as pilot_slots
from backend.core.security import request_session

def pilot_operation(operation):
    try:
        return operation()
    except OperationalNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except OperationalConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OperationalValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Invalid pilot geometry or navigation payload") from exc

def authorized_pilot_layout(request: FastAPIRequest):
    session = request_session(request, "ADMIN", "VENDOR")
    if session["role"] == "VENDOR":
        with pilot_slots.transaction(dependencies.DATABASE_PATH) as db:
            allocation = db.execute("""SELECT a.allocation_id FROM allocations a
                JOIN allocation_requests r ON r.request_id = a.request_id
                WHERE a.vendor_id = ? AND a.zone_id = ? AND a.status = 'ACTIVE'
                AND r.status = 'APPROVED' AND r.vendor_id = a.vendor_id AND r.zone_id = a.zone_id""",
                (session["vendor_id"], pilot_slots.PILOT_ZONE_ID)).fetchone()
        if not allocation:
            raise HTTPException(403, "A current approved allocation to the pilot zone is required")
    layout = pilot_operation(lambda: pilot_slots.get_layout(dependencies.DATABASE_PATH))
    if session["role"] == "VENDOR":
        layout["my_slot_id"] = next((s["slot_id"] for s in layout["slots"]
                                      if s["assigned_vendor_id"] == session["vendor_id"]), None)
        for slot in layout["slots"]:
            if slot["assigned_vendor_id"] != session["vendor_id"]:
                slot["assigned_vendor_id"] = None
    return layout
