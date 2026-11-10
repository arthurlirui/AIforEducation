"""桌面 demo 的 API 层 (挂在 GUI server 的 /api/demo/* 下)。

端点 (设计文档 §4):
- GET  /api/demo/device           设备探测 + 当前档位 + 后端矩阵
- POST /api/demo/run              跑一次三步 demo (可指定 prefer 档位)
- GET  /api/demo/runs             历史 demo 运行记录
- GET  /api/demo/artifact/{path}  demo 产物文件 (overlay/depth/ply)
- POST /api/demo/benchmark        当前档位基准测试
- POST /api/demo/paintings        上传/注册示例画作 (multipart)
- GET  /api/demo/paintings        示例画作列表
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse

from ..gui.imgio import imread, imwrite
from ..gui.store import atomic_write_json, read_json
from .device import DeviceTier, probe_device
from .engine import PaintingStudioDemoEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])

# demo 数据根: 项目目录旁的独立 demo 区
DEMO_ROOT = Path(__file__).resolve().parents[2] / "projects" / "_demo"
PAINTINGS_DIR = DEMO_ROOT / "paintings"
RUNS_DIR = DEMO_ROOT / "runs"
MAX_RUNS_KEPT = 30  # runs/ 保留最近 N 个, 超出清理最旧

# GPU 互斥锁: desktop 组装时（__main__.py）用 set_gpu_lock 注入与 gui
# TaskQueue 共享的同一把锁, 保证 demo 推理与任务队列不并发抢占 GPU。
# 默认独立锁（独立 demo app 场景仍保证并发 run 串行）。
_gpu_lock = threading.Lock()

_engine_lock = threading.Lock()
_engine: PaintingStudioDemoEngine | None = None


def set_gpu_lock(lock: threading.Lock) -> None:
    """注入共享 GPU 锁（与 TaskQueue 同一把）。"""
    global _gpu_lock
    _gpu_lock = lock


def _get_engine(prefer: str = "auto") -> PaintingStudioDemoEngine:
    """全局 demo 引擎 (按 prefer 重建, GPU→CPU→mock 回退在引擎内完成)。"""
    global _engine
    with _engine_lock:
        if _engine is None or _engine.choice.requested != prefer:
            _engine = PaintingStudioDemoEngine(DEMO_ROOT, prefer=prefer)
        return _engine


def _ensure_dirs() -> None:
    PAINTINGS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────── device ───────────────────────────

@router.get("/device")
def get_device(prefer: str = "auto"):
    """设备探测报告 (不重建引擎, 轻量探测)。"""
    report = probe_device(prefer)
    from .device import resolve_choice
    choice = resolve_choice(prefer, report)
    return {"report": report.to_dict(),
            "requested": choice.requested,
            "effective": choice.effective.value,
            "reason": choice.reason}


# ─────────────────────────── paintings ───────────────────────────

@router.get("/paintings")
def list_paintings():
    _ensure_dirs()
    out = []
    for d in sorted(PAINTINGS_DIR.iterdir()):
        meta_p = d / "meta.json"
        if meta_p.exists():
            out.append(read_json(meta_p))
    return out


@router.post("/paintings", status_code=201)
async def upload_painting(name: str = Form(...), painting: UploadFile = File(...)):
    _ensure_dirs()
    slug = name.replace("/", "-").replace("\\", "-")[:60] or "untitled"
    d = PAINTINGS_DIR / slug
    if d.exists():
        raise HTTPException(409, f"示例画作已存在: {slug}")
    d.mkdir(parents=True)
    suffix = Path(painting.filename or "p.png").suffix or ".png"
    # 统一 ASCII 文件名 (cv2 中文路径限制)
    src = d / "painting.png"
    src.write_bytes(await painting.read())
    img = imread(src)
    if img is None:
        raise HTTPException(400, "无法读取图像")
    h, w = img.shape[:2]
    # 缩略图
    scale = 512 / max(h, w)
    if scale < 1:
        imwrite(d / "thumb.png", cv2_resize_safe(img, scale))
    else:
        imwrite(d / "thumb.png", img)
    meta = {"name": slug, "painting_path": "painting.png",
            "thumb_path": "thumb.png", "width": w, "height": h}
    atomic_write_json(d / "meta.json", meta)
    return meta


def cv2_resize_safe(img, scale: float):
    import cv2
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * scale), int(h * scale)))


# ─────────────────────────── run ───────────────────────────

class DemoRunRequest(BaseModel):
    painting: str
    prefer: Literal["auto", "gpu", "cpu", "mock"] = "auto"


@router.post("/run")
def run_demo(req: DemoRunRequest):
    """跑一次三步 demo, 同步返回完整 timeline (demo 单次数秒内, 无需异步队列)。"""
    painting = req.painting
    prefer = req.prefer
    _ensure_dirs()
    meta_p = PAINTINGS_DIR / painting / "meta.json"
    if not meta_p.exists():
        raise HTTPException(404, f"示例画作不存在: {painting}")
    painting_path = PAINTINGS_DIR / painting / "painting.png"
    if not painting_path.exists():
        raise HTTPException(404, f"画作文件缺失: {painting}")

    try:
        engine = _get_engine(prefer)
    except Exception as e:
        raise HTTPException(500, f"引擎初始化失败: {e}")

    # 毫秒后缀: 同秒两次运行不共用 out_dir
    run_id = (datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]
              + f"-{engine.choice.effective.value}")
    out_dir = RUNS_DIR / run_id
    try:
        # GPU 互斥: 与 gui TaskQueue 共享同一把锁 (D1), 且 per-engine 串行 (D2)
        with _gpu_lock:
            run = engine.run_locked(painting_path, out_dir)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("demo run 失败")
        raise HTTPException(500, f"demo 运行失败: {e}")

    # 运行记录落盘 + 清理旧 runs（保留最近 MAX_RUNS_KEPT 个）
    record = {"run_id": run_id, "painting": painting,
              "ts": datetime.now().isoformat(),
              "device": run.to_dict()}
    atomic_write_json(out_dir / "run.json", record)
    _cleanup_runs()
    return record


def _cleanup_runs() -> None:
    """runs/ 只保留最近 MAX_RUNS_KEPT 个目录, 超出删最旧。"""
    try:
        dirs = sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()),
                      key=lambda d: d.name, reverse=True)
        for old in dirs[MAX_RUNS_KEPT:]:
            import shutil
            shutil.rmtree(old, ignore_errors=True)
    except OSError as e:  # 清理失败不影响主流程
        logger.warning("runs 清理失败: %s", e)


@router.get("/runs")
def list_runs():
    _ensure_dirs()
    out = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        rp = d / "run.json"
        if rp.exists():
            out.append(read_json(rp))
    return out[:30]


@router.get("/artifact/{run_id}/{filename}")
def get_artifact(run_id: str, filename: str):
    # 防目录穿越
    if ".." in run_id or ".." in filename or "/" in run_id or "\\" in run_id:
        raise HTTPException(400, "非法路径")
    p = RUNS_DIR / run_id / filename
    if not p.exists():
        raise HTTPException(404, f"{run_id}/{filename}")
    media = "model/ply" if filename.endswith(".ply") else "image/png"
    return FileResponse(p, media_type=media)


# ── 可独立导入的 demo 子应用 (测试与 web 模式共用) ──
# 桌面窗口入口见 __main__.py (在其上叠加静态托管)。
from fastapi import FastAPI  # noqa: E402

app = FastAPI(title="PaintingStudio Desktop Demo API", version="0.1.0")
app.include_router(router)


@app.get("/api/demo/health")
def _health():
    return {"status": "ok", "app": "paintingstudio-desktop"}
