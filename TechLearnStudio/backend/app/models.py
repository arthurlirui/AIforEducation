"""SQLModel data models: courses + frames.

注意（B2）：原 Source / VersionDelta 两个模型定义后从未被任何代码读写
（frame 级 diff 未实现），已删除以免误导维护者；实现增量版本时再按需建模。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Course(SQLModel, table=True):
    id: str = Field(primary_key=True)  # slug 如 "python-asyncio"
    title: str
    category: str = "language"  # "language" | "course"
    subject: str = ""  # "python" | "signal-system" | ...
    source_id: str = ""
    version: int = 1
    frames_count: int = 0
    status: str = "draft"  # "draft" | "published" | "archived"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Frame(SQLModel, table=True):
    id: str = Field(primary_key=True)  # "{course_id}#{n}"
    course_id: str = Field(index=True)
    index: int
    title: str
    layout: str = "title"  # title|two-col|code-focus|diagram|formula|quiz|summary
    blocks_json: str = "[]"  # 内容块 JSON（见设计文档 §6.1）
    notes: str = ""  # 演讲者备注
    version: int = 1
