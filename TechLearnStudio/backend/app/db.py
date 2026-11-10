"""Database setup: SQLite + SQLModel engine + session factory."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, update
from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings
from . import models  # noqa: F401  ensure tables registered


def _engine():
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{settings.db_path.as_posix()}"
    eng = create_engine(url, echo=False,
                        connect_args={"check_same_thread": False, "timeout": 30})
    # B4：WAL 模式 + 30s busy timeout，缓解 FastAPI 线程池并发写时的 database is locked
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    return eng


engine = _engine()


def reinit_engine() -> None:
    """重建 engine（测试时切换 DB 路径用）。旧 engine 先释放连接，
    避免 Windows 下残留连接锁住 DB 文件。"""
    global engine
    engine.dispose()
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
    """创建或更新课程字段。

    更新时跳过主键、created_at（B5：不重置创建时间）与 version
    （version 只能经 bump_course_version 原子自增，B3）。
    """
    with get_session() as s:
        existing = s.get(models.Course, course.id)
        if existing:
            for k in type(course).model_fields:
                if k in ("id", "created_at", "version"):
                    continue
                setattr(existing, k, getattr(course, k))
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return existing
        s.add(course)
        s.commit()
        s.refresh(course)
        return course


def bump_course_version(course_id: str) -> int | None:
    """原子自增课程版本号（B3）。

    单条 UPDATE 用 SQL 表达式 version = version + 1，SQLite 对单语句加写锁，
    并发推送不会丢版本号（无 get-then-set 竞态）。返回自增后的版本号；
    课程不存在返回 None。
    """
    with get_session() as s:
        result = s.execute(
            update(models.Course)
            .where(models.Course.id == course_id)
            .values(version=models.Course.version + 1)
        )
        s.commit()
        if result.rowcount == 0:
            return None
        return s.get(models.Course, course_id).version


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
