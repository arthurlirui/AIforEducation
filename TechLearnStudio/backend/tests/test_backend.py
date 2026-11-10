"""Backend tests: 用 TestClient 覆盖 health / courses CRUD / admin 推送 / sandbox / search。

DB 与 admin token 由 conftest（根或本目录）在收集前统一定向（T1），
本模块不再在导入期改 os.environ。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.db import reinit_engine
from app.services.anim_gen import TEMPLATES, generate, save_svg, scene_hash

_TMP_DB = Path(__file__).resolve().parent / "_test.db"  # 仅独立运行时使用（见本目录 conftest）

app = create_app()
client = TestClient(app)
ADMIN = {"X-Admin-Token": "test-token"}


def setup_module(_):
    # 其它测试模块（studio/tests）可能已用统一 DB 初始化过 settings/engine，
    # setup 时重建 engine，保证拿到干净的初始状态
    reinit_engine()


def teardown_module(_):
    # 释放 engine 连接；仅当独立运行（settings 指向本目录 _test.db）时清理文件，
    # 全仓统一 DB 由根 conftest 的 sessionfinish 清理
    from app import db as _db
    from app.config import settings
    _db.engine.dispose()
    if settings.db_path == _TMP_DB and _TMP_DB.exists():
        _TMP_DB.unlink()


# ---------- health ----------
def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- admin 推送课件 ----------
def test_admin_push_course():
    frames = [
        {"index": 0, "title": "封面", "layout": "title",
         "blocks_json": json.dumps([{"type": "text", "md": "# Python 异步编程", "fragment": 0}])},
        {"index": 1, "title": "为什么需要 async", "layout": "two-col",
         "blocks_json": json.dumps([
             {"type": "text", "md": "## 问题\n阻塞 IO 浪费线程。", "fragment": 0},
             {"type": "code", "lang": "python", "src": "import asyncio\nasync def main():\n    pass", "runnable": True, "fragment": 1},
         ])},
    ]
    payload = {"id": "python-asyncio", "title": "Python 异步编程",
               "category": "language", "subject": "python", "frames": frames}
    r = client.post("/api/admin/courses", json=payload, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "python-asyncio"
    assert body["frames_count"] == 2
    assert body["status"] == "draft"
    assert body["version"] == 1


def test_admin_requires_token():
    r = client.post("/api/admin/courses", json={"id": "x", "title": "x"})
    assert r.status_code == 401


# ---------- 发布 + 前端读 ----------
def test_publish_and_read():
    client.post("/api/admin/courses/python-asyncio/publish", headers=ADMIN)
    r = client.get("/api/courses")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert "python-asyncio" in ids

    r = client.get("/api/courses/python-asyncio")
    assert r.json()["status"] == "published"

    r = client.get("/api/courses/python-asyncio/frames")
    assert len(r.json()) == 2
    assert r.json()[0]["title"] == "封面"

    r = client.get("/api/courses/python-asyncio/frames/1")
    assert r.status_code == 200
    assert r.json()["layout"] == "two-col"


def test_404_for_missing():
    assert client.get("/api/courses/nope").status_code == 404
    assert client.get("/api/courses/python-asyncio/frames/99").status_code == 404


# ---------- sandbox ----------
def test_sandbox_run():
    r = client.post("/api/sandbox/run", json={"lang": "python", "code": "print('hi')"})
    assert r.status_code == 200
    body = r.json()
    assert body["lang"] == "python"
    assert "stub" in body["stdout"].lower()
    assert body["exit_code"] == 0


# ---------- anim 端点参数校验（S6） ----------
def test_anim_render_ok():
    r = client.post("/api/anim/render", json={"sceneRef": "convolution", "params": {"signal": [1, 2, 3]}})
    assert r.status_code == 200
    assert r.json()["contentType"] == "image/svg+xml"


def test_anim_render_rejects_unknown_scene():
    r = client.post("/api/anim/render", json={"sceneRef": "evil", "params": {}})
    assert r.status_code == 422


def test_anim_render_rejects_non_numeric_signal():
    # 修复前：非数值 signal 会进模板内部抛 TypeError → 500；现在被 422 挡住
    r = client.post("/api/anim/render", json={
        "sceneRef": "convolution",
        "params": {"signal": ["</text><img src=x onerror=alert(1)>"]},
    })
    assert r.status_code == 422


def test_anim_render_rejects_out_of_range():
    r = client.post("/api/anim/render", json={"sceneRef": "attention_flow", "params": {"seq_len": 999}})
    assert r.status_code == 422


def test_anim_render_escapes_signal_text():
    # 修复前：signal 元素未转义直接进 <text>；现在（合法浮点入参 + _esc）无注入面。
    # 这里验证数值渲染为文本且 SVG 结构完整。
    r = client.post("/api/anim/render", json={"sceneRef": "convolution", "params": {"signal": [1.5, -2]}})
    assert r.status_code == 200
    assert "<svg" in r.json()["content"]
    assert "onerror" not in r.json()["content"]


# ---------- anim 内容生成（S5：随唯一实现从 studio/tests/test_m4_anim.py 迁入） ----------
def test_anim_generate_all_templates_valid_svg():
    """generate 各模板返回合法 SVG（内容生成级测试，非仅端点校验）。

    迁自 studio 侧的 4 个模板单测，模板特征文案断言一并保留。
    """
    markers = {
        "convolution": "卷积",
        "ownership_move": "移动",
        "ofdm_subcarriers": "子载波",
        "attention_flow": "Attention",
    }
    assert set(TEMPLATES) == set(markers)
    for ref, marker in markers.items():
        result = generate(ref, {})
        assert result.content_type == "image/svg+xml"
        assert result.content.lstrip().startswith("<svg")
        assert result.content.rstrip().endswith("</svg>")
        assert marker in result.content
        assert result.duration_s > 0


def test_anim_generate_convolution_animated():
    result = generate("convolution", {"signal": [1, 2, 3], "kernel": [1, 0, -1]})
    assert "animateTransform" in result.content  # 有动画
    assert result.duration_s == 4.0


def test_anim_generate_unknown_scene_fallback():
    result = generate("nonexistent", {})
    assert "<svg" in result.content
    assert "未找到" in result.content


def test_anim_save_svg_writes_file(tmp_path):
    result = generate("convolution", {})
    path = save_svg(result, tmp_path)
    assert path.exists()
    assert path.suffix == ".svg"
    assert path.read_text(encoding="utf-8").startswith("<svg")


def test_anim_scene_hash_deterministic():
    h1 = scene_hash("convolution", {"signal": [1, 2]})
    h2 = scene_hash("convolution", {"signal": [1, 2]})
    h3 = scene_hash("convolution", {"signal": [1, 3]})
    assert h1 == h2
    assert h1 != h3


def test_anim_library_endpoint():
    r = client.get("/api/anim/library")
    assert r.status_code == 200
    templates = r.json()["templates"]
    assert set(templates) >= {"convolution", "ownership_move",
                              "ofdm_subcarriers", "attention_flow"}


# ---------- search ----------
def test_search():
    r = client.get("/api/search?q=python")
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(res["id"] == "python-asyncio" for res in results)


# ---------- archive + delete ----------
def test_archive_and_delete():
    # 自建一个临时课件，避免依赖前序测试顺序
    client.post("/api/admin/courses", json={"id": "tmp-del", "title": "临时"}, headers=ADMIN)
    client.post("/api/admin/courses/tmp-del/publish", headers=ADMIN)
    client.post("/api/admin/courses/tmp-del/archive", headers=ADMIN)
    r = client.get("/api/courses")  # 默认只看 published
    assert "tmp-del" not in [c["id"] for c in r.json()]

    r = client.delete("/api/admin/courses/tmp-del", headers=ADMIN)
    assert r.status_code == 200
    assert client.get("/api/courses/tmp-del").status_code == 404


# ---------- draft/archived 不对外（B8） ----------
def test_draft_course_not_publicly_readable():
    client.post("/api/admin/courses", json={"id": "draft-x", "title": "草稿课",
                                            "frames": [{"index": 0, "title": "t"}]},
                headers=ADMIN)
    # draft：详情/帧/单帧都 404
    assert client.get("/api/courses/draft-x").status_code == 404
    assert client.get("/api/courses/draft-x/frames").status_code == 404
    assert client.get("/api/courses/draft-x/frames/0").status_code == 404
    assert "draft-x" not in [c["id"] for c in client.get("/api/courses").json()]
    # 发布后可读
    client.post("/api/admin/courses/draft-x/publish", headers=ADMIN)
    assert client.get("/api/courses/draft-x").status_code == 200
    assert client.get("/api/courses/draft-x/frames").status_code == 200
    # archived 后再次 404
    client.post("/api/admin/courses/draft-x/archive", headers=ADMIN)
    assert client.get("/api/courses/draft-x").status_code == 404
    assert client.get("/api/courses/draft-x/frames").status_code == 404
    client.delete("/api/admin/courses/draft-x", headers=ADMIN)


def test_admin_wrong_token_rejected():
    r = client.post("/api/admin/courses", json={"id": "x", "title": "x"},
                    headers={"X-Admin-Token": "wrong-token"})
    assert r.status_code == 401
