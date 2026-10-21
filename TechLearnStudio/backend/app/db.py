"""Database setup: SQLite + SQLModel engine + session factory."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings
from . import models  # noqa: F401  ensure tables registered


def _engine():
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{settings.db_path.as_posix()}"
    return create_engine(url, echo=False, connect_args={"check_same_thread": False})


engine = _engine()


def reinit_engine() -> None:
    """重建 engine（测试时切换 DB 路径用）。"""
    global engine
    engine = _engine()
    init_db()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def list_courses(category: str | None = None, status: str | None = "published") -> list[models.Course]:
    with get_session() as s:
        stmt = select(models.Course)
        if category:
            stmt = stmt.where(models.Course.category == category)
        if status:
            stmt = stmt.where(models.Course.status == status)
        return list(s.exec(stmt).all())


def get_course(course_id: str) -> models.Course | None:
    with get_session() as s:
        return s.get(models.Course, course_id)


def upsert_course(course: models.Course) -> models.Course:
    with get_session() as s:
        existing = s.get(models.Course, course.id)
        if existing:
            for k in course.model_fields:
                setattr(existing, k, getattr(course, k))
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return existing
        s.add(course)
        s.commit()
        s.refresh(course)
        return course


def delete_course(course_id: str) -> bool:
    with get_session() as s:
        c = s.get(models.Course, course_id)
        if not c:
            return False
        s.delete(c)
        # 删除关联帧
        for f in s.exec(select(models.Frame).where(models.Frame.course_id == course_id)).all():
            s.delete(f)
        s.commit()
        return True


def set_course_status(course_id: str, status: str) -> models.Course | None:
    with get_session() as s:
        c = s.get(models.Course, course_id)
        if not c:
            return None
        c.status = status
        s.add(c)
        s.commit()
        s.refresh(c)
        return c


def list_frames(course_id: str) -> list[models.Frame]:
    with get_session() as s:
        stmt = select(models.Frame).where(models.Frame.course_id == course_id).order_by(models.Frame.index)
        return list(s.exec(stmt).all())


def get_frame(course_id: str, n: int) -> models.Frame | None:
    with get_session() as s:
        stmt = select(models.Frame).where(
            models.Frame.course_id == course_id, models.Frame.index == n
        )
        return s.exec(stmt).first()


def upsert_frames(course_id: str, frames: list[models.Frame]) -> int:
    with get_session() as s:
        # 替换式：先删旧帧再插新帧
        for f in s.exec(select(models.Frame).where(models.Frame.course_id == course_id)).all():
            s.delete(f)
        for f in frames:
            f.course_id = course_id
            s.add(f)
        s.commit()
        return len(frames)
