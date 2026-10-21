"""检查点管理：各阶段中间产物持久化与恢复。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..schemas import ProjectMeta

logger = logging.getLogger(__name__)

META_FILENAME = "meta.json"


def new_project(output_dir: Path, project_id: str | None = None) -> Path:
    """创建项目目录。"""
    pid = project_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    d = output_dir / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_meta(project_dir: Path) -> ProjectMeta:
    """加载项目元数据。"""
    p = project_dir / META_FILENAME
    if not p.exists():
        raise FileNotFoundError(f"项目元数据不存在: {p}")
    return ProjectMeta.model_validate_json(p.read_text(encoding="utf-8"))


def save_meta(project_dir: Path, meta: ProjectMeta) -> None:
    """保存项目元数据。"""
    p = project_dir / META_FILENAME
    p.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def init_meta(project_dir: Path, painting_path: Path) -> ProjectMeta:
    """初始化项目元数据。"""
    meta = ProjectMeta(
        project_id=project_dir.name,
        painting_path=painting_path,
        created_at=datetime.now().isoformat(),
    )
    save_meta(project_dir, meta)
    return meta


def mark_stage(project_dir: Path, stage: int, info: dict) -> ProjectMeta:
    """标记某阶段完成。"""
    try:
        meta = load_meta(project_dir)
    except FileNotFoundError:
        meta = ProjectMeta(
            project_id=project_dir.name,
            painting_path=Path(""),
            created_at=datetime.now().isoformat(),
        )
    meta.mark_stage(stage, info)
    save_meta(project_dir, meta)
    return meta


def get_completed_stage(project_dir: Path) -> int:
    """获取已完成的最高阶段号。"""
    try:
        meta = load_meta(project_dir)
        return meta.current_stage
    except FileNotFoundError:
        return 0
