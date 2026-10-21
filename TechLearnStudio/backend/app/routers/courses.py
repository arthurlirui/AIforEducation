"""Course list/detail router (public read API)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..models import Course

router = APIRouter()


@router.get("/courses", response_model=list[Course])
def list_courses(category: str | None = Query(None), status: str | None = Query("published")):
    return db.list_courses(category=category, status=status)


@router.get("/courses/{course_id}", response_model=Course)
def get_course(course_id: str):
    c = db.get_course(course_id)
    if not c:
        raise HTTPException(404, "course not found")
    return c


@router.get("/courses/{course_id}/frames")
def list_frames(course_id: str):
    if not db.get_course(course_id):
        raise HTTPException(404, "course not found")
    return db.list_frames(course_id)


@router.get("/courses/{course_id}/frames/{n}")
def get_frame(course_id: str, n: int):
    f = db.get_frame(course_id, n)
    if not f:
        raise HTTPException(404, "frame not found")
    return f
