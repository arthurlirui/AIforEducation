"""Code sandbox stub: returns a canned result without running anything.

M4+ will wire Pyodide (browser-side) and Docker runners; the backend endpoint
exists so the frontend can call it and tests can exercise the contract.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RunResult:
    lang: str
    stdout: str
    stderr: str
    time_ms: int
    exit_code: int


def run(lang: str, code: str) -> RunResult:
    """Run a code snippet in the sandbox. Stub: echoes code without executing."""
    t0 = time.perf_counter()
    # 安全占位：不真正执行任意代码
    stdout = f"[sandbox stub] {lang} code received ({len(code)} chars); execution not enabled in this build."
    elapsed = int((time.perf_counter() - t0) * 1000)
    return RunResult(lang=lang, stdout=stdout, stderr="", time_ms=elapsed, exit_code=0)
