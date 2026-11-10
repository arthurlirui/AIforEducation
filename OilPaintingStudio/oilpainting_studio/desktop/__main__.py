"""桌面入口: pywebview 窗口承载 demo 前端。

- 启动内置 uvicorn (127.0.0.1:8712, 仅本机)
- 挂载 demo API + 静态 demo 页面
- pywebview 打开原生窗口 (EdgeChromium/WebView2 后端)
- PYSTUDIO_DEMO=web 环境变量时仅启动服务 (浏览器访问, CI/无窗口环境)

用法:
    py -m oilpainting_studio.desktop            # 桌面窗口
    PYSTUDIO_DEMO=web py -m oilpainting_studio.desktop   # 浏览器模式
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router as demo_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("paintingstudio.desktop")

HOST = "127.0.0.1"
PORT = 8712
# 桌面 demo 前端构建产物
DEMO_DIST = Path(__file__).resolve().parents[2] / "gui" / "dist"

app = FastAPI(title="PaintingStudio Desktop Demo", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(demo_router)

# 桌面端承载完整前端 (六个视图), 因此工作台 API 也必须挂载:
# 否则 /api/projects 等 404 → 画作库/分割/组装页面"无反应"。
from ..gui.api import routers as gui_routers  # noqa: E402
from ..gui.server import task_queue  # noqa: E402
from .api import set_gpu_lock  # noqa: E402

for _r in (gui_routers.projects_router, gui_routers.objects_router,
           gui_routers.segment_router, gui_routers.gs_router,
           gui_routers.scene_router, gui_routers.keyframes_router,
           gui_routers.compose_router, gui_routers.tasks_router,
           gui_routers.undo_router):
    app.include_router(_r)

# demo 推理与 gui 任务队列共享同一把 GPU 互斥锁 (避免并发抢占显存):
# TaskQueue worker 执行任务前先获取 gpu_lock, /api/demo/run 同样。
set_gpu_lock(task_queue.gpu_lock)


@app.get("/api/demo/health")
def health():
    return {"status": "ok", "app": "paintingstudio-desktop"}


if DEMO_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DEMO_DIST), html=True), name="dist")
    logger.info("demo 前端托管: %s", DEMO_DIST)


def _serve() -> None:
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main() -> None:  # pragma: no cover - 窗口入口
    mode = os.environ.get("PYSTUDIO_DEMO", "window")
    if mode == "web":
        logger.info("浏览器模式: http://%s:%d", HOST, PORT)
        _serve()
        return

    # 后台线程起服务, 主线程开窗口
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    # 等服务就绪
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/demo/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)

    import webview
    window = webview.create_window(
        "PaintingStudio — 论文 Demo",
        f"http://{HOST}:{PORT}/index.html",
        width=1440, height=900, min_size=(1100, 700),
    )
    logger.info("桌面窗口启动 (pywebview)…")
    webview.start()
    logger.info("窗口已关闭, 退出")


if __name__ == "__main__":  # pragma: no cover
    main()
