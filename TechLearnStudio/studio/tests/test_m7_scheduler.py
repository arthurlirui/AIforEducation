"""M7 测试：Scheduler 定时自动上新。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

from scheduler import run_once, reset_states, get_state
from scheduler.scheduler import StudioScheduler

app = create_app()
client = TestClient(app)

# monkeypatch publish._post 到 TestClient
from publish import client as _publish_client
from urllib.parse import urlparse
_orig_publish_post = _publish_client._post
_orig_post = client.post
def _mock_post(url, json_data, headers, timeout=30):
    path = urlparse(url).path
    return _orig_post(path, json=json_data, headers=headers)
_publish_client._post = _mock_post


def setup_module(_):
    from app.db import reinit_engine
    reinit_engine()
    _publish_client._post = _mock_post


def teardown_module(_):
    _publish_client._post = _orig_publish_post
    reset_states()


def test_run_once_first_run_publishes_all():
    """首次巡检：所有源都变化 → 全部 compose + publish。"""
    reset_states()
    report = run_once(backend_url="http://mock", admin_token="test-token")
    assert report.checked == 7
    assert report.changed == 7
    assert report.published == 14  # 每源 2 节 = 14 门课
    assert len(report.errors) == 0

    # 验证 backend 里有这些课
    r = client.get("/api/courses")
    courses = r.json()
    assert len(courses) >= 14

    # 验证状态已更新
    for sid in ["python_docs", "rust_docs", "course_signal"]:
        state = get_state(sid)
        assert state is not None
        assert state.last_hash != ""


def test_run_once_second_run_no_changes():
    """第二次巡检：fingerprint 未变 → 无变化。"""
    report = run_once(backend_url="", admin_token="test-token")
    assert report.checked == 7
    assert report.changed == 0
    assert report.published == 0


def test_run_once_subset_sources():
    """只巡检部分源。"""
    reset_states()
    report = run_once(
        backend_url="http://mock", admin_token="test-token",
        source_ids=["python_docs", "rust_docs"],
    )
    assert report.checked == 2
    assert report.changed == 2
    assert report.published == 4  # 2 源 × 2 节


def test_run_once_no_publish_when_no_backend():
    """backend_url 为空时不推送，但仍 compose。"""
    reset_states()
    report = run_once(backend_url="", admin_token="", auto_publish=False)
    assert report.changed == 7
    assert report.published == 0  # 不推送


def test_scheduler_class():
    """StudioScheduler 可实例化、run_now 等效 run_once。"""
    reset_states()
    sched = StudioScheduler(backend_url="http://mock", admin_token="test-token")
    report = sched.run_now()
    assert report.checked == 7
    assert report.changed == 7


def test_scheduler_start_shutdown():
    """APScheduler 后台调度可启停。"""
    sched = StudioScheduler(backend_url="", admin_token="test-token", cron="* * * * *")
    sched.start()
    import time; time.sleep(0.5)
    sched.shutdown()
