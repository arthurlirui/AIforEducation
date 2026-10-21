"""Admin router: Studio 推送/上下架（写权限，需 admin token）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .. import db
from ..config import settings
from ..models import Course, Frame

router = APIRouter()


def _require_admin(x_admin_token: str | None = Header(None)) -> None:
    if x_admin_token != settings.admin_token:
        raise HTTPException(401, "invalid admin token")


class FramePayload(BaseModel):
    index: int
    title: str
    layout: str = "title"
    blocks_json: str = "[]"
    notes: str = ""


class CoursePayload(BaseModel):
    id: str
    title: str
    category: str = "language"
    subject: str = ""
    source_id: str = ""
    frames: list[FramePayload] = []


@router.post("/admin/courses", response_model=Course, dependencies=[Depends(_require_admin)])
def upsert_course_with_frames(payload: CoursePayload):
    """Studio 推送：创建或更新课件，含全部帧（替换式）。"""
    existing = db.get_course(payload.id)
    version = (existing.version + 1) if existing else 1
    course = Course(
        id=payload.id,
        title=payload.title,
        category=payload.category,
        subject=payload.subject,
        source_id=payload.source_id,
        version=version,
        frames_count=len(payload.frames),
        status=(existing.status if existing else "draft"),
    )
    db.upsert_course(course)
    frames = [
        Frame(
            id=f"{payload.id}#{f.index}",
            course_id=payload.id,
            index=f.index,
            title=f.title,
            layout=f.layout,
            blocks_json=f.blocks_json,
            notes=f.notes,
            version=version,
        )
        for f in payload.frames
    ]
    db.upsert_frames(payload.id, frames)
    return db.get_course(payload.id)


@router.post("/admin/courses/{course_id}/publish", dependencies=[Depends(_require_admin)])
def publish_course(course_id: str):
    c = db.set_course_status(course_id, "published")
    if not c:
        raise HTTPException(404, "course not found")
    return {"status": "published", "course_id": course_id}


@router.post("/admin/courses/{course_id}/archive", dependencies=[Depends(_require_admin)])
def archive_course(course_id: str):
    c = db.set_course_status(course_id, "archived")
    if not c:
        raise HTTPException(404, "course not found")
    return {"status": "archived", "course_id": course_id}


@router.delete("/admin/courses/{course_id}", dependencies=[Depends(_require_admin)])
def delete_course(course_id: str):
    if not db.delete_course(course_id):
        raise HTTPException(404, "course not found")
    return {"deleted": course_id}
