"""Minimal in-process per-IP sliding-window rate limiter.

Used to protect ``POST /api/generate`` (which can consume paid API keys and
writes files to disk) without introducing any extra dependency.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Allows at most ``max_requests`` hits per ``window_seconds`` per key."""

    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = window_seconds
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for ``key`` and return whether it is within budget."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True
