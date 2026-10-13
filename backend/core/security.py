"""Extracted core security helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from backend.services.authentication import AuthError
from fastapi import Request as FastAPIRequest
from fastapi import HTTPException
from backend.repositories.database import OperationalConflictError
from backend.repositories.database import OperationalNotFoundError
from fastapi import Response
from backend.services.authentication import SESSION_COOKIE_NAME
from backend.services.authentication import cookie_secure
from backend.services.vendors import get_vendor_profile
from fastapi import status as http_status

def operational_error(
    exc: ValueError,
):
    """Translate domain errors into HTTP responses."""

    if isinstance(
        exc,
        OperationalNotFoundError,
    ):

        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            str(
                exc
            ),
        ) from exc


    if isinstance(
        exc,
        OperationalConflictError,
    ):

        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            str(
                exc
            ),
        ) from exc


    raise HTTPException(
        422,
        str(
            exc
        ),
    ) from exc

def auth_error(
    exc: AuthError,
):
    """Translate authentication errors."""

    raise HTTPException(
        exc.status_code,
        str(
            exc
        ),
    ) from exc

def request_session(
    request: FastAPIRequest,
    *roles: str,
) -> dict:

    if dependencies.AUTH_TEST_BYPASS:

        return {
            "session_id":
                "TEST",

            "role":
                "ADMIN",

            "admin_id":
                "test_admin",

            "vendor_id":
                None,
        }


    session = dependencies.get_session(
        request.cookies.get(
            SESSION_COOKIE_NAME
        ),
        database_path=dependencies.DATABASE_PATH,
    )


    if session is None:

        raise HTTPException(
            http_status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
        )


    if (
        roles
        and session[
            "role"
        ] not in roles
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You do not have permission "
                "to perform this action"
            ),
        )


    return session

def require_vendor_owner(
    request: FastAPIRequest,
    vendor_id: str,
    *,
    allow_admin: bool = True,
) -> dict:

    permitted_roles = (
        (
            "VENDOR",
            "ADMIN",
        )
        if allow_admin
        else (
            "VENDOR",
        )
    )


    session = request_session(
        request,
        *permitted_roles,
    )


    if (
        session[
            "role"
        ]
        == "VENDOR"

        and session[
            "vendor_id"
        ]
        != vendor_id
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You may only access "
                "your own vendor record"
            ),
        )


    return session

def require_request_owner(
    request: FastAPIRequest,
    row,
) -> dict:

    session = request_session(
        request,
        "VENDOR",
        "ADMIN",
    )


    if (
        session[
            "role"
        ]
        == "VENDOR"

        and session[
            "vendor_id"
        ]
        != row[
            "vendor_id"
        ]
    ):

        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            (
                "You may only access "
                "your own request"
            ),
        )


    return session

def set_session_cookie(
    response: Response,
    token: str,
) -> None:

    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=(
            12
            * 60
            * 60
        ),
        path="/",
    )

def session_payload(
    session: dict,
) -> dict:

    payload = {
        "authenticated":
            True,

        "role":
            session[
                "role"
            ],
    }


    if (
        session[
            "role"
        ]
        == "VENDOR"
    ):

        payload[
            "vendor_id"
        ] = session[
            "vendor_id"
        ]


        payload[
            "vendor_profile"
        ] = get_vendor_profile(
            session[
                "vendor_id"
            ],
            database_path=dependencies.DATABASE_PATH,
        )


    elif (
        session[
            "role"
        ]
        == "ADMIN"
    ):

        payload[
            "admin_id"
        ] = session[
            "admin_id"
        ]


    return payload
