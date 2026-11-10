"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import admin, anim, courses, health, sandbox, search


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="TechLearnStudio Backend · 课件仓库 + 托管 + sandbox",
        lifespan=lifespan,
    )

    # B7：显式 Origin 白名单（settings 可配），不回显任意 Origin；
    # 无 cookie 认证，关闭 credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(courses.router, prefix="/api")
    app.include_router(sandbox.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(anim.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    settings.static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.get("/")
    def root():
        return {"name": settings.app_name, "version": settings.app_version,
                "docs": "/docs", "api_prefix": "/api"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
