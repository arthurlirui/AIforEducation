"""模块 2 编排：TripoSplat 3DGS 生成 + 模型注册表管理。

针对每一个分割出的前景物体生成单目三维高斯泼溅模型，
为背景生成 2DGS surfel，组装统一场景并维护模型注册表。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings
from ..schemas import Stage1Output, Stage2Output
from .assemble import assemble_scene
from .triposplat import generate_background_2dgs, generate_object_3dgs

logger = logging.getLogger(__name__)


def run_stage2(
    stage1: Stage1Output,
    project_dir: Path,
    settings: Settings,
) -> Stage2Output:
    """执行模块 2 完整流程。"""
    stage2_dir = project_dir / "stage2"
    stage2_dir.mkdir(parents=True, exist_ok=True)

    # 1. 为每个前景物体生成 3DGS 模型
    object_records = []
    for obj in stage1.objects:
        record = generate_object_3dgs(
            obj, stage1.painting_path, stage1.depth_path,
            settings, stage2_dir,
        )
        object_records.append(record)

    # 2. 为背景生成 2DGS
    bg_ply = generate_background_2dgs(
        stage1.background_path,
        stage1.background_mask_path,
        stage1.depth_path,
        settings,
        stage2_dir,
    )

    # 3. 组装统一场景 + 构建注册表
    registry, scene_ply = assemble_scene(bg_ply, object_records, stage2_dir)

    output = Stage2Output(
        registry=registry,
        scene_ply_path=scene_ply,
    )
    logger.info("模块 2 完成: %d 个前景模型 + 背景 → %s",
                registry.num_models, scene_ply.name)
    return output
