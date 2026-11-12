"""Runtime configuration, read from environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass

BRAND_NAME = "Arogya Drishti"
TAGLINE = "See the warning signs before they become emergencies."
DISCLAIMER = "Clinical decision support only. Not for medical diagnosis."


@dataclass(frozen=True)
class Settings:
    fhir_base_url: str
    fhir_timeout_seconds: float  # status probe only
    sqlite_path: str
    cors_origins: tuple[str, ...]
    fhir_request_timeout_seconds: float = 60.0  # reads, $validate, writes

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080")
        return cls(
            fhir_base_url=os.environ.get("FHIR_BASE_URL", "http://localhost:8090/fhir").rstrip("/"),
            fhir_timeout_seconds=float(os.environ.get("FHIR_TIMEOUT_SECONDS", "3")),
            sqlite_path=os.environ.get("APP_SQLITE_PATH", "./data/app.db"),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            fhir_request_timeout_seconds=float(os.environ.get("FHIR_REQUEST_TIMEOUT_SECONDS", "60")),
        )
