"""Sandbox router: run code snippets.

边界约束（接入真实执行器前先画好边界）：
- code 长度上限 64KB（防超大 body 打内存）；
- 每 IP 每分钟 10 次的进程内滑动窗口限流（429）。

注意：当前执行为 stub（backend/app/sandbox/runner.py 只回显不执行），
响应文本已如实注明。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..sandbox import runner

router = APIRouter()

_CODE_MAX = 65536  # 64KB
_RATE_LIMIT = 10       # 每 IP 每分钟最大请求数
_RATE_WINDOW = 60.0

_req_times: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(client_ip: str) -> None:
    """进程内滑动窗口限流（单实例有效；多副本部署需换共享存储）。"""
    now = time.monotonic()
    q = _req_times[client_ip]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded: 10 requests/min per IP")
    q.append(now)


class RunRequest(BaseModel):
    lang: str
    code: str = Field(max_length=_CODE_MAX)


class RunResponse(BaseModel):
    lang: str
    stdout: str
    stderr: str
    time_ms: int
    exit_code: int


@router.post("/sandbox/run", response_model=RunResponse)
def run(req: RunRequest, request: Request):
    _check_rate_limit(request.client.host if request.client else "unknown")
    r = runner.run(req.lang, req.code)
    return RunResponse(lang=r.lang, stdout=r.stdout, stderr=r.stderr,
                       time_ms=r.time_ms, exit_code=r.exit_code)
