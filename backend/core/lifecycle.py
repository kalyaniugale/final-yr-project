"""Extracted core lifecycle helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.bootstrap import initialize_application

def validate_configuration_and_schema() -> None:
    """Validate configuration and safely initialize operational storage."""

    initialize_application(
        dependencies.DATABASE_PATH
    )

@asynccontextmanager
async def lifespan(
    _: FastAPI,
):
    validate_configuration_and_schema()

    yield
