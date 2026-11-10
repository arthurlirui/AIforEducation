"""Course list/detail router (public read API).

B8：draft/archived 课件不对外——详情与帧接口校验 status，非 published 一律 404
（避免未发布内容被按 id 枚举读取）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..models import Course

router = APIRouter()


@router.get("/courses", response_model=list[Course])
def list_courses(category: str | None = Query(None)):
    """公开列表：只返回已发布课件。"""
    return db.list_courses(category=category, status="published")


def _get_published(course_id: str) -> Course:
    c = db.get_course(course_id)
    if not c or c.status != "published":
        raise HTTPException(404, "course not found")
    return c


@router.get("/courses/{course_id}", response_model=Course)
def get_course(course_id: str):
    return _get_published(course_id)


@router.get("/courses/{course_id}/frames")
def list_frames(course_id: str):
    _get_published(course_id)
    return db.list_frames(course_id)


@router.get("/courses/{course_id}/frames/{n}")
def get_frame(course_id: str, n: int):
    _get_published(course_id)
    f = db.get_frame(course_id, n)
    if not f:
        raise HTTPException(404, "frame not found")
    return f
