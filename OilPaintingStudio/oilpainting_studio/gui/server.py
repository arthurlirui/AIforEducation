"""FastAPI app 组装 + dev 入口。

启动:  py -m oilpainting_studio.gui.server
访问:  http://127.0.0.1:8710  (API docs: /docs)
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import routers
from .store import ProjectRegistry
from .tasks import get_queue

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("paintingstudio")

# projects 根目录: 项目目录自包含, 可整目录拷贝迁移 (§3.2)
# oilpainting_studio/gui/server.py → 上三级 = OilPaintingStudio/
_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = _ROOT / "projects"
DIST_DIR = _ROOT / "gui" / "dist"

registry = ProjectRegistry(PROJECTS_ROOT)
task_queue = get_queue()

app = FastAPI(
    title="PaintingStudio",
    version="0.1.0",
    description="画作物体级三维编辑与动画工作站 API (设计文档: docs/paintingstudio_gui_design.md)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (routers.projects_router, routers.objects_router, routers.segment_router,
          routers.gs_router, routers.scene_router, routers.keyframes_router,
          routers.compose_router, routers.tasks_router, routers.undo_router):
    app.include_router(r)


@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    if DIST_DIR.is_dir():
        return RedirectResponse(url="/index.html")
    return {
        "app": "PaintingStudio",
        "version": "0.1.0",
        "docs": "/docs",
        "projects_root": str(PROJECTS_ROOT),
        "endpoints": ["/api/projects", "/api/tasks", "/api/projects/{id}/scene", "..."],
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 前端构建产物 (npm run build 后自动托管)
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="dist")
    logger.info("前端静态托管: %s", DIST_DIR)


def main() -> None:  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8710)


if __name__ == "__main__":  # pragma: no cover
    main()
