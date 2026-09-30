"""Project-root environment loading and validated authentication settings."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# Explicit process environment values win over values in the project .env file.
load_dotenv(dotenv_path=ENV_FILE, override=False)


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is absent or invalid."""


@dataclass(frozen=True)
class AuthSettings:
    app_env: str
    auth_hmac_secret: str
    session_cookie_secure: bool
    otp_provider: str
    otp_debug: bool
    nmc_admin_username: str
    nmc_admin_password: str


@dataclass(frozen=True)
class WhatsAppSettings:
    access_token: str
    phone_number_id: str
    verify_token: str
    meta_app_secret: str
    graph_version: str


_REQUIRED_AUTH_VARIABLES = (
    "APP_ENV",
    "AUTH_HMAC_SECRET",
    "SESSION_COOKIE_SECURE",
    "OTP_PROVIDER",
    "OTP_DEBUG",
    "NMC_ADMIN_USERNAME",
    "NMC_ADMIN_PASSWORD",
)


def _required_value(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise ConfigurationError(f"Required configuration variable is missing: {name}")
    return value


def _boolean_value(name: str) -> bool:
    value = _required_value(name).strip().lower()
    if value not in {"true", "false"}:
        raise ConfigurationError(f"Configuration variable {name} must be true or false")
    return value == "true"


def get_auth_settings() -> AuthSettings:
    """Read current environment values and fail without disclosing their contents."""
    missing = [name for name in _REQUIRED_AUTH_VARIABLES if not os.environ.get(name, "").strip()]
    if missing:
        raise ConfigurationError(
            "Missing required authentication configuration: " + ", ".join(missing)
        )
    return AuthSettings(
        app_env=_required_value("APP_ENV").strip().lower(),
        auth_hmac_secret=_required_value("AUTH_HMAC_SECRET"),
        session_cookie_secure=_boolean_value("SESSION_COOKIE_SECURE"),
        otp_provider=_required_value("OTP_PROVIDER").strip().lower(),
        otp_debug=_boolean_value("OTP_DEBUG"),
        nmc_admin_username=_required_value("NMC_ADMIN_USERNAME"),
        nmc_admin_password=_required_value("NMC_ADMIN_PASSWORD"),
    )


def get_whatsapp_settings() -> WhatsAppSettings:
    """Validate direct Meta Cloud API configuration without exposing values."""
    names = (
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
        "META_APP_SECRET",
        "WHATSAPP_GRAPH_VERSION",
    )
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ConfigurationError(
            "Missing required WhatsApp configuration: " + ", ".join(missing)
        )
    graph_version = _required_value("WHATSAPP_GRAPH_VERSION").strip()
    if not re.fullmatch(r"v\d+\.\d+", graph_version):
        raise ConfigurationError("WHATSAPP_GRAPH_VERSION must use the form vNN.N")
    return WhatsAppSettings(
        access_token=_required_value("WHATSAPP_ACCESS_TOKEN"),
        phone_number_id=_required_value("WHATSAPP_PHONE_NUMBER_ID").strip(),
        verify_token=_required_value("WHATSAPP_VERIFY_TOKEN"),
        meta_app_secret=_required_value("META_APP_SECRET"),
        graph_version=graph_version,
    )
