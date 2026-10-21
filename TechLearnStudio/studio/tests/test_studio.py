"""Studio tests: composer 生成帧 + 端到端推送（用 TestClient 不启真实服务）。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app

from composer import compose, Section
from composer.samples import SAMPLES, PYTHON_ASYNCIO, SIGNAL_CONVOLUTION
from publish import publish_and_publish

app = create_app()
client = TestClient(app)

# monkeypatch publish._post 到 TestClient
from publish import client as _publish_client
_orig_publish_post = _publish_client._post
def _mock_post(url, json_data, headers, timeout=30):
    from urllib.parse import urlparse
    path = urlparse(url).path
    return client.post(path, json=json_data, headers=headers)
_publish_client._post = _mock_post


def setup_module(_):
    from app.db import reinit_engine
    reinit_engine()
    _publish_client._post = _mock_post


def teardown_module(_):
    _publish_client._post = _orig_publish_post


# ---------- composer ----------
def test_compose_produces_frames():
    frames = compose(PYTHON_ASYNCIO)
    assert len(frames) >= 4
    assert frames[0]["layout"] == "title"
    # 应该有代码帧
    layouts = [f["layout"] for f in frames]
    assert "code-focus" in layouts
    # 代码帧的 block 含 runnable code
    code_frame = next(f for f in frames if f["layout"] == "code-focus")
    blocks = json.loads(code_frame["blocks_json"])
    assert any(b["type"] == "code" and b.get("runnable") for b in blocks)


def test_compose_with_formula_and_anim():
    frames = compose(SIGNAL_CONVOLUTION)
    layouts = [f["layout"] for f in frames]
    assert "formula" in layouts
    assert "diagram" in layouts
    # 动画帧含 motionCanvas block
    diag = next(f for f in frames if f["layout"] == "diagram")
    blocks = json.loads(diag["blocks_json"])
    assert any(b["type"] == "motionCanvas" for b in blocks)


# ---------- 端到端推送 ----------
def test_publish_to_backend():
    course_id = "python-asyncio"
    title, cat, subj, section = SAMPLES[course_id]
    frames = compose(section)
    publish_and_publish(
        backend_url="",  # 被 httpx.post mock 拦截
        admin_token="test-token",
        course_id=course_id, title=title, category=cat, subject=subj,
        frames=frames,
    )
    # 验证 backend 里能读到
    r = client.get("/api/courses")
    ids = [c["id"] for c in r.json()]
    assert course_id in ids

    r = client.get(f"/api/courses/{course_id}/frames")
    assert len(r.json()) >= 4


def test_publish_signal_course():
    course_id = "signal-convolution"
    title, cat, subj, section = SAMPLES[course_id]
    frames = compose(section)
    publish_and_publish(
        backend_url="", admin_token="test-token",
        course_id=course_id, title=title, category=cat, subject=subj,
        frames=frames,
    )
    r = client.get(f"/api/courses/{course_id}")
    assert r.json()["status"] == "published"
    r = client.get("/api/search?q=信号")
    assert any(res["id"] == course_id for res in r.json()["results"])
