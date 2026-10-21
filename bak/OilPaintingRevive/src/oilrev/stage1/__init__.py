"""模块 1 编排：YOLO 多物体分割 + 深度估计 + 控制线稿解析。

将油画或水墨画的不同部分分割出来，形成多个物体的 mask，并保留背景。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings
from ..schemas import Stage1Output
from .depth import run_depth_estimation
from .parse_control import parse_controls
from .segment import run_segmentation

logger = logging.getLogger(__name__)


def run_stage1(
    painting_path: Path,
    project_dir: Path,
    settings: Settings,
    object_lineart_path: Path | None = None,
    keyframe_lineart_paths: list[Path] | None = None,
) -> Stage1Output:
    """执行模块 1 完整流程。"""
    import cv2

    stage1_dir = project_dir / "stage1"
    stage1_dir.mkdir(parents=True, exist_ok=True)

    image = cv2.imread(str(painting_path))
    h, w = image.shape[:2]

    # 1. 多物体分割
    objects, bg_mask_path, bg_path, detector = run_segmentation(
        painting_path, stage1_dir, settings,
    )

    # 2. 深度估计 + 物体级归一化
    depth_path = run_depth_estimation(painting_path, objects, stage1_dir, settings)

    # 3. 控制线稿解析
    controls = parse_controls(
        painting_path,
        object_lineart_path,
        keyframe_lineart_paths or [],
        stage1_dir,
    )

    output = Stage1Output(
        painting_path=painting_path,
        objects=objects,
        background_mask_path=bg_mask_path,
        background_path=bg_path,
        depth_path=depth_path,
        controls=controls,
        width=w,
        height=h,
        detector=detector,
    )
    logger.info("模块 1 完成: %d 个物体, 深度=%s, 检测器=%s",
                len(objects), depth_path.name, detector)
    return output
