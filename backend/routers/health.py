"""Health HTTP endpoints; existing contracts retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import APIRouter
router = APIRouter()

@router.get(
    "/api/health"
)
def health():

    return {
        "status":
            "ok",

        "mode":
            "research",
    }
