"""depth.py — YOLO26 单目深度估计 + 语义分割 (可选依赖).

本模块封装 YOLO26 深度估计与语义分割模型, 并提供深度归一化、
深度→半径 / 深度→密度场等纯 numpy 算法函数.

**可选依赖**: ``ultralytics`` 与 YOLO26 权重文件. 若未安装,
:class:`DepthEstimator` / :class:`SemanticSegmentor` 实例化时会抛
``ImportError``; 而深度归一化等算法函数 (无 DL 依赖) 仍可直接使用.

权重文件默认位于项目根 ``models/`` 目录:
- ``yolo26x-depth.pt`` (114MB) — 单目深度, 输出 metric depth (米)
- ``yolo26x-sem.pt``   (80MB)  — Cityscapes 19 类语义分割

Cityscapes 类别不适用于通用照片 (猫会被分为 person, 南瓜分为 car),
但足以做前景/背景分离.
"""

from __future__ import annotations

import numpy as np
import cv2
from typing import Optional

from .voronoi import compute_density, rejection_sample, lloyd_relax, prune_overlapping


# ---------------------------------------------------------------------------
# YOLO26 模型封装 (可选)
# ---------------------------------------------------------------------------

class DepthEstimator:
    """YOLO26 单目深度估计.

    输入 BGR uint8 图像, 输出 (H, W) float32 metric depth (米).
    """

    def __init__(self, model_path: str = "yolo26x-depth.pt", device: str = "0"):
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "DepthEstimator 需要 ultralytics; "
                "pip install ultralytics 或激活 polkadot-art conda 环境"
            ) from e
        self.model = YOLO(model_path)
        self.device = device

    def predict(self, image: np.ndarray) -> np.ndarray:
        H, W = image.shape[:2]
        results = self.model(image, device=self.device, verbose=False)
        depth = results[0].depth.data.cpu().numpy()
        if depth.shape != (H, W):
            depth = cv2.resize(depth, (W, H), interpolation=cv2.INTER_CUBIC)
        return depth.astype(np.float32)


class SemanticSegmentor:
    """YOLO26 语义分割 (Cityscapes 19 类)."""

    CLASS_NAMES = {
        0: "road", 1: "sidewalk", 2: "building", 3: "wall", 4: "fence",
        5: "pole", 6: "traffic light", 7: "traffic sign", 8: "vegetation",
        9: "terrain", 10: "sky", 11: "person", 12: "rider", 13: "car",
        14: "truck", 15: "bus", 16: "train", 17: "motorcycle", 18: "bicycle",
    }

    def __init__(self, model_path: str = "yolo26x-sem.pt", device: str = "0"):
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "SemanticSegmentor 需要 ultralytics; "
                "pip install ultralytics 或激活 polkadot-art conda 环境"
            ) from e
        self.model = YOLO(model_path)
        self.device = device

    def predict(self, image: np.ndarray) -> np.ndarray:
        H, W = image.shape[:2]
        results = self.model(image, device=self.device, verbose=False)
        seg = results[0].semantic_mask.data.cpu().numpy()
        if seg.shape != (H, W):
            seg = cv2.resize(seg, (W, H), interpolation=cv2.INTER_NEAREST)
        return seg.astype(np.uint8)


def has_ultralytics() -> bool:
    """返回 ultralytics 是否可导入."""
    try:
        import ultralytics  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# 深度归一化 (纯 numpy, 无 DL 依赖)
# ---------------------------------------------------------------------------

def normalize_depth(depth: np.ndarray,
                    d_min: Optional[float] = None,
                    d_max: Optional[float] = None,
                    percentile_clip: float = 2.0) -> np.ndarray:
    """归一化深度到 [0, 1], 0=最近, 1=最远.

    percentile_clip > 0 时按百分位裁剪 (去除天空等离群点).
    """
    if d_min is None:
        d_min = np.percentile(depth, percentile_clip) if percentile_clip > 0 else depth.min()
    if d_max is None:
        d_max = np.percentile(depth, 100 - percentile_clip) if percentile_clip > 0 else depth.max()
    d_max = max(d_max, d_min + 1e-6)
    d_norm = (depth - d_min) / (d_max - d_min)
    return np.clip(d_norm, 0.0, 1.0).astype(np.float32)


def normalize_depth_foreground(depth: np.ndarray,
                               fg_mask: np.ndarray,
                               percentile_clip: float = 2.0) -> np.ndarray:
    """仅用前景区域深度范围归一化.

    将前景物体内部细微深度差 (如南瓜前 vs 后) 放大到全 [0,1] 范围,
    背景像素设为 d̂=1.0 (最远 → 最小点).
    """
    fg_depths = depth[fg_mask > 0]
    if len(fg_depths) < 10:
        return normalize_depth(depth, percentile_clip=percentile_clip)
    if percentile_clip > 0:
        d_min = np.percentile(fg_depths, percentile_clip)
        d_max = np.percentile(fg_depths, 100 - percentile_clip)
    else:
        d_min = fg_depths.min()
        d_max = fg_depths.max()
    d_max = max(d_max, d_min + 1e-6)
    d_norm = (depth - d_min) / (d_max - d_min)
    d_norm = np.clip(d_norm, 0.0, 1.0).astype(np.float32)
    d_norm[fg_mask == 0] = 1.0
    return d_norm


# ---------------------------------------------------------------------------
# 深度→半径 / 深度→密度 (纯 numpy)
# ---------------------------------------------------------------------------

def depth_to_radius(d_norm: np.ndarray,
                    r_min: float = 1.0,
                    r_max: float = 25.0,
                    alpha: float = 1.5,
                    sigma: float = 0.12,
                    rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """深度 → 半径映射:

        r(x,y) = r_min + (r_max - r_min) · (1 - d̂)^α · (1 + ε),  ε ~ N(0, σ²)

    近景 (d̂→0) → 大点; 远景 (d̂→1) → 小点.
    α>1 强深度强调, σ 模拟手绘有机变化.
    """
    if rng is None:
        rng = np.random.default_rng()
    depth_weight = np.power(1.0 - d_norm, alpha)
    radii = r_min + (r_max - r_min) * depth_weight
    if sigma > 0:
        radii *= (1.0 + rng.normal(0, sigma, radii.shape))
    return np.clip(radii, 0.3, r_max * 1.1).astype(np.float32)


def depth_to_density(d_norm: np.ndarray,
                     gray: np.ndarray,
                     gamma: float = 1.2,
                     beta: float = 0.6,
                     invert_luminance: bool = True) -> np.ndarray:
    """复合密度场: ρ(x,y) = (1 - d̂)^β · γ(I_gray)."""
    lum_density = compute_density(gray, gamma=gamma, invert=invert_luminance)
    depth_density = np.power(1.0 - d_norm, beta)
    density = depth_density * lum_density
    d_max = density.max()
    if d_max > 1e-9:
        density /= d_max
    return density.astype(np.float32)


# ---------------------------------------------------------------------------
# 深度感知点绘 (纯 numpy 算法, 不依赖 DL 模型)
# ---------------------------------------------------------------------------

def depth_aware_stipple(density: np.ndarray,
                        d_norm: np.ndarray,
                        n_points: int = 20000,
                        n_iter: int = 10,
                        r_min: float = 1.0,
                        r_max: float = 25.0,
                        alpha: float = 1.5,
                        sigma: float = 0.12,
                        pos_jitter: float = 0.4,
                        overlap_gap: float = 2.0,
                        seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """深度感知点绘: 密度场驱动位置 + 深度调制半径.

    返回 (points, radii).
    """
    rng = np.random.default_rng(seed)
    pts = rejection_sample(density, n_points, rng)
    from .voronoi import has_scipy
    if has_scipy():
        pts = lloyd_relax(pts, density, n_iter=n_iter, rng=rng)

    xi = np.clip(pts[:, 0].astype(int), 0, d_norm.shape[1] - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, d_norm.shape[0] - 1)
    local_d = d_norm[yi, xi]
    depth_weight = np.power(1.0 - local_d, alpha)
    radii = r_min + (r_max - r_min) * depth_weight
    if sigma > 0:
        radii *= (1.0 + rng.normal(0, sigma, radii.shape))
    radii = np.clip(radii, 0.3, r_max * 1.1)
    if pos_jitter > 0:
        pts = pts + rng.normal(0, pos_jitter, pts.shape)
    if overlap_gap >= 0:
        pts, radii = prune_overlapping(pts, radii, gap=overlap_gap)
    return pts, radii


# ---------------------------------------------------------------------------
# 语义分析 (纯 numpy + cv2)
# ---------------------------------------------------------------------------

def analyze_semantic_regions(seg: np.ndarray) -> list[dict]:
    """识别连通语义区域, 按面积降序返回 [{class_id, class_name, area, bbox, centroid, mask}]."""
    regions = []
    unique_classes = np.unique(seg)
    for cls_id in unique_classes:
        mask = (seg == cls_id).astype(np.uint8)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n_labels):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < 100:
                continue
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            cx, cy = centroids[i]
            regions.append({
                "class_id": int(cls_id),
                "class_name": SemanticSegmentor.CLASS_NAMES.get(int(cls_id), "unknown"),
                "area": area,
                "bbox": (x, y, w, h),
                "centroid": (cx, cy),
                "mask": (labels == i).astype(np.uint8),
            })
    regions.sort(key=lambda r: r["area"], reverse=True)
    return regions


def get_foreground_mask(seg: np.ndarray, min_area_ratio: float = 0.02) -> np.ndarray:
    """从语义分割结果中提取前景掩码.

    背景类: road(0), sidewalk(1), building(2), wall(3), sky(10),
    vegetation(8), terrain(9). 其余为前景.
    """
    H, W = seg.shape
    background_classes = {0, 1, 2, 3, 8, 9, 10}
    fg = np.ones((H, W), dtype=np.uint8)
    for cls_id in background_classes:
        fg[seg == cls_id] = 0
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    min_area = int(H * W * min_area_ratio)
    fg_clean = np.zeros_like(fg)
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            fg_clean[labels == i] = 1
    return fg_clean


# ---------------------------------------------------------------------------
# 深度感知调色板 (语义感知双色: 前景/背景不同色)
# ---------------------------------------------------------------------------

DEPTH_PALETTES = {
    "black_red":     {"bg": (0, 0, 0),       "fg_dot": (0, 0, 220),   "bg_dot": (0, 180, 180)},
    "yellow_black":  {"bg": (0, 215, 255),   "fg_dot": (0, 0, 0),     "bg_dot": (0, 0, 180)},
    "white_red":     {"bg": (255, 255, 255), "fg_dot": (0, 0, 220),   "bg_dot": (200, 200, 0)},
    "magenta_cyan":  {"bg": (10, 10, 30),    "fg_dot": (220, 0, 220), "bg_dot": (220, 180, 0)},
    "red_yellow":    {"bg": (0, 0, 200),     "fg_dot": (0, 215, 255), "bg_dot": (255, 255, 255)},
}
"""深度感知版调色板: bg / fg_dot / bg_dot (BGR)."""
