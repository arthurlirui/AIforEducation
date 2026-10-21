"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import admin, anim, courses, health, sandbox, search


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="TechLearnStudio Backend · 课件仓库 + 托管 + sandbox",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
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

    @app.on_event("startup")
    def _startup():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
