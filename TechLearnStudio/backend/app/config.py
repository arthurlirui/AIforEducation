"""Backend configuration."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings  # type: ignore

# 路径锚定 backend 包目录，而不是进程 cwd（避免从仓库根跑测试/服务时
# 在根目录重建 app/、data/ 残留目录）
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "TechLearnStudio Backend"
    app_version: str = "0.1.0"
    db_path: Path = _BACKEND_DIR / "data" / "techlearn.db"
    static_dir: Path = _BACKEND_DIR / "app" / "static"
    # B7：CORS 白名单（env TLS_CORS_ORIGINS 可覆盖，JSON 数组格式）
    cors_origins: list[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",  # vite dev
        "http://localhost:4173", "http://127.0.0.1:4173",  # vite preview
        "http://localhost:8000", "http://127.0.0.1:8000",  # uvicorn 默认
    ]
    # B6：默认空 token = 未配置即拒绝所有写操作（fail-safe）；
    # 生产/开发都需要显式设置 TLS_ADMIN_TOKEN
    admin_token: str = ""

    model_config = {"env_prefix": "TLS_", "env_file": ".env"}


settings = Settings()
