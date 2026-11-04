"""GPU 串行任务队列（设计文档 §4.3/§6）。

- 单 worker 线程串行执行（TripoSplat/ComfyUI 均占满 GPU）
- 每个任务带进度 (0..1)、日志尾随、取消标志
- 任务函数签名: fn(task: TaskInfo, store: ProjectStore) -> dict
  可通过 task.progress 更新进度、task.log.append(...) 记日志、
  task.cancel_requested 检查取消。
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections import deque
from typing import Callable

from .models import TaskInfo, TaskStatus
from .store import ProjectStore

logger = logging.getLogger(__name__)

TaskFn = Callable[[TaskInfo, ProjectStore], dict]


class TaskQueue:
    def __init__(self) -> None:
        self._queue: deque[tuple[TaskInfo, TaskFn, ProjectStore]] = deque()
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._worker = threading.Thread(target=self._run, daemon=True, name="ps-gpu-worker")
        self._worker.start()

    # ── 生产者接口 ──

    def submit(self, kind: str, store: ProjectStore, fn: TaskFn,
               label: str = "") -> TaskInfo:
        task = TaskInfo(kind=kind, project_id=store.meta.project_id, label=label)
        with self._cv:
            self._tasks[task.task_id] = task
            self._queue.append((task, fn, store))
            self._cv.notify()
        return task

    def get(self, task_id: str) -> TaskInfo | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[TaskInfo]:
        with self._lock:
            return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return False
            if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                t.cancel_requested = True
                return True
            return False

    # ── worker ──

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                task, fn, store = self._queue.popleft()

            with self._lock:
                task.status = TaskStatus.RUNNING
            if task.cancel_requested:
                self._finish(task, TaskStatus.CANCELLED)
                continue

            try:
                result = fn(task, store)
                with self._lock:
                    cancelled = task.cancel_requested
                if cancelled:
                    self._finish(task, TaskStatus.CANCELLED)
                else:
                    task.result = result
                    self._finish(task, TaskStatus.DONE)
            except Exception as e:
                logger.exception("任务 %s 失败", task.task_id)
                task.error = f"{e}\n{traceback.format_exc(limit=3)}"
                self._finish(task, TaskStatus.FAILED)

    def _finish(self, task: TaskInfo, status: TaskStatus) -> None:
        from .models import _now
        task.status = status
        task.finished_at = _now()
        if status == TaskStatus.DONE:
            task.progress = 1.0


# ── 全局单例 ──
_queue: TaskQueue | None = None
_queue_lock = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = TaskQueue()
        return _queue
