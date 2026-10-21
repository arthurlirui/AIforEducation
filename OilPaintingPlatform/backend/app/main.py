"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import health, styles, generate, teaching, gallery, prompts, providers


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="艺术与油画教学平台 · 文生图后端 API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router, prefix="/api")
    app.include_router(styles.router, prefix="/api")
    app.include_router(generate.router, prefix="/api")
    app.include_router(teaching.router, prefix="/api")
    app.include_router(gallery.router, prefix="/api")
    app.include_router(prompts.router, prefix="/api")
    app.include_router(providers.router, prefix="/api")

    # Serve generated images
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.output_url_prefix,
        StaticFiles(directory=str(settings.output_dir)),
        name="files",
    )

    @app.get("/")
    def root():
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api_prefix": "/api",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
