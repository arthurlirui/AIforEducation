"""Studio Scheduler: 定时自动上新。

- run_once(): 手动触发一轮全量巡检（fetch → diff → compose → publish），返回报告。
- StudioScheduler: 用 APScheduler 后台定时调 run_once。

S9：巡检状态持久化到 scheduler_state.json（原子写），每 section 粒度记录
（发布成功一节就落盘一节）——进程重启不丢 last_hash，部分失败可断点续发。
S10：run_once 入口文件锁（O_CREAT|O_EXCL 原子创建），防 cron 与手动触发并发。
S11：course_id 基于 sid + section 序号（不再含标题 hash），标题改名走版本更新
而非新建重复课程。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from crawler import REGISTRY, get_source
from composer import compose
from publish import publish_and_publish

logger = logging.getLogger(__name__)

# 状态/锁文件放在模块目录旁（部署时与代码同生命周期）
_STATE_FILE = Path(__file__).resolve().parent / "scheduler_state.json"
_LOCK_FILE = Path(__file__).resolve().parent / "scheduler.lock"
_LOCK_STALE_S = 600  # 陈锁：超过 10 分钟视为残留（进程崩溃遗留），强制抢占


@dataclass
class SourceState:
    """内容源的巡检状态（S9：持久化到 scheduler_state.json）。

    last_hash：当前正在（或已经）处理的內容指纹。
    done_sections：该指纹下已发布成功的 section 标题（断点续发粒度）。
    """
    last_hash: str = ""
    last_checked: str = ""
    done_sections: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    """一轮巡检的报告。"""
    checked: int = 0
    changed: int = 0
    published: int = 0
    errors: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)


# 内存态缓存（首次访问时从磁盘加载）
_states: dict[str, SourceState] | None = None


def _states_map() -> dict[str, SourceState]:
    global _states
    if _states is None:
        _states = _load_states()
    return _states


def _load_states() -> dict[str, SourceState]:
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return {sid: SourceState(**d) for sid, d in raw.items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_states(states: dict[str, SourceState]) -> None:
    """原子写：先写临时文件再 os.replace，避免半截 JSON。"""
    payload = {sid: {
        "last_hash": st.last_hash,
        "last_checked": st.last_checked,
        "done_sections": st.done_sections,
    } for sid, st in states.items()}
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _STATE_FILE)


def _acquire_lock() -> bool:
    """S10：文件锁。O_CREAT|O_EXCL 原子创建；陈锁（>10 分钟）强制抢占。"""
    for _ in range(2):
        try:
            fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - _LOCK_FILE.stat().st_mtime > _LOCK_STALE_S:
                    _LOCK_FILE.unlink()
                    logger.warning("检测到陈旧 scheduler 锁（>%ss），已强制抢占", _LOCK_STALE_S)
                    continue
            except OSError:
                pass
            return False
    return False


def _release_lock() -> None:
    try:
        _LOCK_FILE.unlink()
    except OSError:
        pass


def run_once(backend_url: str = "", admin_token: str = "",
             source_ids: list[str] | None = None,
             auto_publish: bool = True) -> RunReport:
    """执行一轮巡检：遍历内容源 → diff → compose → publish。

    backend_url 为空时不推送（仅 compose），报告 status 如实记 "skipped"（S8）。
    source_ids 为 None 时遍历所有注册源。
    """
    report = RunReport()

    if not _acquire_lock():  # S10：与 cron/手动触发并发防护
        report.errors.append("run_once: 已有巡检在进行中（文件锁被持有），本轮跳过")
        return report

    try:
        states = _states_map()
        ids = source_ids or list(REGISTRY.keys())

        for sid in ids:
            report.checked += 1
            try:
                src = get_source(sid)
                if not src:
                    report.errors.append(f"{sid}: source not found")
                    continue

                docs = src.fetch()
                fp = src.fingerprint(docs)
                state = states.get(sid, SourceState())

                sections = src.parse(docs)
                # 断点续发：上一轮已发布成功的 section 不重发
                # （保留原始序号，续发时 course_id 不漂移）
                pending = [(i, s) for i, s in enumerate(sections)
                           if s.title not in state.done_sections]

                if fp == state.last_hash and not pending:
                    report.details.append({"source": sid, "status": "unchanged"})
                    continue

                if fp != state.last_hash:
                    # 内容有变化（或首跑）：重置该源的进度并先落盘新指纹，
                    # 中途崩溃后下一轮可按 pending 断点续发
                    report.changed += 1
                    state = SourceState(last_hash=fp)
                    states[sid] = state
                    _save_states(states)

                for i, section in pending:
                    frames = compose(section)
                    # S11：course_id 基于 sid + section 序号，标题改名时
                    # 命中同一 course_id → 走版本更新而非新建重复课
                    course_id = f"{sid}-s{i + 1}"

                    pushed = False
                    if backend_url and auto_publish:
                        publish_and_publish(
                            backend_url=backend_url,
                            admin_token=admin_token,
                            course_id=course_id,
                            title=section.title,
                            category="course" if "course" in sid else "language",
                            subject=src.subject,
                            frames=frames,
                            source_id=sid,
                        )
                        pushed = True
                        report.published += 1
                        # S9：发布成功一节就记一节（按 section 粒度落盘）
                        state.done_sections.append(section.title)
                        _save_states(states)

                    report.details.append({
                        "source": sid,
                        "status": "published" if pushed else "skipped",  # S8：如实
                        "course_id": course_id, "frames": len(frames),
                    })

            except Exception as e:
                report.errors.append(f"{sid}: {e}")

        return report
    finally:
        _release_lock()


def get_state(source_id: str) -> SourceState | None:
    return _states_map().get(source_id)


def reset_states():
    """重置所有巡检状态（测试用）：清内存 + 删持久化文件。"""
    global _states
    _states = {}
    try:
        _STATE_FILE.unlink()
    except OSError:
        pass


class StudioScheduler:
    """APScheduler 后台调度器。"""

    def __init__(self, backend_url: str, admin_token: str,
                 cron: str = "0 3 * * *", source_ids: list[str] | None = None):
        self.backend_url = backend_url
        self.admin_token = admin_token
        self.cron = cron
        self.source_ids = source_ids
        self._scheduler = None

    def start(self):
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        self._scheduler = BackgroundScheduler()
        trigger = CronTrigger.from_crontab(self.cron)
        self._scheduler.add_job(
            run_once,
            trigger=trigger,
            args=[self.backend_url, self.admin_token, self.source_ids],
            id="studio_auto_publish",
        )
        self._scheduler.start()

    def shutdown(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def run_now(self) -> RunReport:
        """手动触发一轮。"""
        return run_once(self.backend_url, self.admin_token, self.source_ids)
