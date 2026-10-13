"""Allocations HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.schemas.api import AllocationListResponse
from backend.allocation_optimizer import AllocationOptimizationError
from backend.schemas.api import AllocationPlanningBody
from backend.allocation_planning_service import AllocationPlanningValidationError
from backend.schemas.api import AllocationRequestCreate
from backend.schemas.api import AllocationRequestListResponse
from backend.schemas.api import AllocationRequestResponse
from backend.schemas.api import AllocationResponse
from backend.schemas.api import ApprovalBody
from backend.schemas.api import ApprovalResponse
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from typing import Literal
from backend.repositories.database import OperationalConflictError
from backend.repositories.database import OperationalNotFoundError
from backend.repositories.database import OperationalValidationError
from fastapi import Query
from backend.schemas.api import RejectionBody
from backend.services.responses import allocation_request_response
from backend.services.responses import allocation_response
from backend.repositories.database import approve_allocation_request
from backend.repositories.database import cancel_allocation_request
from backend.core.serialization import clean
from backend.repositories.database import create_allocation_request
from backend.repositories.database import get_admin_overview
from backend.repositories.database import get_allocation
from backend.repositories.database import get_allocation_request
from backend.services.vendors import get_vendor_profile
from fastapi import status as http_status
from backend.repositories.database import list_allocation_requests
from backend.repositories.database import list_allocations
from backend.core.security import operational_error
from backend.allocation_planning_service import plan_vendor_allocations
from backend.repositories.database import reject_allocation_request
from backend.core.security import request_session
from backend.core.security import require_request_owner
from backend.core.security import require_vendor_owner
from fastapi import APIRouter
router = APIRouter()

@router.post(
    "/api/allocation-requests",
    status_code=(
        http_status
        .HTTP_201_CREATED
    ),
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def submit_allocation_request(
    payload: AllocationRequestCreate,
    request: FastAPIRequest,
):

    vendor_id = (
        payload.vendor_id.strip()
    )


    zone_id = (
        payload.zone_id.strip()
    )


    if not vendor_id:

        raise HTTPException(
            422,
            "vendor_id must not be empty",
        )


    if not zone_id:

        raise HTTPException(
            422,
            "zone_id must not be empty",
        )


    require_vendor_owner(
        request,
        vendor_id,
        allow_admin=False,
    )


    if (
        get_vendor_profile(
            vendor_id,
            database_path=dependencies.DATABASE_PATH,
        )
        is None
    ):

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown vendor_id: {vendor_id}",
        )


    try:

        row = create_allocation_request(
            vendor_id=vendor_id,
            zone_id=zone_id,
            request_type=(
                payload.request_type
            ),
            business_category=(
                payload.business_category
            ),
            preferred_division=(
                payload.preferred_division
            ),
            notes=(
                payload.notes
            ),
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


    return allocation_request_response(
        row
    )

@router.get(
    "/api/allocation-requests",
    response_model=(
        AllocationRequestListResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def allocation_request_list(
    request: FastAPIRequest,
    request_status: (
        Literal[
            "PENDING",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
        ]
        | None
    ) = Query(
        default=None,
        alias="status",
    ),
):

    request_session(
        request,
        "ADMIN",
    )


    rows = list_allocation_requests(
        status=request_status,
        database_path=dependencies.DATABASE_PATH,
    )


    return {
        "requests": [
            allocation_request_response(
                row
            )
            for row
            in rows
        ],

        "count":
            len(
                rows
            ),

        "status_filter":
            request_status,
    }

@router.get(
    "/api/allocation-requests/{request_id}",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def allocation_request_detail(
    request_id: str,
    request: FastAPIRequest,
):

    row = get_allocation_request(
        request_id,
        database_path=dependencies.DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            (
                "Unknown allocation request: "
                f"{request_id}"
            ),
        )


    require_request_owner(
        request,
        row,
    )


    return allocation_request_response(
        row
    )

@router.post(
    "/api/allocation-requests/{request_id}/cancel",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def cancel_request(
    request_id: str,
    request: FastAPIRequest,
):

    existing = get_allocation_request(
        request_id,
        database_path=dependencies.DATABASE_PATH,
    )


    if existing is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            (
                "Unknown allocation request: "
                f"{request_id}"
            ),
        )


    require_request_owner(
        request,
        existing,
    )


    try:

        row = cancel_allocation_request(
            request_id,
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


    return allocation_request_response(
        row
    )

@router.post(
    "/api/allocation-requests/{request_id}/approve",
    response_model=ApprovalResponse,
    tags=[
        "Allocation Requests"
    ],
)
def approve_request(
    request_id: str,
    payload: ApprovalBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    approved_by = (
        payload.approved_by

        if (
            dependencies.AUTH_TEST_BYPASS
            and payload.approved_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        result = approve_allocation_request(
            request_id=request_id,
            approved_by=approved_by,
            notes=payload.notes,
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
        "request":
            allocation_request_response(
                result[
                    "request"
                ]
            ),

        "allocation":
            allocation_response(
                result[
                    "allocation"
                ]
            ),

        "released_allocation":
            (
                allocation_response(
                    result[
                        "released_allocation"
                    ]
                )

                if result[
                    "released_allocation"
                ]
                is not None

                else None
            ),
    }

@router.post(
    "/api/allocation-requests/{request_id}/reject",
    response_model=(
        AllocationRequestResponse
    ),
    tags=[
        "Allocation Requests"
    ],
)
def reject_request(
    request_id: str,
    payload: RejectionBody,
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "ADMIN",
    )


    reviewed_by = (
        payload.reviewed_by

        if (
            dependencies.AUTH_TEST_BYPASS
            and payload.reviewed_by
        )

        else session[
            "admin_id"
        ]
    )


    try:

        row = reject_allocation_request(
            request_id=request_id,
            reviewed_by=reviewed_by,
            rejection_reason=(
                payload.rejection_reason
            ),
            notes=(
                payload.notes
            ),
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


    return allocation_request_response(
        row
    )

@router.get(
    "/api/allocations",
    response_model=AllocationListResponse,
    tags=[
        "Allocations"
    ],
)
def allocation_list(
    request: FastAPIRequest,
    allocation_status: (
        Literal[
            "ACTIVE",
            "RELEASED",
        ]
        | None
    ) = Query(
        default=None,
        alias="status",
    ),
):

    request_session(
        request,
        "ADMIN",
    )


    rows = list_allocations(
        status=allocation_status,
        database_path=dependencies.DATABASE_PATH,
    )


    return {
        "allocations": [
            allocation_response(
                row
            )
            for row
            in rows
        ],

        "count":
            len(
                rows
            ),

        "status_filter":
            allocation_status,
    }

@router.get(
    "/api/allocations/{allocation_id}",
    response_model=AllocationResponse,
    tags=[
        "Allocations"
    ],
)
def allocation_detail(
    allocation_id: str,
    request: FastAPIRequest,
):

    request_session(
        request,
        "ADMIN",
    )


    row = get_allocation(
        allocation_id,
        database_path=dependencies.DATABASE_PATH,
    )


    if row is None:

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            f"Unknown allocation: {allocation_id}",
        )


    return allocation_response(
        row
    )

@router.post(
    "/api/admin/allocation-plan",
    tags=[
        "Admin",
        "Allocation Planning",
    ],
)
def create_allocation_plan(
    payload: AllocationPlanningBody,
    request: FastAPIRequest,
):
    """Create an advisory multi-vendor allocation plan.

    No database mutation occurs here.
    """

    request_session(
        request,
        "ADMIN",
    )


    try:

        result = (
            plan_vendor_allocations(
                payload.vendor_ids,
                database_path=(
                    dependencies.DATABASE_PATH
                ),
                require_verified=(
                    payload.require_verified
                ),
                candidate_pool_size=(
                    payload.candidate_pool_size
                ),
                reject_pending_requests=(
                    payload.reject_pending_requests
                ),
                max_vendors=(
                    payload.max_vendors
                ),
                time_limit_seconds=(
                    payload.time_limit_seconds
                ),
            )
        )


    except AllocationPlanningValidationError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    except (
        OperationalNotFoundError,
        OperationalConflictError,
        OperationalValidationError,
    ) as exc:

        operational_error(
            exc
        )


    except ValueError as exc:

        raise HTTPException(
            422,
            str(
                exc
            ),
        ) from exc


    except AllocationOptimizationError as exc:

        raise HTTPException(
            503,
            (
                "Allocation optimizer could "
                f"not produce a plan: {exc}"
            ),
        ) from exc


    return clean(
        result.to_dict()
    )

@router.get(
    "/api/admin/overview",
    tags=[
        "Admin"
    ],
)
def admin_overview(
    request: FastAPIRequest,
):

    request_session(
        request,
        "ADMIN",
    )


    return get_admin_overview(
        database_path=dependencies.DATABASE_PATH
    )
