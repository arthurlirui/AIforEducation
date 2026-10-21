"""Sandbox router: run code snippets."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..sandbox import runner

router = APIRouter()


class RunRequest(BaseModel):
    lang: str
    code: str


class RunResponse(BaseModel):
    lang: str
    stdout: str
    stderr: str
    time_ms: int
    exit_code: int


@router.post("/sandbox/run", response_model=RunResponse)
def run(req: RunRequest):
    r = runner.run(req.lang, req.code)
    return RunResponse(lang=r.lang, stdout=r.stdout, stderr=r.stderr,
                       time_ms=r.time_ms, exit_code=r.exit_code)
