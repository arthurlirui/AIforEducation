"""Stage 2.1：2DGS 场景初始化。

将单视图油画 + 单目深度反投影为 surfel 点云，生成 .ply 文件。
真实 2DGS 优化需要 hbb1/2d-gaussian-splatting 仓库；此处提供初始化 + mock 优化。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def depth_to_pointcloud(
    image: np.ndarray,
    depth: np.ndarray,
    focal: float,
) -> np.ndarray:
    """将 RGB-D 反投影为点云 (N, 6): x,y,z,r,g,b。"""
    h, w = depth.shape
    cx, cy = w / 2, h / 2
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    z = depth
    x = (xs - cx) * z / focal
    y = (ys - cy) * z / focal
    rgb = image.reshape(-1, 3).astype(np.float32)
    pts = np.stack([x.flatten(), y.flatten(), z.flatten()], axis=-1)
    return np.concatenate([pts, rgb], axis=-1)


def pointcloud_to_surfels(
    points: np.ndarray,
    image: np.ndarray,
    depth: np.ndarray,
) -> np.ndarray:
    """点云 → surfel 表示 (N, 10): x,y,z, nx,ny,nz, su,sv, opacity, sh_dc(3)。

    简化：法线初始化为相机方向(0,0,1) + 颜色梯度扰动，
    尺度初始化为像素间距对应的 3D 间距。
    """
    h, w = depth.shape
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

    n = points.shape[0]
    # 法线：基础朝相机(0,0,1)，用小随机扰动模拟笔触方向变化
    normals = np.zeros((n, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    # 轻微随机倾斜（梯度方向不可直接对齐降采样后的点，改用随机扰动）
    normals[:, 0] = np.random.randn(n).astype(np.float32) * 0.05
    normals[:, 1] = np.random.randn(n).astype(np.float32) * 0.05
    # 归一化
    norms = np.linalg.norm(normals, axis=-1, keepdims=True)
    normals = normals / (norms + 1e-8)

    # 尺度：相邻像素的 3D 距离（近似）
    scale = np.median(np.abs(np.diff(depth.flatten()))) + 0.01
    su = np.full(n, scale, dtype=np.float32)
    sv = np.full(n, scale, dtype=np.float32)

    opacity = np.ones(n, dtype=np.float32)
    sh_dc = points[:, 3:6] / 255.0  # 归一化颜色

    surfels = np.concatenate([
        points[:, :3],  # position
        normals,         # normal
        su[:, None], sv[:, None],  # scale
        opacity[:, None],  # opacity
        sh_dc,            # sh_dc
    ], axis=-1)
    return surfels


def surfels_to_ply(surfels: np.ndarray, path: Path) -> None:
    """保存 surfel 点云为简易 PLY（点云格式，供后续 2DGS 优化加载）。"""
    n = surfels.shape[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {n}\n")
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
        for s in surfels:
            r, g, b = int(s[9] * 255), int(s[10] * 255), int(s[11] * 255)
            f.write(f"{s[0]:.6f} {s[1]:.6f} {s[2]:.6f} "
                    f"{s[3]:.6f} {s[4]:.6f} {s[5]:.6f} "
                    f"{s[6]:.6f} {s[7]:.6f} {s[8]:.6f} "
                    f"{r} {g} {b}\n")
    logger.info("Surfel PLY 已保存: %s (%d 点)", path, n)
