"""Configuration is loaded at startup; secrets are never logged."""
import os
import re
from dataclasses import dataclass, field


@dataclass
class Settings:
    access_token: str = field(repr=False)
    phone_number_id: str
    verify_token: str = field(repr=False)
    app_secret: str = field(repr=False)
    graph_version: str
    backend_url: str = "http://127.0.0.1:8000"
    db_path: str = "backend/whatsapp/sessions.sqlite3"
    session_ttl: int = 86400
    timeout: float = 15

    @classmethod
    def from_env(cls):
        names = ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
                 "WHATSAPP_VERIFY_TOKEN", "META_APP_SECRET", "GRAPH_API_VERSION"]
        if any(not os.getenv(k, "").strip() for k in names):
            raise ValueError("Set all required variables listed in whatsapp/.env.example")
        s = cls(*(os.environ[k].strip() for k in names),
                backend_url=os.getenv("RECOMMENDATION_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
                db_path=os.getenv("WHATSAPP_DB_PATH", "backend/whatsapp/sessions.sqlite3"),
                session_ttl=int(os.getenv("SESSION_TTL_SECONDS", "86400")),
                timeout=float(os.getenv("HTTP_TIMEOUT_SECONDS", "15")))
        if not re.fullmatch(r"v\d+\.\d+", s.graph_version) or not s.phone_number_id.isdigit():
            raise ValueError("Invalid Graph version or Phone Number ID format")
        if s.session_ttl <= 0 or s.timeout <= 0:
            raise ValueError("Expiry and timeout must be positive")
        if not s.backend_url.startswith(("http://", "https://")):
            raise ValueError("Backend URL must use HTTP or HTTPS")
        return s
