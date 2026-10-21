"""Studio Scheduler: 定时自动上新。

- run_once(): 手动触发一轮全量巡检（fetch → diff → compose → publish），返回报告。
- StudioScheduler: 用 APScheduler 后台定时调 run_once。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from crawler import REGISTRY, get_source
from composer import compose
from publish import publish_and_publish


@dataclass
class SourceState:
    """内容源的巡检状态（持久化在内存中，M7+ 可换 SQLite）。"""
    last_hash: str = ""
    last_checked: str = ""


@dataclass
class RunReport:
    """一轮巡检的报告。"""
    checked: int = 0
    changed: int = 0
    published: int = 0
    errors: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)


# 全局状态（内存）
_states: dict[str, SourceState] = {}


def run_once(backend_url: str = "", admin_token: str = "",
             source_ids: list[str] | None = None,
             auto_publish: bool = True) -> RunReport:
    """执行一轮巡检：遍历内容源 → diff → compose → publish。

    backend_url 为空时不推送（仅 compose）。
    source_ids 为 None 时遍历所有注册源。
    """
    report = RunReport()
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
            state = _states.get(sid, SourceState())

            if fp == state.last_hash:
                report.details.append({"source": sid, "status": "unchanged"})
                continue

            # 内容有变化 → compose + publish
            report.changed += 1
            sections = src.parse(docs)
            for section in sections:
                frames = compose(section)
                course_id = f"{sid}-{_slug(section.title)}"

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
                    report.published += 1

                report.details.append({
                    "source": sid, "status": "published",
                    "course_id": course_id, "frames": len(frames),
                })

            # 更新状态
            _states[sid] = SourceState(last_hash=fp)

        except Exception as e:
            report.errors.append(f"{sid}: {e}")

    return report


def _slug(title: str) -> str:
    """中文标题 → slug（简单转拼音首字母不可行，用 hash 短码）。"""
    import hashlib
    return hashlib.md5(title.encode()).hexdigest()[:8]


def get_state(source_id: str) -> SourceState | None:
    return _states.get(source_id)


def reset_states():
    """重置所有巡检状态（测试用）。"""
    _states.clear()


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
