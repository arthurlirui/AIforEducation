"""端到端冒烟测试：启动 Backend（子进程）→ Studio 推送 3 门课 → 验证前端可读。

跑法：py -m pytest tests/test_e2e.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 临时 DB
_TMP_DB = Path(__file__).resolve().parent / "_e2e.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["TLS_DB_PATH"] = str(_TMP_DB)
os.environ["TLS_ADMIN_TOKEN"] = "e2e-token"

import httpx
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(ROOT / "studio"))
sys.path.insert(0, str(BACKEND_DIR))

from composer import compose
from composer.samples import SAMPLES
from publish import publish_and_publish

BASE = "http://127.0.0.1:8799"
_proc = None


def setup_module(_):
    global _proc
    env = os.environ.copy()
    env["TLS_DB_PATH"] = str(_TMP_DB)
    env["TLS_ADMIN_TOKEN"] = "e2e-token"
    _proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8799", "--log-level", "warning"],
        cwd=str(BACKEND_DIR), env=env,
    )
    # 等 server 起来
    for _ in range(40):
        try:
            httpx.get(f"{BASE}/api/health", timeout=1).raise_for_status()
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("backend server did not start")


def teardown_module(_):
    if _proc:
        _proc.terminate()
        _proc.wait(timeout=5)
    from app import db as _db
    _db.engine.dispose()
    if _TMP_DB.exists():
        _TMP_DB.unlink()


def test_e2e_push_and_read():
    """Studio 推送 3 门课 → 前端能列课、读帧、搜索。"""
    # Studio 推送
    for cid, (title, cat, subj, section) in SAMPLES.items():
        frames = compose(section)
        result = publish_and_publish(
            backend_url=BASE, admin_token="e2e-token",
            course_id=cid, title=title, category=cat, subject=subj, frames=frames,
        )
        assert result["status"] == "published"

    # 前端：列课程
    r = httpx.get(f"{BASE}/api/courses")
    courses = r.json()
    assert len(courses) == 3
    ids = {c["id"] for c in courses}
    assert ids == {"python-asyncio", "signal-convolution", "rust-ownership"}

    # 前端：读某一门课的帧
    r = httpx.get(f"{BASE}/api/courses/signal-convolution/frames")
    frames = r.json()
    assert len(frames) >= 5  # 封面+动机+公式+代码+动画+陷阱+小结
    layouts = [f["layout"] for f in frames]
    assert "formula" in layouts
    assert "diagram" in layouts  # motionCanvas 帧

    # 验证 motionCanvas block 存在
    diag = next(f for f in frames if f["layout"] == "diagram")
    blocks = json.loads(diag["blocks_json"])
    assert any(b["type"] == "motionCanvas" for b in blocks)

    # 前端：sandbox 运行
    r = httpx.post(f"{BASE}/api/sandbox/run", json={"lang": "python", "code": "print(1)"})
    assert r.json()["exit_code"] == 0

    # 前端：搜索
    r = httpx.get(f"{BASE}/api/search?q=rust")
    assert any(res["id"] == "rust-ownership" for res in r.json()["results"])

    # 前端：health
    assert httpx.get(f"{BASE}/api/health").json()["status"] == "ok"


def test_e2e_incremental_update():
    """同一课件再次推送，版本号 +1。"""
    r = httpx.get(f"{BASE}/api/courses/python-asyncio").json()
    v1 = r["version"]

    section = SAMPLES["python-asyncio"][3]
    frames = compose(section)
    publish_and_publish(
        backend_url=BASE, admin_token="e2e-token",
        course_id="python-asyncio", title="Python 异步编程", category="language",
        subject="python", frames=frames,
    )
    r = httpx.get(f"{BASE}/api/courses/python-asyncio").json()
    assert r["version"] == v1 + 1
