"""Application configuration (environment-overridable)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


class Settings:
    app_name: str = "ArtRealm3D 艺境"
    app_version: str = "0.1.0"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Static asset serving
    data_dir: Path = BASE_DIR / "data"
    output_dir: Path = data_dir / "generated"
    output_url_prefix: str = "/static/generated"


settings = Settings()

# Environment overrides
if env_origins := os.environ.get("ARTREALM_CORS_ORIGINS"):
    settings.cors_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
