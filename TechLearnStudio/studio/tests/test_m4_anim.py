"""M4 测试：Motion Canvas (SVG 动画) 真实渲染。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

app = create_app()
client = TestClient(app)


def setup_module(_):
    from app.db import reinit_engine
    reinit_engine()


def teardown_module(_):
    pass


# ---------- AnimGen 单元测试 ----------
def test_convolution_template():
    from anim_gen import generate
    result = generate("convolution", {"signal": [1, 2, 3], "kernel": [1, 0, -1]})
    assert result.content_type == "image/svg+xml"
    assert "<svg" in result.content
    assert "animateTransform" in result.content  # 有动画
    assert result.duration_s == 4.0


def test_ownership_move_template():
    from anim_gen import generate
    result = generate("ownership_move", {"move_from": "s", "move_to": "t"})
    assert "<svg" in result.content
    assert "animate" in result.content
    assert "移动" in result.content


def test_ofdm_template():
    from anim_gen import generate
    result = generate("ofdm_subcarriers", {"n_subcarriers": 4})
    assert "<svg" in result.content
    assert "子载波" in result.content


def test_attention_flow_template():
    from anim_gen import generate
    result = generate("attention_flow", {"seq_len": 4})
    assert "<svg" in result.content
    assert "Attention" in result.content


def test_unknown_template_fallback():
    from anim_gen import generate
    result = generate("nonexistent", {})
    assert "<svg" in result.content
    assert "未找到" in result.content


def test_save_svg():
    from anim_gen import generate, save_svg
    result = generate("convolution", {})
    out = Path(__file__).parent / "_tmp_anim"
    path = save_svg(result, out)
    assert path.exists()
    assert path.suffix == ".svg"
    path.unlink()
    out.rmdir()


def test_scene_hash_deterministic():
    from anim_gen import scene_hash
    h1 = scene_hash("convolution", {"signal": [1, 2]})
    h2 = scene_hash("convolution", {"signal": [1, 2]})
    h3 = scene_hash("convolution", {"signal": [1, 3]})
    assert h1 == h2
    assert h1 != h3


# ---------- Backend anim API ----------
def test_anim_render_endpoint():
    r = client.post("/api/anim/render", json={"sceneRef": "convolution", "params": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["contentType"] == "image/svg+xml"
    assert "<svg" in data["content"]


def test_anim_library_endpoint():
    r = client.get("/api/anim/library")
    assert r.status_code == 200
    templates = r.json()["templates"]
    assert "convolution" in templates
    assert "ownership_move" in templates
    assert "ofdm_subcarriers" in templates
    assert "attention_flow" in templates


# ---------- Composer 集成：motionCanvas block 含真实 SVG ----------
def test_compose_produces_real_anim_svg():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from composer import compose
    from composer.samples import SIGNAL_CONVOLUTION

    frames = compose(SIGNAL_CONVOLUTION)
    diag = next(f for f in frames if f["layout"] == "diagram")
    blocks = json.loads(diag["blocks_json"])
    mc_block = next(b for b in blocks if b["type"] == "motionCanvas")
    # fallbackSvg 应该是真实 SVG（不是 "<svg/>" 占位）
    assert "<svg" in mc_block["fallbackSvg"]
    assert "animate" in mc_block["fallbackSvg"].lower()
