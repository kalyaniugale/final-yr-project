"""Auth HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.schemas.api import AdminLoginBody
from backend.services.authentication import AuthError
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from fastapi import Response
from backend.services.authentication import SESSION_COOKIE_NAME
from backend.schemas.api import VendorOtpRequestBody
from backend.schemas.api import VendorOtpVerifyBody
from backend.core.security import auth_error
from backend.services.authentication import create_admin_session
from backend.services.authentication import create_otp_challenge
from backend.core.security import request_session
from backend.services.authentication import revoke_session
from backend.core.security import session_payload
from backend.core.security import set_session_cookie
from backend.services.authentication import verify_otp_challenge
from fastapi import APIRouter
router = APIRouter()

@router.post(
    "/api/auth/vendor/request-otp",
    tags=[
        "Authentication"
    ],
)
def request_vendor_otp(
    payload: VendorOtpRequestBody,
):

    try:

        return create_otp_challenge(
            payload.mobile,
            database_path=dependencies.DATABASE_PATH,
        )

    except AuthError as exc:

        auth_error(
            exc
        )

    except RuntimeError as exc:

        raise HTTPException(
            503,
            (
                "Authentication service "
                "is not configured"
            ),
        ) from exc

@router.post(
    "/api/auth/vendor/verify-otp",
    tags=[
        "Authentication"
    ],
)
def verify_vendor_otp(
    payload: VendorOtpVerifyBody,
    response: Response,
):

    try:

        token, session = (
            verify_otp_challenge(
                payload.challenge_id,
                payload.otp,
                database_path=dependencies.DATABASE_PATH,
            )
        )

    except AuthError as exc:

        auth_error(
            exc
        )

    except RuntimeError as exc:

        raise HTTPException(
            503,
            (
                "Authentication service "
                "is not configured"
            ),
        ) from exc


    set_session_cookie(
        response,
        token,
    )


    return session_payload(
        session
    )

@router.post(
    "/api/auth/admin/login",
    tags=[
        "Authentication"
    ],
)
def admin_login(
    payload: AdminLoginBody,
    response: Response,
):

    try:

        token, session = (
            create_admin_session(
                payload.username,
                payload.password,
                database_path=dependencies.DATABASE_PATH,
            )
        )

    except AuthError as exc:

        auth_error(
            exc
        )


    set_session_cookie(
        response,
        token,
    )


    return session_payload(
        session
    )

@router.get(
    "/api/auth/me",
    tags=[
        "Authentication"
    ],
)
def current_user(
    request: FastAPIRequest,
):

    session = request_session(
        request,
        "VENDOR",
        "ADMIN",
        "NEW_VENDOR_ONBOARDING",
    )


    return session_payload(
        session
    )

@router.post(
    "/api/auth/logout",
    tags=[
        "Authentication"
    ],
)
def logout(
    request: FastAPIRequest,
    response: Response,
):

    revoke_session(
        request.cookies.get(
            SESSION_COOKIE_NAME
        ),
        database_path=dependencies.DATABASE_PATH,
    )


    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
    )


    return {
        "authenticated":
            False,
    }
