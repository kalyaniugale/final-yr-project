"""Shared dependency bindings and legacy test configuration. No HTTP handlers."""
from __future__ import annotations
import json

import sys

from contextlib import asynccontextmanager

from functools import lru_cache

from pathlib import Path

from typing import Any, Literal

import numpy as np

import pandas as pd

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request as FastAPIRequest,
    Response,
    status as http_status,
)

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
)

from backend.mcda_engine import ROOT, DATA, CATEGORIES, recommend

from backend.decision_policy import DEFAULT_POLICY_PATH, FACTOR_ORDER, RESEARCH_BASELINE_WEIGHTS, derive_mcda_weights, load_base_weight_policy

from backend.recommendation_evaluation import SensitivityConfig, evaluate_weight_sensitivity

from backend.allocation_optimizer import AllocationOptimizationError

from backend.allocation_planning_service import AllocationPlanningValidationError, plan_vendor_allocations

from backend.repositories.database import DATABASE_PATH, OperationalConflictError, OperationalNotFoundError, OperationalValidationError, approve_allocation_request, cancel_allocation_request, create_allocation_request, get_allocation, get_admin_overview, get_allocation_request, get_active_allocation_for_vendor, get_zone_live_status, get_live_zone_status_map, get_vendor_dashboard_activity, list_allocations, list_allocation_requests, reject_allocation_request, update_zone_live_status

from backend.bootstrap import initialize_application

import backend.services.pilot_slots as pilot_slots

import backend.services.navigation as pilot_navigation

from backend.services.vendors import get_vendor_profile, register_vendor, update_vendor_profile

from backend.services.authentication import AuthError, SESSION_COOKIE_NAME, bind_onboarding_session, cookie_secure, create_admin_session, create_otp_challenge, get_session, revoke_session, verify_otp_challenge
AUTH_TEST_BYPASS = False

from backend.schemas.response_fields import ALLOCATION_REQUEST_RESPONSE_FIELDS

from backend.schemas.response_fields import ALLOCATION_RESPONSE_FIELDS

from backend.schemas.response_fields import ZONE_LIVE_STATUS_RESPONSE_FIELDS

from backend.schemas.api import *
from backend.core.lifecycle import validate_configuration_and_schema, lifespan
from backend.core.serialization import clean, _read_json, _csv_row_count
from backend.core.security import operational_error, auth_error, request_session, require_vendor_owner, require_request_owner, set_session_cookie, session_payload
from backend.services.responses import allocation_request_response, allocation_response
from backend.services.explanations import official_zone_descriptions, metric, explain
from backend.services.recommendation_context import resolve_recommendation_context
from backend.services.pilot_access import pilot_operation, authorized_pilot_layout
