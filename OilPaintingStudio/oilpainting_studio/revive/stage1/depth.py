"""模块 1.2：深度估计（Depth Anything V2 适配器）。

估计单目深度并按物体类别做归一化。
模型未安装时用基于亮度梯度的 mock 深度。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ...common.config import Settings
from ..schemas import SegmentedObject

logger = logging.getLogger(__name__)


def estimate_depth_da_v2(image: np.ndarray, model_path: str) -> np.ndarray:
    """用 Depth Anything V2 估计深度。返回 float32 深度图（越大越远）。"""
    import torch
    from depth_anything_v2.dpt import DepthAnythingV2

    model = DepthAnythingV2(encoder="vitl", features=256, out_channels=1)
    state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    with torch.no_grad():
        depth = model.infer_image(image)
    return depth.astype(np.float32)


def estimate_depth_mock(image: np.ndarray) -> np.ndarray:
    """Mock 深度：上方远、下方近 + 亮度调制。"""
    h, w = image.shape[:2]
    grad = np.linspace(10.0, 1.0, h, dtype=np.float32)
    depth = np.tile(grad[:, None], (1, w))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    depth += gray * 0.5
    return depth


def normalize_depth_by_objects(
    depth: np.ndarray,
    objects: list[SegmentedObject],
    settings: Settings,
) -> np.ndarray:
    """按物体类别做深度归一化，使各物体深度范围可控。"""
    normalized = depth.copy()
    for obj in objects:
        mask = cv2.imread(str(obj.mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        region = mask > 0
        if not region.any():
            continue
        near, far = settings.depth_range_for(obj.category.value)
        d_min = depth[region].min()
        d_max = depth[region].max()
        if d_max - d_min < 1e-6:
            normalized[region] = (near + far) / 2
        else:
            norm = (depth[region] - d_min) / (d_max - d_min)
            normalized[region] = near + norm * (far - near)
        obj.depth_range = (near, far)
    return normalized


def run_depth_estimation(
    image_path: Path,
    objects: list[SegmentedObject],
    output_dir: Path,
    settings: Settings,
) -> Path:
    """执行深度估计 + 物体级归一化，输出 16-bit PNG 深度图。"""
    image = cv2.imread(str(image_path))
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    try:
        depth = estimate_depth_da_v2(image_rgb, settings.da_v2_model)
        logger.info("Depth Anything V2 深度估计完成")
    except (ImportError, Exception) as e:
        logger.warning("DA-V2 不可用 (%s)，使用 mock 深度", e)
        depth = estimate_depth_mock(image_rgb)

    depth = normalize_depth_by_objects(depth, objects, settings)

    output_dir.mkdir(parents=True, exist_ok=True)
    d_min, d_max = depth.min(), depth.max()
    depth_u16 = ((depth - d_min) / (d_max - d_min + 1e-8) * 65535).astype(np.uint16)
    depth_path = output_dir / "depth.png"
    cv2.imwrite(str(depth_path), depth_u16)
    logger.info("深度图已保存: %s", depth_path)
    return depth_path


def load_depth(depth_path: Path) -> np.ndarray:
    """加载深度图，返回 float32（归一化到 [0,1]）。"""
    d = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    return d.astype(np.float32) / 65535.0
