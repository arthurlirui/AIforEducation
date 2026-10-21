"""模块 3.2：3DGS 模型线稿引导重定位与边缘对齐。

将多个高斯泼溅模型移动到线稿指引的目标位置上，
通过迭代优化使模型渲染边缘与线稿边缘贴合。

核心算法：
1. 计算物体原始 3D 中心 → 目标 3D 中心的平移量
2. 渲染当前 3DGS 到 2D → 提取边缘 → 与线稿边缘做 IoU 优化
3. 迭代调整平移、旋转、缩放使边缘贴合
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..config import Settings
from ..schemas import GSModelRecord, RepositionTransform, SegmentedObject

logger = logging.getLogger(__name__)


def compute_target_3d_position(
    target_bbox_2d: tuple[int, int, int, int],
    depth_value: float,
    focal: float,
    img_h: int,
    img_w: int,
) -> tuple[float, float, float]:
    """将 2D 目标包围盒中心反投影到 3D 空间。"""
    x0, y0, x1, y1 = target_bbox_2d
    cx_pixel, cy_pixel = (x0 + x1) / 2, (y0 + y1) / 2
    cx_img, cy_img = img_w / 2, img_h / 2
    x_3d = (cx_pixel - cx_img) * depth_value / focal
    y_3d = (cy_pixel - cy_img) * depth_value / focal
    z_3d = depth_value
    return (float(x_3d), float(y_3d), float(z_3d))


def render_object_to_2d(
    surfels: np.ndarray,
    translation: np.ndarray,
    rotation_angle: float,
    scale: float,
    img_h: int,
    img_w: int,
    focal: float,
) -> np.ndarray:
    """渲染 3DGS 物体到 2D 二值 mask（用于边缘对齐计算）。"""
    positions = surfels[:, :3].copy()

    # 应用缩放
    positions = positions * scale

    # 应用旋转（绕 Z 轴）
    if abs(rotation_angle) > 1e-6:
        cos_r, sin_r = np.cos(rotation_angle), np.sin(rotation_angle)
        rot_matrix = np.array([
            [cos_r, -sin_r, 0],
            [sin_r, cos_r, 0],
            [0, 0, 1],
        ], dtype=np.float32)
        positions = positions @ rot_matrix.T

    # 应用平移
    positions = positions + translation

    # 投影到 2D
    valid = positions[:, 2] > 0.1
    if not valid.any():
        return np.zeros((img_h, img_w), dtype=np.uint8)

    z = positions[valid, 2]
    x = positions[valid, 0] * focal / z + img_w / 2
    y = positions[valid, 1] * focal / z + img_h / 2

    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    px = x.astype(int)
    py = y.astype(int)
    in_bounds = (px >= 0) & (px < img_w) & (py >= 0) & (py < img_h)
    mask[py[in_bounds], px[in_bounds]] = 255

    # 膨胀使轮廓连续
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=2)
    return mask


def compute_edge_iou(
    rendered_mask: np.ndarray,
    target_edge: np.ndarray,
) -> float:
    """计算渲染边缘与目标线稿边缘的 IoU。"""
    # 提取渲染 mask 的边缘
    rendered_edge = cv2.Canny(rendered_mask, 50, 150)
    # 膨胀两边缘使匹配更宽容
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    rendered_dilated = cv2.dilate(rendered_edge, kernel, iterations=1)
    target_dilated = cv2.dilate(target_edge, kernel, iterations=1)

    intersection = np.logical_and(rendered_dilated > 0, target_dilated > 0).sum()
    union = np.logical_or(rendered_dilated > 0, target_dilated > 0).sum()
    return float(intersection / (union + 1e-8))


def optimize_repositioning(
    surfels: np.ndarray,
    target_bbox_2d: tuple[int, int, int, int],
    target_edge: np.ndarray,
    original_depth: float,
    focal: float,
    img_h: int,
    img_w: int,
    settings: Settings,
) -> RepositionTransform:
    """迭代优化物体重定位，使渲染边缘与线稿边缘贴合。

    返回 RepositionTransform。
    """
    # 初始平移：物体中心 → 目标中心
    target_3d = compute_target_3d_position(
        target_bbox_2d, original_depth, focal, img_h, img_w)
    original_center = surfels[:, :3].mean(axis=0)
    translation = np.array(target_3d, dtype=np.float32) - original_center

    rotation_angle = 0.0
    scale = 1.0

    best_iou = 0.0
    best_translation = translation.copy()
    best_rotation = rotation_angle
    best_scale = scale

    for iteration in range(settings.edge_align_iterations):
        # 渲染当前状态
        rendered_mask = render_object_to_2d(
            surfels, translation, rotation_angle, scale,
            img_h, img_w, focal)
        iou = compute_edge_iou(rendered_mask, target_edge)

        if iou > best_iou:
            best_iou = iou
            best_translation = translation.copy()
            best_rotation = rotation_angle
            best_scale = scale

        # 简单梯度估计：小扰动各参数看 IoU 变化
        best_delta = None
        best_delta_iou = iou
        perturbations = [
            ("tx", np.array([settings.edge_align_lr, 0, 0], dtype=np.float32)),
            ("tx-", np.array([-settings.edge_align_lr, 0, 0], dtype=np.float32)),
            ("ty", np.array([0, settings.edge_align_lr, 0], dtype=np.float32)),
            ("ty-", np.array([0, -settings.edge_align_lr, 0], dtype=np.float32)),
            ("rot", None),  # rotation
            ("rot-", None),
            ("scale+", None),
            ("scale-", None),
        ]

        for name, delta in perturbations:
            if name in ("tx", "tx-", "ty", "ty-"):
                t = translation + delta
                r, s = rotation_angle, scale
            elif name == "rot":
                t, r, s = translation, rotation_angle + 0.05, scale
            elif name == "rot-":
                t, r, s = translation, rotation_angle - 0.05, scale
            elif name == "scale+":
                t, r, s = translation, rotation_angle, scale * 1.02
            elif name == "scale-":
                t, r, s = translation, rotation_angle, scale * 0.98
            else:
                continue

            test_mask = render_object_to_2d(
                surfels, t, r, s, img_h, img_w, focal)
            test_iou = compute_edge_iou(test_mask, target_edge)
            if test_iou > best_delta_iou:
                best_delta_iou = test_iou
                best_delta = (t, r, s)

        if best_delta is not None:
            translation, rotation_angle, scale = best_delta
        else:
            # 无改善，减小学习率
            pass

    logger.info("边缘对齐完成: IoU=%.4f (平移=%s, 旋转=%.3f, 缩放=%.3f)",
                best_iou, best_translation, best_rotation, best_scale)

    return RepositionTransform(
        object_id=-1,  # 由调用方设置
        label="",  # 由调用方设置
        translation=tuple(best_translation.astype(float)),
        rotation_angle=float(best_rotation),
        scale=float(best_scale),
        target_bbox=target_bbox_2d,
        edge_iou=best_iou,
    )


def apply_transform_to_surfels(
    surfels: np.ndarray,
    transform: RepositionTransform,
) -> np.ndarray:
    """将重定位变换应用到 surfel 点云。"""
    positions = surfels[:, :3].copy()

    # 缩放
    positions = positions * transform.scale

    # 旋转（绕 Z 轴）
    if abs(transform.rotation_angle) > 1e-6:
        cos_r, sin_r = np.cos(transform.rotation_angle), np.sin(transform.rotation_angle)
        rot_matrix = np.array([
            [cos_r, -sin_r, 0],
            [sin_r, cos_r, 0],
            [0, 0, 1],
        ], dtype=np.float32)
        positions = positions @ rot_matrix.T

    # 平移
    translation = np.array(transform.translation, dtype=np.float32)
    positions = positions + translation

    result = surfels.copy()
    result[:, :3] = positions
    return result


def load_surfels_from_ply(ply_path: Path) -> np.ndarray:
    """加载 PLY surfel 为 numpy 数组 (N, 12)。"""
    lines = ply_path.read_text().splitlines()
    idx = lines.index("end_header")
    data_lines = lines[idx + 1:]
    rows = []
    for line in data_lines:
        parts = line.strip().split()
        if len(parts) >= 12:
            row = [float(p) for p in parts[:9]] + [float(p) for p in parts[9:12]]
            rows.append(row)
    return np.array(rows, dtype=np.float32)


def save_surfels_to_ply(surfels: np.ndarray, ply_path: Path) -> None:
    """保存 surfel 数组为 PLY。"""
    from ..stage2.gs2d_init import surfels_to_ply
    surfels_to_ply(surfels, ply_path)
