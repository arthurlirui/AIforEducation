"""模块 3.1：手绘线稿解析与目标轮廓提取。

从手绘线稿中提取各物体的目标轮廓区域，用于指引 3DGS 模型重定位。
线稿中不同连通区域对应不同物体，通过位置匹配关联到分割物体。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def load_lineart(lineart_path: Path | None, target_h: int, target_w: int) -> np.ndarray:
    """加载线稿并二值化。返回 (H, W) uint8 二值图（255=线，0=背景）。"""
    if lineart_path and lineart_path.exists():
        img = cv2.imread(str(lineart_path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            if img.shape[:2] != (target_h, target_w):
                img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            # 二值化
            _, binary = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY_INV)
            return binary

    # 无线稿时返回 None
    logger.info("无线稿，使用物体原始 mask 作为目标轮廓")
    return np.array([])


def extract_target_regions(
    lineart: np.ndarray,
    num_objects: int,
    threshold: float,
) -> list[tuple[int, int, int, int]]:
    """从线稿中提取各目标区域的包围盒。

    策略：对线稿做距离变换 → 连通域分析 → 按面积排序取前 N 个。
    无线稿时返回空列表（调用方使用物体原始位置）。
    """
    if lineart.size == 0:
        return []

    h, w = lineart.shape

    # 膨胀线稿形成封闭区域
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    filled = cv2.morphologyEx(lineart, cv2.MORPH_CLOSE, kernel, iterations=3)

    # 距离变换 + 阈值分割
    dist = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
    dist_norm = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, regions = cv2.threshold(
        dist_norm, int(threshold * 255), 255, cv2.THRESH_BINARY)

    # 连通域
    num_labels, comp_labels, stats, _ = cv2.connectedComponentsWithStats(
        regions.astype(np.uint8), connectivity=8)

    # 按面积排序，取前 num_objects 个（跳过背景标签 0）
    areas = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < (h * w * 0.005):  # 过滤太小
            continue
        areas.append((i, area))
    areas.sort(key=lambda x: -x[1])
    areas = areas[:num_objects]

    bboxes: list[tuple[int, int, int, int]] = []
    for comp_idx, _ in areas:
        x0 = int(stats[comp_idx, cv2.CC_STAT_LEFT])
        y0 = int(stats[comp_idx, cv2.CC_STAT_TOP])
        x1 = x0 + int(stats[comp_idx, cv2.CC_STAT_WIDTH])
        y1 = y0 + int(stats[comp_idx, cv2.CC_STAT_HEIGHT])
        bboxes.append((x0, y0, x1, y1))

    return bboxes


def match_objects_to_targets(
    object_bboxes: list[tuple[int, int, int, int]],
    target_bboxes: list[tuple[int, int, int, int]],
) -> dict[int, int]:
    """将物体包围盒匹配到目标包围盒。

    使用贪心最近匹配（中心距离最小）。
    返回 {object_index: target_index}。
    """
    if not target_bboxes:
        return {}

    def center(bbox):
        x0, y0, x1, y1 = bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    target_centers = [center(tb) for tb in target_bboxes]
    used_targets: set[int] = set()
    matching: dict[int, int] = {}

    for i, ob in enumerate(object_bboxes):
        oc = center(ob)
        best_idx = -1
        best_dist = float("inf")
        for j, tc in enumerate(target_centers):
            if j in used_targets:
                continue
            dist = (oc[0] - tc[0]) ** 2 + (oc[1] - tc[1]) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = j
        if best_idx >= 0:
            matching[i] = best_idx
            used_targets.add(best_idx)

    return matching
