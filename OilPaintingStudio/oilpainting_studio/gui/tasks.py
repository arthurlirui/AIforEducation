"""GPU 串行任务队列（设计文档 §4.3/§6）。

- 单 worker 线程串行执行（TripoSplat/ComfyUI 均占满 GPU）
- 每个任务带进度 (0..1)、日志尾随（上限 500 条）、取消标志
- 任务函数签名: fn(task: TaskInfo, store: ProjectStore) -> dict
  可通过 task.progress 更新进度、task.append_log(...) 记日志、
  task.cancel_requested 检查取消。
- 序列化（model_dump）必须经 queue.snapshot(): 在锁内拷贝 log, 避免
  请求线程遍历 list 时与 worker append 竞态。
- gpu_lock 可注入: 与桌面 demo 等同进程内其他 GPU 消费方共享互斥。
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
    def __init__(self, gpu_lock: threading.Lock | None = None) -> None:
        self._queue: deque[tuple[TaskInfo, TaskFn, ProjectStore]] = deque()
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        # GPU 互斥: 默认进程内私有锁; desktop 组装时传入共享锁
        self._gpu_lock = gpu_lock if gpu_lock is not None else threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True, name="ps-gpu-worker")
        self._worker.start()

    @property
    def gpu_lock(self) -> threading.Lock:
        """GPU 互斥锁（供 desktop demo run 等队列外 GPU 消费方共享）。"""
        return self._gpu_lock

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

    def snapshot(self, task: TaskInfo) -> dict:
        """锁内拷贝 task 状态为可序列化 dict。

        log 换成浅拷贝再序列化: 即使 worker 线程并发 append 原始 list,
        序列化也只遍历拷贝, 不会触发 "list changed size during iteration"。
        """
        with self._lock:
            clone = task.model_copy(update={"log": list(task.log)})
            return clone.model_dump(mode="json")

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return False
            if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                t.cancel_requested = True
                return True
            return False

    def reset(self) -> None:
        """清空任务表（测试用; 不中断正在执行的任务）。"""
        with self._lock:
            self._tasks.clear()
            self._queue.clear()

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
                with self._gpu_lock:
                    result = fn(task, store)
                with self._lock:
                    cancelled = task.cancel_requested
                    if not cancelled:
                        task.result = result
                if cancelled:
                    self._finish(task, TaskStatus.CANCELLED)
                else:
                    self._finish(task, TaskStatus.DONE)
            except Exception as e:
                logger.exception("任务 %s 失败", task.task_id)
                with self._lock:
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
