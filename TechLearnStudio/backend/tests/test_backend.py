"""Backend tests: 用 TestClient 覆盖 health / courses CRUD / admin 推送 / sandbox / search。"""
from __future__ import annotations

import os
from pathlib import Path

# 在导入 app 前把 DB 指向临时文件
_TMP_DB = Path(__file__).resolve().parent / "_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["TLS_DB_PATH"] = str(_TMP_DB)
os.environ["TLS_ADMIN_TOKEN"] = "test-token"

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.db import init_db

app = create_app()
client = TestClient(app)
ADMIN = {"X-Admin-Token": "test-token"}


def setup_module(_):
    init_db()


def teardown_module(_):
    # 释放 engine 连接后再删文件，避免 Windows 文件占用
    from app import db as _db
    _db.engine.dispose()
    if _TMP_DB.exists():
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
