"""Extracted services recommendation_context helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.decision_policy import derive_mcda_weights
from backend.services.vendors import get_vendor_profile
from fastapi import status as http_status
from backend.core.security import require_vendor_owner

def resolve_recommendation_context(
    payload,
    request: FastAPIRequest,
):
    """Resolve vendor inheritance and decision-policy context."""

    business = (
        payload.business
    )

    division = (
        payload.division
    )

    engine_vendor_id = (
        payload.vendor_id
    )

    profile = None


    if payload.vendor_id:

        require_vendor_owner(
            request,
            payload.vendor_id,
            allow_admin=True,
        )


        profile = get_vendor_profile(
            payload.vendor_id,
            database_path=dependencies.DATABASE_PATH,
        )


        if profile is None:

            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND,
                (
                    "Unknown vendor_id: "
                    f"{payload.vendor_id}"
                ),
            )


        if not business:

            business = (
                profile[
                    "business_category"
                ]
            )


        if not division:

            division = (
                profile[
                    "preferred_division"
                ]
                or ""
            )


        # New operational vendors do not have historical evidence rows.
        if (
            profile[
                "vendor_type"
            ]
            == "NEW"
        ):

            engine_vendor_id = ""


    weight_profile = (
        derive_mcda_weights(
            profile
        )
    )


    return {
        "business":
            business,

        "division":
            division,

        "engine_vendor_id":
            engine_vendor_id,

        "profile":
            profile,

        "weight_profile":
            weight_profile,
    }
