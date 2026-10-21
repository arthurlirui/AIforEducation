"""Application configuration.

All secrets are read from environment variables so that no API key is ever
hard-coded. Copy `.env.example` to `.env` and fill in the keys you have.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
OUTPUT_DIR = BACKEND_ROOT / "output"
DATA_DIR = BACKEND_ROOT / "app" / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "油画艺术教学平台"
    app_version: str = "0.1.0"
    debug: bool = True

    # CORS – allow the Vite dev server by default
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
        ]
    )

    # Output / storage
    output_dir: Path = OUTPUT_DIR
    output_url_prefix: str = "/files"

    # Default provider used when the client does not specify one.
    # One of: mock, openai, dashscope, zhipu, sdwebui
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "mock")

    # ---- Provider API keys / endpoints ----------------------------------
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "dall-e-3"

    # 阿里云通义万相 (DashScope)
    dashscope_api_key: str = ""
    dashscope_image_model: str = "wanx-v1"

    # 智谱 CogView
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_image_model: str = "cogview-3-plus"

    # Stable Diffusion WebUI (Automatic1111) – local HTTP endpoint
    sdwebui_base_url: str = "http://127.0.0.1:7860"
    sdwebui_sampler: str = "DPM++ 2M Karras"
    sdwebui_steps: int = 30

    # Generation defaults
    default_size: str = "1024x1024"
    request_timeout: int = 120


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    Settings().output_dir.mkdir(parents=True, exist_ok=True)
    return Settings()


settings = get_settings()
