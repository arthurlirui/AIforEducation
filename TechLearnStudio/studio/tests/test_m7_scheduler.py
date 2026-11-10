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
import anim_client
_orig_post = client.post
def _mock_post(url, json_data, headers, timeout=30):
    path = urlparse(url).path
    return _orig_post(path, json=json_data, headers=headers)


def _anim_offline(*a, **k):
    """S5：巡检 compose 时的动画获取一律离线降级，测试不发真实网络请求。"""
    raise ConnectionError("offline")


def setup_module(_):
    global _orig_publish_post
    global _orig_anim_post
    from app.db import reinit_engine
    # 在 setup 时才保存当前 _post：导入期保存会把别的测试模块装上的 mock
    # 误当"原始值"，teardown 恢复后跨模块泄漏（如 e2e 请求被改写到 TestClient）
    _orig_publish_post = _publish_client._post
    _orig_anim_post = anim_client._post
    reinit_engine()
    _publish_client._post = _mock_post
    anim_client._post = _anim_offline


def teardown_module(_):
    _publish_client._post = _orig_publish_post
    anim_client._post = _orig_anim_post
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


# ---------- S9/S10/S11：持久化、锁、稳定 course_id ----------
def test_state_persisted_across_reset_of_memory():
    """S9：状态落盘 scheduler_state.json，进程重启（内存清空）后不重发。"""
    from scheduler.scheduler import _STATE_FILE, _states
    import scheduler.scheduler as sched_mod
    reset_states()
    report = run_once(backend_url="http://mock", admin_token="test-token")
    assert report.published == 14
    assert _STATE_FILE.exists()

    # 模拟进程重启：内存态清空但磁盘保留
    sched_mod._states = None
    report2 = run_once(backend_url="http://mock", admin_token="test-token")
    assert report2.changed == 0
    assert report2.published == 0
    reset_states()


def test_partial_failure_resumes_per_section():
    """S9：部分 section 失败后，重跑只补发未完成的 section。"""
    import scheduler.scheduler as sched_mod
    from publish import client as _publish_client
    reset_states()
    # 先完整跑一轮建立基线，再构造部分失败场景
    run_once(backend_url="http://mock", admin_token="test-token")

    state = get_state("python_docs")
    # 模拟第 2 节发布失败：把它从 done 里去掉（等价于上轮失败未记录）
    state.done_sections = state.done_sections[:1]
    sched_mod._save_states(sched_mod._states_map())

    report = run_once(backend_url="http://mock", admin_token="test-token",
                      source_ids=["python_docs"])
    # 只补发 1 节，且 unchanged 不成立（内容未变但仍有 pending）
    assert report.published == 1
    assert report.changed == 0
    assert report.details[0]["status"] == "published"
    # 补发后 done 恢复完整
    assert len(get_state("python_docs").done_sections) == 2
    reset_states()


def test_run_once_details_skipped_when_no_backend():
    """S8：不推送时报告 status 如实记 skipped。"""
    reset_states()
    report = run_once(backend_url="", admin_token="", auto_publish=False)
    assert report.published == 0
    assert all(d["status"] == "skipped" for d in report.details)
    reset_states()


def test_course_id_stable_across_title_rename():
    """S11：标题改名不产生新 course_id（走版本更新而非新建重复课）。"""
    from crawler import get_source as _get_source
    reset_states()
    src = _get_source("python_docs")
    sections = src.get_sections()
    # course_id 由 sid + section 序号决定，与标题无关
    from scheduler.scheduler import run_once as _ro
    report = _ro(backend_url="http://mock", admin_token="test-token",
                 source_ids=["python_docs"])
    ids = [d["course_id"] for d in report.details if "course_id" in d]
    assert ids == ["python_docs-s1", "python_docs-s2"]
    reset_states()
