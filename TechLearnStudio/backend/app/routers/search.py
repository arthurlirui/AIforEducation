"""Simple in-memory search router (placeholder; M8 可换 SQLite FTS)。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import db

router = APIRouter()


@router.get("/search")
def search(q: str = Query(..., min_length=1)):
    """在已发布课件的标题里做大小写不敏感子串匹配。"""
    ql = q.lower()
    out = []
    for c in db.list_courses(status="published"):
        if ql in c.title.lower() or ql in c.id.lower() or ql in c.subject.lower():
            out.append({"id": c.id, "title": c.title, "subject": c.subject, "version": c.version})
    return {"query": q, "results": out}
