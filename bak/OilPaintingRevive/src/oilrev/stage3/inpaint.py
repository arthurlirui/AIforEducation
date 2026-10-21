"""模块 3.3：填色补缺算法。

物体移动后，原位置暴露出的背景缺口需要通过填色算法修补。
使用 OpenCV 的 inpaint 算法（Telea / Navier-Stokes）实现。

对于大面积缺口，先做颜色统计修复，再做边缘融合。
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def compute_hole_mask(
    background: np.ndarray,
    object_mask_original: np.ndarray,
    object_mask_new: np.ndarray | None = None,
) -> np.ndarray:
    """计算物体移动后暴露的缺口区域。

    缺口 = 原始物体区域 - 新物体区域（如果新位置不重叠）。
    """
    hole = object_mask_original.copy()
    if object_mask_new is not None:
        # 减去新位置重叠部分
        hole = cv2.subtract(hole, object_mask_new)
    return hole


def inpaint_holes(
    image: np.ndarray,
    hole_mask: np.ndarray,
    radius: int = 5,
    method: str = "telea",
) -> np.ndarray:
    """用 OpenCV inpaint 填色补缺。

    Args:
        image: 原始图像（BGR）
        hole_mask: 缺口掩码（255=需修补）
        radius: 修补半径
        method: "telea" 或 "ns"
    """
    if hole_mask.sum() == 0:
        return image.copy()

    inpaint_flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    result = cv2.inpaint(image, hole_mask, radius, inpaint_flag)
    logger.info("填色补缺: %d 像素 (method=%s, radius=%d)",
                int((hole_mask > 0).sum()), method, radius)
    return result


def inpaint_all_holes(
    background_path: np.ndarray,
    object_masks_original: list[np.ndarray],
    object_masks_new: list[np.ndarray | None],
    radius: int = 5,
    method: str = "telea",
) -> np.ndarray:
    """对所有物体的移动缺口进行填色补缺。

    Args:
        background_path: 背景图像（BGR）
        object_masks_original: 各物体原始掩码列表
        object_masks_new: 各物体新位置掩码列表（None 表示物体未移动）
    """
    result = background_path.copy()
    for orig_mask, new_mask in zip(object_masks_original, object_masks_new):
        hole = compute_hole_mask(orig_mask, new_mask)
        if hole.sum() > 0:
            result = inpaint_holes(result, hole, radius, method)
    return result


def seamless_blend(
    foreground: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    center: tuple[int, int],
) -> np.ndarray:
    """无缝融合：将前景物体无缝混合到背景上（用于关键帧合成）。

    使用 cv2.seamlessClone 实现边缘自然过渡。
    """
    # 确保掩码为单通道
    if len(mask.shape) == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    mask = (mask > 0).astype(np.uint8) * 255

    # seamlessClone 需要前景和掩码尺寸一致
    h, w = foreground.shape[:2]
    if mask.shape[:2] != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

    try:
        result = cv2.seamlessClone(
            foreground, background, mask, center, cv2.NORMAL_CLONE)
        return result
    except cv2.error:
        # seamlessClone 失败时直接 alpha 混合
        logger.warning("seamlessClone 失败，使用 alpha 混合")
        mask_f = mask.astype(np.float32) / 255.0
        blended = (foreground.astype(np.float32) * mask_f[:, :, None] +
                   background.astype(np.float32) * (1 - mask_f[:, :, None]))
        return blended.astype(np.uint8)
