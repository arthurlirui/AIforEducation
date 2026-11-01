"""Application configuration (environment-overridable)."""
from __future__ import annotations

import os


class Settings:
    app_name: str = "读史 HistorySandbox"
    app_version: str = "0.1.0"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # LLM (optional; local template narrator is the offline fallback)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # timeouts
    llm_timeout_seconds: float = 12.0


settings = Settings()

if env_origins := os.environ.get("HISTORY_CORS_ORIGINS"):
    settings.cors_origins = [o.strip() for o in env_origins.split(",") if o.strip()]

settings.llm_base_url = os.environ.get("HISTORY_LLM_BASE_URL", "").strip() or settings.llm_base_url
settings.llm_api_key = os.environ.get("HISTORY_LLM_API_KEY", "").strip() or settings.llm_api_key
settings.llm_model = os.environ.get("HISTORY_LLM_MODEL", "").strip() or settings.llm_model
