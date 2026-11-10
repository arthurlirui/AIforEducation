"""PaintingStudio 桌面 demo 测试 (设备回退 / 引擎 / API)。

覆盖设计文档 docs/paintingstudio_desktop_demo.md §3–§4:
- probe_device: auto/gpu/cpu/mock 四种偏好的档位解析与回退
- resolve_choice: 不可用档位的回退原因
- DemoEngine: 三步 run 全档位可跑、产物落盘、计时记录
- API: device/paintings/run/runs/artifact 合约与错误码
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oilpainting_studio.desktop.api import app  # noqa: E402
from oilpainting_studio.desktop.device import (  # noqa: E402
    DeviceTier, probe_device, resolve_choice,
)
from oilpainting_studio.desktop.engine import PaintingStudioDemoEngine  # noqa: E402


# ─────────────────────── device: 档位解析 ───────────────────────

def test_probe_auto_uses_cuda_when_available():
    """本机有 CUDA: auto 应探测为 GPU 档。"""
    report = probe_device("auto")
    assert report.tier in (DeviceTier.GPU, DeviceTier.CPU, DeviceTier.MOCK)
    if report.cuda_available:
        assert report.tier == DeviceTier.GPU
        assert report.cuda_device_name
        assert report.vram_gb and report.vram_gb > 0


def test_probe_forced_mock():
    report = probe_device("mock")
    assert report.tier == DeviceTier.MOCK
    assert report.backends["segment"].kind.value == "mock_segment"
    assert report.backends["depth"].kind.value == "mock_depth"


def test_probe_report_serializable():
    import json
    report = probe_device("auto")
    data = json.loads(json.dumps(report.to_dict()))
    assert data["tier"] in ("gpu", "cpu", "mock")
    assert "segment" in data["backends"] and "depth" in data["backends"]


def test_resolve_choice_fallback_reason():
    """请求 GPU 但只有 CPU 时: 回退并给出原因。"""
    from oilpainting_studio.desktop.device import DeviceReport
    cpu_only = DeviceReport(tier=DeviceTier.CPU)
    c = resolve_choice("gpu", cpu_only)
    assert c.effective == DeviceTier.CPU
    assert "回退" in c.reason

    mock_only = DeviceReport(tier=DeviceTier.MOCK)
    c2 = resolve_choice("gpu", mock_only)
    assert c2.effective == DeviceTier.MOCK
    assert "回退" in c2.reason

    # 请求低于可用档 (有 GPU 请求 CPU) → 尊重请求
    gpu = DeviceReport(tier=DeviceTier.GPU)
    c3 = resolve_choice("cpu", gpu)
    assert c3.effective == DeviceTier.CPU


# ─────────────────────── engine: 三步 demo ───────────────────────

@pytest.fixture(scope="module")
def demo_painting(tmp_path_factory):
    p = tmp_path_factory.mktemp("demo") / "village.png"
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    img[:, :, 0] = 200; img[:, :, 1] = 165
    img[140:, :] = (50, 130, 40)
    cv2.circle(img, (70, 70), 30, (40, 60, 220), -1)
    cv2.rectangle(img, (220, 130), (290, 210), (30, 200, 220), -1)
    cv2.imwrite(str(p), img)
    return p


@pytest.mark.parametrize("prefer", ["mock", "cpu", "auto"])
def test_engine_runs_all_tiers(tmp_path, demo_painting, prefer):
    """三步 demo 在 mock/cpu/auto 档都能跑通并落盘产物。"""
    engine = PaintingStudioDemoEngine(tmp_path, prefer=prefer)
    out_dir = tmp_path / "run1"
    run = engine.run(demo_painting, out_dir)

    assert len(run.steps) == 3
    names = [s.name for s in run.steps]
    assert "PaintParse 分割" in names[0]
    assert "MonoDepth 深度" in names[1]
    assert "MonoSplat 3D 化身" in names[2]
    for s in run.steps:
        assert s.ok and s.ms >= 0
    assert run.total_ms >= 0

    # 产物落盘
    assert (out_dir / "overlay.png").exists()
    assert (out_dir / "depth.png").exists()
    assert (out_dir / "depth_vis.png").exists()
    ply = out_dir / "scene.ply"
    assert ply.exists() and ply.read_bytes().startswith(b"ply")

    # auto 档在有 CUDA 机器上应至少尝试真模型; mock 档必然 mock
    if prefer == "mock":
        assert engine.choice.effective == DeviceTier.MOCK


def test_engine_run_dict(tmp_path, demo_painting):
    import json
    engine = PaintingStudioDemoEngine(tmp_path, prefer="mock")
    run = engine.run(demo_painting, tmp_path / "r")
    data = json.loads(json.dumps(run.to_dict()))
    assert data["device_effective"] in ("gpu", "cpu", "mock")
    assert len(data["steps"]) == 3
    assert all("ms" in s and "summary" in s for s in data["steps"])


def test_engine_missing_painting(tmp_path):
    engine = PaintingStudioDemoEngine(tmp_path, prefer="mock")
    with pytest.raises(FileNotFoundError):
        engine.run(tmp_path / "nope.png", tmp_path / "r")


# ─────────────────────── API 合约 ───────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """demo API 测试端: 把 DEMO_ROOT 指到临时目录。"""
    from oilpainting_studio.desktop import api as demo_api
    monkeypatch.setattr(demo_api, "PAINTINGS_DIR", tmp_path / "paintings")
    monkeypatch.setattr(demo_api, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(demo_api, "DEMO_ROOT", tmp_path)
    # 重置全局引擎, 避免跨测试档位残留
    monkeypatch.setattr(demo_api, "_engine", None)
    yield TestClient(app)


def test_api_health(client):
    assert client.get("/api/demo/health").json()["status"] == "ok"


def test_api_device(client):
    r = client.get("/api/demo/device")
    assert r.status_code == 200
    d = r.json()
    assert d["report"]["tier"] in ("gpu", "cpu", "mock")
    assert d["effective"] in ("gpu", "cpu", "mock")
    assert "segment" in d["report"]["backends"]

    # 强制 mock 探测
    r = client.get("/api/demo/device?prefer=mock")
    assert r.json()["effective"] == "mock"


def test_api_paintings_upload_and_run(client, demo_painting):
    # 上传示例画作
    with open(demo_painting, "rb") as f:
        r = client.post("/api/demo/paintings",
                        data={"name": "村庄"},
                        files={"painting": ("v.png", f, "image/png")})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["width"] == 320 and meta["height"] == 240

    # 重复上传 409
    with open(demo_painting, "rb") as f:
        r = client.post("/api/demo/paintings", data={"name": "村庄"},
                        files={"painting": ("v.png", f, "image/png")})
    assert r.status_code == 409

    # 列表
    paintings = client.get("/api/demo/paintings").json()
    assert len(paintings) == 1 and paintings[0]["name"] == "村庄"

    # mock 档跑 demo
    r = client.post("/api/demo/run", json={"painting": "村庄", "prefer": "mock"})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["device"]["device_effective"] == "mock"
    assert len(run["device"]["steps"]) == 3
    assert run["device"]["total_ms"] >= 0
    run_id = run["run_id"]

    # 产物可取
    for fn in ("overlay.png", "depth.png", "depth_vis.png", "scene.ply"):
        r = client.get(f"/api/demo/artifact/{run_id}/{fn}")
        assert r.status_code == 200, fn
    assert client.get(f"/api/demo/artifact/{run_id}/scene.ply").content.startswith(b"ply")

    # 历史列表
    runs = client.get("/api/demo/runs").json()
    assert any(x["run_id"] == run_id for x in runs)


def test_api_run_auto_tier(client, demo_painting):
    """auto 档: 有 CUDA 的机器上走 GPU 真模型, 无依赖机器落 mock — 两者都必须成功。"""
    with open(demo_painting, "rb") as f:
        client.post("/api/demo/paintings", data={"name": "auto村"},
                    files={"painting": ("v.png", f, "image/png")})
    r = client.post("/api/demo/run", json={"painting": "auto村", "prefer": "auto"})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["device"]["device_effective"] in ("gpu", "cpu", "mock")
    assert len(run["device"]["steps"]) == 3


def test_api_errors(client):
    # 未注册画作
    r = client.post("/api/demo/run", json={"painting": "不存在的画", "prefer": "mock"})
    assert r.status_code == 404
    # 非法路径
    assert client.get("/api/demo/artifact/..%2Fetc/passwd/x").status_code in (400, 404)
    assert client.get("/api/demo/artifact/nope/missing.png").status_code == 404
