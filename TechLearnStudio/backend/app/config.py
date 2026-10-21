"""Backend configuration."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings  # type: ignore


class Settings(BaseSettings):
    app_name: str = "TechLearnStudio Backend"
    app_version: str = "0.1.0"
    db_path: Path = Path("data/techlearn.db")
    static_dir: Path = Path("app/static")
    cors_origins: list[str] = ["*"]
    admin_token: str = "dev-admin-token"  # 仅供开发；生产环境通过环境变量覆盖
    auto_publish_cron: str = "0 * * * *"  # 每小时（占位，M7 实装调度器）

    model_config = {"env_prefix": "TLS_", "env_file": ".env"}


settings = Settings()
