"""模块 2.2：场景组装与模型注册表管理。

合并背景 2DGS 和各前景 3DGS 模型为统一场景 PLY，
并维护 GSModelRegistry 注册表集中管理所有前景物体模型。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..schemas import GSModelRecord, GSModelRegistry

logger = logging.getLogger(__name__)


def _load_ply_vertex_count(path: Path) -> int:
    """快速读取 PLY 顶点数。"""
    if not path.exists():
        return 0
    with path.open("r") as f:
        for line in f:
            if line.startswith("element vertex"):
                return int(line.split()[-1])
    return 0


def _merge_ply_files(ply_files: list[Path], output: Path) -> int:
    """合并多个 PLY 文件为一个（ascii 格式，顶点拼接）。返回总顶点数。"""
    total = 0
    bodies: list[str] = []

    for p in ply_files:
        if not p.exists():
            continue
        lines = p.read_text().splitlines()
        idx = lines.index("end_header")
        body = lines[idx + 1:]
        bodies.extend(body)
        total += len(body)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {total}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("property float nx\n")
        f.write("property float ny\n")
        f.write("property float nz\n")
        f.write("property float su\n")
        f.write("property float sv\n")
        f.write("property float opacity\n")
        f.write("property uchar red\n")
        f.write("property uchar green\n")
        f.write("property uchar blue\n")
        f.write("end_header\n")
        f.write("\n".join(bodies))
        f.write("\n")
    return total


def assemble_scene(
    background_ply: Path | None,
    object_records: list[GSModelRecord],
    output_dir: Path,
) -> tuple[GSModelRegistry, Path]:
    """组装统一场景并构建模型注册表。

    返回 (registry, scene_ply_path)。
    """
    scene_ply_path = output_dir / "scene_unified.ply"

    all_plies: list[Path] = []
    if background_ply and background_ply.exists():
        all_plies.append(background_ply)

    for record in object_records:
        if record.ply_path.exists():
            all_plies.append(record.ply_path)

    total = _merge_ply_files(all_plies, scene_ply_path)

    registry = GSModelRegistry(
        models=object_records,
        background_ply_path=background_ply,
    )

    logger.info("场景组装完成: %d 总高斯点, %d 前景模型 → %s",
                total, registry.num_models, scene_ply_path.name)
    return registry, scene_ply_path
