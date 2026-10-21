"""模块 3 编排：线稿引导 3DGS 重定位 + 填色补缺 + 关键帧合成。

根据手绘线稿，将多个高斯泼溅模型移动到线稿位置上，
使边缘贴合，通过填色算法补上物体移动导致的缺口，
最终合成编辑后的关键帧。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..config import Settings
from ..schemas import Stage1Output, Stage2Output, Stage3Output, RepositionTransform
from .inpaint import compute_hole_mask, inpaint_holes
from .lineart_parse import (
    extract_target_regions,
    load_lineart,
    match_objects_to_targets,
)
from .reposition import (
    apply_transform_to_surfels,
    load_surfels_from_ply,
    optimize_repositioning,
    render_object_to_2d,
    save_surfels_to_ply,
)

logger = logging.getLogger(__name__)


def run_stage3(
    stage1: Stage1Output,
    stage2: Stage2Output,
    project_dir: Path,
    settings: Settings,
) -> Stage3Output:
    """执行模块 3 完整流程。"""
    stage3_dir = project_dir / "stage3"
    stage3_dir.mkdir(parents=True, exist_ok=True)

    h, w = stage1.height, stage1.width
    focal = settings.focal_length

    # 1. 解析线稿，提取目标轮廓
    lineart = load_lineart(stage1.controls.edge_path, h, w)
    target_bboxes = extract_target_regions(lineart, len(stage1.objects), settings.lineart_threshold)

    # 2. 匹配物体到目标区域
    object_bboxes = [obj.bbox for obj in stage1.objects]
    matching = match_objects_to_targets(object_bboxes, target_bboxes)

    # 3. 逐物体优化重定位
    transforms: list[RepositionTransform] = []
    edited_surfels_list: list[np.ndarray] = []
    object_masks_new: list[np.ndarray | None] = []
    object_masks_original: list[np.ndarray] = []

    # 加载背景 surfel
    bg_surfels = None
    if stage2.registry.background_ply_path and stage2.registry.background_ply_path.exists():
        bg_surfels = load_surfels_from_ply(stage2.registry.background_ply_path)

    for i, obj in enumerate(stage1.objects):
        record = stage2.registry.get_model(obj.object_id)
        if record is None:
            logger.warning("物体 %d 无 3DGS 模型记录，跳过", obj.object_id)
            continue

        surfels = load_surfels_from_ply(record.ply_path)
        original_mask = cv2.imread(str(obj.mask_path), cv2.IMREAD_GRAYSCALE)
        object_masks_original.append(original_mask)

        if i in matching and target_bboxes:
            target_bbox = target_bboxes[matching[i]]
            # 提取目标区域的线稿边缘
            if lineart.size > 0:
                target_region = np.zeros((h, w), dtype=np.uint8)
                x0, y0, x1, y1 = target_bbox
                target_region[y0:y1, x0:x1] = lineart[y0:y1, x0:x1]
                target_edge = cv2.Canny(target_region, 50, 150)
            else:
                # 无线稿时用目标 bbox 边框作为边缘
                target_edge = np.zeros((h, w), dtype=np.uint8)
                x0, y0, x1, y1 = target_bbox
                cv2.rectangle(target_edge, (x0, y0), (x1, y1), 255, 2)

            # 深度中值
            d_mid = (obj.depth_range[0] + obj.depth_range[1]) / 2

            # 优化重定位
            transform = optimize_repositioning(
                surfels, target_bbox, target_edge,
                d_mid, focal, h, w, settings,
            )
            transform.object_id = obj.object_id
            transform.label = obj.label
        else:
            # 无匹配目标，保持原位
            transform = RepositionTransform(
                object_id=obj.object_id,
                label=obj.label,
                translation=(0.0, 0.0, 0.0),
                target_bbox=obj.bbox,
                edge_iou=0.0,
            )

        transforms.append(transform)

        # 应用变换
        edited_surfels = apply_transform_to_surfels(surfels, transform)
        edited_surfels_list.append(edited_surfels)

        # 渲染新位置 mask（用于填色补缺）
        translation = np.array(transform.translation, dtype=np.float32)
        new_mask = render_object_to_2d(
            surfels, translation, transform.rotation_angle, transform.scale,
            h, w, focal)
        object_masks_new.append(new_mask)

    # 4. 保存编辑后场景
    edited_scene_path = stage3_dir / "edited_scene.ply"
    all_surfels: list[np.ndarray] = []
    if bg_surfels is not None:
        all_surfels.append(bg_surfels)
    all_surfels.extend(edited_surfels_list)

    if all_surfels:
        combined = np.concatenate(all_surfels, axis=0)
        save_surfels_to_ply(combined, edited_scene_path)
    else:
        # 空场景
        save_surfels_to_ply(np.zeros((1, 12), dtype=np.float32), edited_scene_path)

    # 5. 填色补缺：修复背景上物体移动导致的缺口
    background = cv2.imread(str(stage1.background_path))
    inpainted_bg = background.copy()
    for orig_mask, new_mask in zip(object_masks_original, object_masks_new):
        if new_mask is not None:
            hole = compute_hole_mask(orig_mask, new_mask)
            if hole.sum() > 0:
                inpainted_bg = inpaint_holes(
                    inpainted_bg, hole,
                    settings.inpaint_radius, settings.inpaint_method)

    inpainted_bg_path = stage3_dir / "inpainted_background.png"
    cv2.imwrite(str(inpainted_bg_path), inpainted_bg)

    # 6. 合成关键帧：将编辑后场景渲染为单张关键帧
    keyframe_path = stage3_dir / "keyframe.png"
    keyframe_depth_path = stage3_dir / "keyframe_depth.png"
    keyframe_edge_path = stage3_dir / "keyframe_edge.png"

    # 渲染：将编辑后 surfel 投影到 2D
    if all_surfels:
        combined_surfels = np.concatenate(all_surfels, axis=0)
    else:
        combined_surfels = np.zeros((1, 12), dtype=np.float32)

    rgb_frame, depth_frame = _render_keyframe(combined_surfels, h, w, focal)
    cv2.imwrite(str(keyframe_path), cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR))

    # 深度图
    d_min, d_max = depth_frame.min(), depth_frame.max()
    if d_max - d_min > 1e-6:
        depth_u16 = ((depth_frame - d_min) / (d_max - d_min) * 65535).astype(np.uint16)
    else:
        depth_u16 = np.zeros((h, w), dtype=np.uint16)
    cv2.imwrite(str(keyframe_depth_path), depth_u16)

    # 边缘图
    gray = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    cv2.imwrite(str(keyframe_edge_path), edges)

    output = Stage3Output(
        transforms=transforms,
        edited_scene_ply_path=edited_scene_path,
        inpainted_background_path=inpainted_bg_path,
        keyframe_path=keyframe_path,
        keyframe_depth_path=keyframe_depth_path,
        keyframe_edge_path=keyframe_edge_path,
    )
    logger.info("模块 3 完成: %d 个物体重定位, 关键帧 → %s",
                len(transforms), keyframe_path.name)
    return output


def _render_keyframe(
    surfels: np.ndarray,
    img_h: int,
    img_w: int,
    focal: float,
) -> tuple[np.ndarray, np.ndarray]:
    """将 surfel 点云投影到 2D 生成关键帧。返回 (rgb, depth)。"""
    positions = surfels[:, :3]
    colors = (surfels[:, 9:12] * 255).clip(0, 255).astype(np.uint8)

    valid = positions[:, 2] > 0.1
    positions = positions[valid]
    colors = colors[valid]

    if len(positions) == 0:
        return (np.zeros((img_h, img_w, 3), dtype=np.uint8),
                np.zeros((img_h, img_w), dtype=np.float32))

    cx, cy = img_w / 2, img_h / 2
    z = positions[:, 2]
    x = positions[:, 0] * focal / z + cx
    y = positions[:, 1] * focal / z + cy

    rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
    depth = np.zeros((img_h, img_w), dtype=np.float32)

    px = x.astype(int)
    py = y.astype(int)
    in_bounds = (px >= 0) & (px < img_w) & (py >= 0) & (py < img_h)
    px, py, z, colors = px[in_bounds], py[in_bounds], z[in_bounds], colors[in_bounds]

    # 按深度排序（远→近）
    order = np.argsort(-z)
    px, py, z, colors = px[order], py[order], z[order], colors[order]

    rgb[py, px] = colors
    depth[py, px] = z

    # 空洞填充
    if depth.max() > 0:
        depth_u16 = (depth * 1000).astype(np.uint16)
        mask = (depth == 0).astype(np.uint8) * 255
        depth_filled = cv2.inpaint(depth_u16, mask, 3, cv2.INPAINT_NS)
        depth = depth_filled.astype(np.float32) / 1000.0

    return rgb, depth
