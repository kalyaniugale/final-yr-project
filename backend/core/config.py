"""Project-root environment loading and validated authentication settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


def get_cors_origins() -> list[str]:
    """Explicit frontend origins; local defaults preserve existing behavior."""
    from urllib.parse import urlsplit

    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = [value.strip() for value in raw.split(",") if value.strip()]
    if not origins:
        raise ConfigurationError("CORS_ORIGINS must contain at least one frontend origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or "*" in origin):
            raise ConfigurationError("CORS_ORIGINS must contain explicit HTTP(S) origins")
    return [origin.rstrip("/") for origin in origins]
