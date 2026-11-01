"""模块 2.1：TripoSplat 单目三维高斯泼溅生成。

将分割出的每个前景物体输入到 TripoSplat 上，输出高质量的三维高斯泼溅模型。
TripoSplat 未安装时退化为从裁剪图 + 深度反投影生成简化 3D 高斯点云。

每个前景物体生成独立的单目 3DGS 模型，保存为 .ply 并注册到注册表。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..config import Settings
from ..schemas import SegmentedObject, GSModelRecord

logger = logging.getLogger(__name__)


def generate_with_triposplat(
    image_crop: np.ndarray,
    depth_crop: np.ndarray,
    focal: float,
) -> np.ndarray:
    """用 TripoSplat 生成 3D 高斯点云。

    返回 (N, 14): x,y,z, sx,sy,sz, r,g,b, opacity, rot_qw, rot_qx, rot_qy, rot_qz。
    需要 TripoSplat 包已安装。
    """
    # TripoSplat 的实际调用需要加载模型并推理
    # 此处接口保留，实际实现待集成
    raise ImportError("TripoSplat 集成为占位，使用 mock 生成")


def generate_triposplat_mock(
    image_crop: np.ndarray,
    depth_crop: np.ndarray,
    focal: float,
    target_gaussians: int,
) -> np.ndarray:
    """Mock TripoSplat：从裁剪图 + 深度反投影生成 3D 高斯点云。

    返回 (N, 9): x,y,z, sx,sy,sz, r,g,b（对角协方差简化）。
    """
    h, w = image_crop.shape[:2]
    # 计算采样步长以接近目标高斯点数
    total_pixels = h * w
    step = max(1, int(np.sqrt(total_pixels / max(1, target_gaussians))))

    ys, xs = np.meshgrid(
        np.arange(0, h, step), np.arange(0, w, step), indexing="ij")

    # 深度值
    if depth_crop.shape[:2] != (h, w):
        depth_crop = cv2.resize(depth_crop, (w, h), interpolation=cv2.INTER_LINEAR)
    d = depth_crop[ys, xs]
    # 避免除零
    d = np.maximum(d, 0.1)

    # 反投影到 3D
    cx, cy = w / 2, h / 2
    x = (xs - cx) * d / focal
    y = (ys - cy) * d / focal
    z = d

    rgb = image_crop[ys, xs].astype(np.float32) / 255.0
    n = x.shape[0] * x.shape[1]

    pts = np.stack([x.flatten(), y.flatten(), z.flatten()], axis=-1)

    # 高斯尺度：根据深度和像素间距
    pixel_spacing = d / focal
    sx = (pixel_spacing.flatten() * step * 0.5).astype(np.float32)
    sy = sx.copy()
    sz = (sx * 0.3).astype(np.float32)  # 深度方向更薄

    colors = rgb.reshape(-1, 3)
    gaussians = np.concatenate([
        pts, sx[:, None], sy[:, None], sz[:, None], colors,
    ], axis=-1)

    return gaussians


def convert_3dgs_to_2dgs(gaussians_3d: np.ndarray) -> np.ndarray:
    """3D 高斯 → 2DGS surfel 转换。

    输入 (N, 9): x,y,z, sx,sy,sz, r,g,b
    输出 (N, 12): x,y,z, nx,ny,nz, su,sv, opacity, r,g,b

    转换：取最短轴方向为法线，其余两轴为切平面尺度。
    """
    n = gaussians_3d.shape[0]
    pos = gaussians_3d[:, :3]
    scales = gaussians_3d[:, 3:6]  # (sx, sy, sz)
    colors = gaussians_3d[:, 6:9]

    # 最短轴 → 法线方向
    min_idx = np.argmin(np.abs(scales), axis=1)
    normals = np.zeros((n, 3), dtype=np.float32)
    for i in range(3):
        mask = min_idx == i
        normals[mask, i] = 1.0

    # 其余两轴 → 切平面尺度
    su = np.zeros(n, dtype=np.float32)
    sv = np.zeros(n, dtype=np.float32)
    for i in range(3):
        mask = min_idx == i
        other = [j for j in range(3) if j != i]
        su[mask] = scales[mask, other[0]]
        sv[mask] = scales[mask, other[1]]

    opacity = np.ones(n, dtype=np.float32)
    surfels = np.concatenate([
        pos, normals,
        su[:, None], sv[:, None],
        opacity[:, None], colors,
    ], axis=-1)
    return surfels


def generate_object_3dgs(
    obj: SegmentedObject,
    painting_path: Path,
    depth_path: Path,
    settings: Settings,
    output_dir: Path,
) -> GSModelRecord:
    """为单个前景物体生成 3DGS 模型并保存为 PLY。

    返回 GSModelRecord。
    """
    from .gs2d_init import surfels_to_ply

    # 加载裁剪图
    crop = cv2.imread(str(obj.crop_path))
    if crop is None:
        raise FileNotFoundError(f"无法读取裁剪图: {obj.crop_path}")
    crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

    # 加载深度图并裁剪到物体区域
    depth_u16 = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    depth = depth_u16.astype(np.float32) / 65535.0 * settings.depth_max
    x0, y0, x1, y1 = obj.bbox
    depth_crop = depth[y0:y1, x0:x1]

    # 生成 3D 高斯
    try:
        gaussians_3d = generate_with_triposplat(
            crop_rgb, depth_crop, settings.focal_length)
    except (ImportError, Exception) as e:
        logger.warning("TripoSplat 不可用 (%s)，使用 mock 生成: %s", e, obj.label)
        gaussians_3d = generate_triposplat_mock(
            crop_rgb, depth_crop, settings.focal_length,
            settings.gaussians_per_object)

    # 转换为 2DGS surfel
    surfels = convert_3dgs_to_2dgs(gaussians_3d)

    # 计算 3D 包围盒和中心
    positions = surfels[:, :3]
    bbox_3d = (
        float(positions[:, 0].min()), float(positions[:, 1].min()), float(positions[:, 2].min()),
        float(positions[:, 0].max()), float(positions[:, 1].max()), float(positions[:, 2].max()),
    )
    center = (
        float(positions[:, 0].mean()), float(positions[:, 1].mean()), float(positions[:, 2].mean()),
    )

    # 保存 PLY
    ply_path = output_dir / f"object_{obj.object_id:02d}_{obj.label}.ply"
    surfels_to_ply(surfels, ply_path)

    record = GSModelRecord(
        object_id=obj.object_id,
        label=obj.label,
        ply_path=ply_path,
        num_gaussians=len(surfels),
        bbox_3d=bbox_3d,
        center_3d=center,
        source="triposplat" if False else "mock",  # 实际使用时根据是否 fallback 设置
    )
    logger.info("物体 %s (id=%d): %d 高斯点 → %s",
                obj.label, obj.object_id, len(surfels), ply_path.name)
    return record


def generate_background_2dgs(
    background_path: Path,
    background_mask_path: Path,
    depth_path: Path,
    settings: Settings,
    output_dir: Path,
) -> Path:
    """为背景生成 2DGS surfel 点云。

    背景使用全图深度反投影（前景区域已被 inpaint 填充）。
    """
    from .gs2d_init import depth_to_pointcloud, pointcloud_to_surfels, surfels_to_ply

    image = cv2.imread(str(background_path))
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    depth_u16 = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    depth = depth_u16.astype(np.float32) / 65535.0 * settings.depth_max

    # 降采样（控制点数，背景 ~50k 点）
    h, w = depth.shape
    step = max(1, int(np.sqrt(h * w / 50000)))

    # 采样
    ys, xs = np.meshgrid(
        np.arange(0, h, step), np.arange(0, w, step), indexing="ij")
    sampled_depth = np.zeros_like(depth)
    sampled_depth[ys, xs] = depth[ys, xs]
    sampled_image = np.zeros_like(image_rgb)
    sampled_image[ys, xs] = image_rgb[ys, xs]

    points = depth_to_pointcloud(sampled_image, sampled_depth, settings.focal_length)
    valid = points[:, 2] > 0.1
    points = points[valid]

    surfels = pointcloud_to_surfels(points, sampled_image, sampled_depth)
    bg_ply = output_dir / "background_2dgs.ply"
    surfels_to_ply(surfels, bg_ply)
    logger.info("背景 2DGS: %d surfels → %s", len(surfels), bg_ply.name)
    return bg_ply
