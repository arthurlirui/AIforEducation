"""模块 1.3：控制线稿解析。

将手绘线稿加载并对齐到油画尺寸。线稿用于模块 3 的物体重定位指引。
支持多种线稿：
- 物体轮廓线稿（object_lineart）：指引各物体的目标位置
- 关键帧线稿（keyframe_linearts）：各关键帧的轮廓草图（用于模块 4）
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..schemas import ControlSignals

logger = logging.getLogger(__name__)


def _load_and_align(line_path: Path, target_h: int, target_w: int) -> Path | None:
    """加载线稿并缩放到目标尺寸。返回处理后的 PNG 路径（同名 _aligned）。"""
    if not line_path.exists():
        logger.warning("线稿不存在: %s", line_path)
        return None
    img = cv2.imread(str(line_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        logger.warning("无法读取线稿: %s", line_path)
        return None
    h, w = img.shape[:2]
    if (h, w) != (target_h, target_w):
        img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        logger.info("线稿缩放: %s (%dx%d → %dx%d)", line_path.name, w, h, target_w, target_h)
    aligned = line_path.parent / f"{line_path.stem}_aligned.png"
    cv2.imwrite(str(aligned), img)
    return aligned


def parse_controls(
    painting_path: Path,
    object_lineart_path: Path | None,
    keyframe_lineart_paths: list[Path],
    output_dir: Path,
) -> ControlSignals:
    """解析控制线稿，对齐到油画尺寸。

    Args:
        object_lineart_path: 物体轮廓线稿（指引模块 3 的物体重定位）
        keyframe_lineart_paths: 关键帧线稿列表（指引模块 4 的动画）
    """
    image = cv2.imread(str(painting_path))
    h, w = image.shape[:2]
    output_dir.mkdir(parents=True, exist_ok=True)

    # 物体轮廓线稿
    aligned_edge = None
    if object_lineart_path and object_lineart_path.exists():
        aligned_edge = _load_and_align(object_lineart_path, h, w)
    else:
        # 无手绘线稿时，自动用 Canny 生成边缘图
        logger.info("无物体线稿，自动生成 Canny 边缘")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        aligned_edge = output_dir / "auto_canny_edge.png"
        cv2.imwrite(str(aligned_edge), edges)

    # 关键帧线稿
    aligned_kfs: list[Path] = []
    for kf in keyframe_lineart_paths:
        a = _load_and_align(kf, h, w)
        if a:
            aligned_kfs.append(a)

    return ControlSignals(
        edge_path=aligned_edge,
        keyframe_paths=aligned_kfs,
    )
