"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .rate_limit import SlidingWindowRateLimiter
from .routers import health, styles, generate, teaching, gallery, prompts, providers
from .services.generate_service import GALLERY_INDEX


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="艺术与油画教学平台 · 文生图后端 API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Simple per-IP sliding-window rate limit on the generate endpoint.
    limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if (
            settings.rate_limit_enabled
            and request.method == "POST"
            and request.url.path == "/api/generate"
        ):
            client_ip = request.client.host if request.client else "unknown"
            if not limiter.allow(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后重试"},
                )
        return await call_next(request)

    # Routers
    app.include_router(health.router, prefix="/api")
    app.include_router(styles.router, prefix="/api")
    app.include_router(generate.router, prefix="/api")
    app.include_router(generate.preview_router, prefix="/api")
    app.include_router(teaching.router, prefix="/api")
    app.include_router(gallery.router, prefix="/api")
    app.include_router(prompts.router, prefix="/api")
    app.include_router(providers.router, prefix="/api")

    # gallery.json is runtime data (git-ignored): auto-create on first run
    if not GALLERY_INDEX.exists():
        GALLERY_INDEX.parent.mkdir(parents=True, exist_ok=True)
        GALLERY_INDEX.write_text("[]", encoding="utf-8")

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
