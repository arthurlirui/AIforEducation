"""回归测试：中文路径 + desktop __main__ 组装冒烟。

T1 (审阅 §9): desktop/__main__.py 挂载 gui routers 零覆盖 — import 冒烟。
T6 (审阅 §9): revive 全流程测试全走 ASCII 路径, 中文路径无守护 —
  在 tmp_path 下建中文项目目录跑关键路径, 锁死 R1/C1 类问题
  （cv2.imread/imwrite 在 Windows 不读非 ASCII 路径）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oilpainting_studio.common.imio import imread_, imwrite_, imread_required  # noqa: E402


# ─────────────────────── T1: desktop __main__ 冒烟 ───────────────────────

def test_desktop_main_app_smoke(tmp_path):
    """__main__.py 挂载 gui routers: import 即可用 + /api/projects 200。

    router 属性名笔误会让桌面入口 import 即崩, 此测试锁住组装正确性。
    注意: gui server 的 registry 是全局单例, 可能已被其他测试指到已删除
    的临时目录 — 冒烟前重置到本测试自己的临时目录。
    """
    import oilpainting_studio.gui.server as srv
    from oilpainting_studio.gui.store import ProjectRegistry
    srv.registry = ProjectRegistry(tmp_path / "projects")

    from fastapi.testclient import TestClient
    from oilpainting_studio.desktop.__main__ import app

    with TestClient(app) as client:
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # demo 路由也挂载
        assert client.get("/api/demo/health").json()["status"] == "ok"


def test_desktop_main_shares_gpu_lock_with_queue():
    """D1: demo run 与 gui TaskQueue 必须共享同一把 GPU 互斥锁。"""
    from oilpainting_studio.desktop import api as demo_api
    from oilpainting_studio.desktop.__main__ import app  # noqa: F401 - 触发组装
    from oilpainting_studio.gui.server import task_queue

    assert demo_api._gpu_lock is task_queue.gpu_lock


# ─────────────────────── T6: 中文路径端到端 ───────────────────────

def test_imio_chinese_path_roundtrip(tmp_path):
    """common/imio 在中文目录下读写。"""
    d = tmp_path / "星月夜" / "子目录"
    img = np.zeros((16, 24, 3), dtype=np.uint8)
    img[:, :, 0] = 200
    p = d / "画.png"
    assert imwrite_(p, img)
    back = imread_(p)
    assert back is not None and back.shape == img.shape
    # imread_required: 读不到抛带路径的明确错误
    with pytest.raises(FileNotFoundError, match="不存在.png"):
        imread_required(d / "不存在.png")


def test_revive_stage1_chinese_project_dir(tmp_path):
    """stage1（分割+深度）在中文项目目录下全产物可读。"""
    from oilpainting_studio.revive.config import load_settings
    from oilpainting_studio.revive.stage1 import run_stage1

    proj = tmp_path / "星月夜项目"
    painting = proj / "原画.png"
    painting.parent.mkdir(parents=True)
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    img[:60, :] = (200, 160, 60)
    img[60:, :] = (60, 140, 40)
    cv2.circle(img, (80, 50), 25, (40, 60, 220), -1)
    imwrite_(painting, img)

    settings = load_settings()
    s1 = run_stage1(painting, proj, settings)
    assert len(s1.objects) >= 1
    assert s1.depth_path.exists() and s1.background_path.exists()
    for obj in s1.objects:
        assert imread_(obj.mask_path, cv2.IMREAD_GRAYSCALE) is not None, obj.mask_path


def test_revive_full_pipeline_chinese_project_dir(tmp_path):
    """四模块 mock 端到端在中文项目目录下跑通（R1 高危路径:
    lineart_parse/stage3/stage4/stage5/eval 全链路中文路径读写）。"""
    from oilpainting_studio.revive.config import load_settings
    from oilpainting_studio.revive.pipeline.director import run_pipeline

    painting = tmp_path / "油画仓库" / "向日葵.png"
    painting.parent.mkdir(parents=True)
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    img[:120, :] = (180, 130, 60)
    img[120:, :] = (80, 120, 60)
    cv2.rectangle(img, (60, 80), (140, 180), (30, 200, 220), -1)
    imwrite_(painting, img)

    settings = load_settings()
    settings.width = 320
    settings.height = 240
    settings.fps = 6
    settings.duration_sec = 1
    settings.focal_length = 400.0
    settings.output_dir = tmp_path / "输出目录"
    settings.gaussians_per_object = 100
    settings.edge_align_iterations = 2
    settings.num_keyframes = 2
    settings.inpaint_radius = 3

    final = run_pipeline(
        settings, painting,
        project_id="中文测试项目",
        use_comfyui=False,
    )
    assert final.exists()
    assert final.suffix == ".mp4"
    assert final.stat().st_size > 0
