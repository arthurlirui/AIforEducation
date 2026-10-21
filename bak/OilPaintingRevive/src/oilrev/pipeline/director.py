"""四模块流水线编排器。

模块 1: YOLO 多物体分割 → 多物体 mask + 背景
模块 2: TripoSplat 3DGS 生成 + 模型注册表
模块 3: 线稿引导 3DGS 重定位 + 填色补缺
模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config import Settings
from ..schemas import Stage1Output, Stage2Output, Stage3Output, Stage4Output
from ..stage1 import run_stage1
from ..stage2 import run_stage2
from ..stage3 import run_stage3
from ..stage4 import run_keyframe_generation
from ..stage5 import run_stage5
from ..utils.eval import run_evaluation
from ..utils.vram import release_gpu_memory
from .checkpoint import get_completed_stage, init_meta, mark_stage, new_project

logger = logging.getLogger(__name__)


def run_pipeline(
    settings: Settings,
    painting_path: Path,
    object_lineart_path: Path | None = None,
    keyframe_lineart_paths: list[Path] | None = None,
    project_id: str | None = None,
    resume_from_stage: int = 0,
    use_comfyui: bool = True,
) -> Path:
    """执行完整四模块流水线。返回最终视频路径。"""
    project_dir = new_project(settings.output_dir, project_id)
    meta = init_meta(project_dir, painting_path)

    completed = get_completed_stage(project_dir) if resume_from_stage else 0
    t_total = time.time()

    # 模块 1: 分割
    if completed < 1:
        t = time.time()
        stage1 = run_stage1(
            painting_path, project_dir, settings,
            object_lineart_path, keyframe_lineart_paths)
        mark_stage(project_dir, 1, {
            "sec": round(time.time() - t, 1),
            "objects": len(stage1.objects),
            "detector": stage1.detector,
        })
        release_gpu_memory()
    else:
        logger.info("跳过模块 1（已完成）")

    # 模块 2: 3DGS 生成
    if completed < 2:
        t = time.time()
        stage1 = _load_stage1(project_dir, painting_path, settings)
        stage2 = run_stage2(stage1, project_dir, settings)
        mark_stage(project_dir, 2, {
            "sec": round(time.time() - t, 1),
            "models": stage2.registry.num_models,
        })
        release_gpu_memory()
    else:
        logger.info("跳过模块 2（已完成）")

    # 模块 3: 线稿引导重定位
    if completed < 3:
        t = time.time()
        stage1 = _load_stage1(project_dir, painting_path, settings)
        stage2 = _load_stage2(project_dir)
        stage3 = run_stage3(stage1, stage2, project_dir, settings)
        mark_stage(project_dir, 3, {
            "sec": round(time.time() - t, 1),
            "transforms": len(stage3.transforms),
            "edge_iou": round(
                sum(tr.edge_iou for tr in stage3.transforms) / max(1, len(stage3.transforms)), 4),
        })
        release_gpu_memory()
    else:
        logger.info("跳过模块 3（已完成）")

    # 模块 4: 关键帧渲染 + 动画生成
    if completed < 4:
        t = time.time()
        stage3 = _load_stage3(project_dir)
        keyframes = run_keyframe_generation(stage3, project_dir, settings)
        stage4 = run_stage5(stage3, project_dir, settings, keyframes, use_comfyui)
        mark_stage(project_dir, 4, {
            "sec": round(time.time() - t, 1),
            "keyframes": len(keyframes),
            "generator": stage4.generator,
            "final": str(stage4.final_video_path),
        })
        release_gpu_memory()
    else:
        logger.info("跳过模块 4（已完成）")

    total_sec = round(time.time() - t_total, 1)
    logger.info("流水线完成: %s (总耗时 %ss)", project_dir, total_sec)
    mark_stage(project_dir, 0, {"total_sec": total_sec})

    # 返回最终视频路径
    final_video = project_dir / "stage5" / "final_mock.mp4"
    if not final_video.exists():
        stage5_dir = project_dir / "stage5"
        mp4s = list(stage5_dir.glob("*.mp4"))
        final_video = mp4s[0] if mp4s else final_video
    return final_video


def _load_stage1(project_dir: Path, painting_path: Path, settings: Settings) -> Stage1Output:
    """从检查点加载模块 1 输出。"""
    import cv2
    import numpy as np
    import re

    from ..schemas import ControlSignals, ObjectCategory, SegmentedObject

    stage1_dir = project_dir / "stage1"
    image = cv2.imread(str(painting_path))
    h, w = image.shape[:2]

    # 扫描所有物体 mask
    objects: list[SegmentedObject] = []
    mask_files = sorted(stage1_dir.glob("mask_obj*.png"))
    for mf in mask_files:
        # 从文件名解析 object_id 和 label: mask_obj00_person.png
        match = re.match(r"mask_obj(\d+)_(.+)\.png", mf.name)
        if not match:
            continue
        obj_id = int(match.group(1))
        label = match.group(2)
        mask = cv2.imread(str(mf), cv2.IMREAD_GRAYSCALE)
        if mask is None or mask.sum() == 0:
            continue
        ys, xs = np.where(mask > 0)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        crop_path = stage1_dir / f"crop_obj{obj_id:02d}_{label}.png"
        # 类别推断
        from ..stage1.segment import _label_to_category
        category = _label_to_category(label)
        near, far = settings.depth_range_for(category.value)
        objects.append(SegmentedObject(
            object_id=obj_id,
            category=category,
            label=label,
            confidence=0.8,
            mask_path=mf,
            bbox=bbox,
            crop_path=crop_path if crop_path.exists() else mf,
            depth_range=(near, far),
        ))

    bg_mask_path = stage1_dir / "mask_background.png"
    bg_path = stage1_dir / "background.png"
    depth_path = stage1_dir / "depth.png"
    edge_path = stage1_dir / "auto_canny_edge.png"
    controls = ControlSignals(
        edge_path=edge_path if edge_path.exists() else None,
    )
    return Stage1Output(
        painting_path=painting_path,
        objects=objects,
        background_mask_path=bg_mask_path,
        background_path=bg_path,
        depth_path=depth_path,
        controls=controls,
        width=w,
        height=h,
        detector="checkpoint",
    )


def _load_stage2(project_dir: Path) -> Stage2Output:
    """从检查点加载模块 2 输出。"""
    import re
    from ..schemas import GSModelRecord, GSModelRegistry

    stage2_dir = project_dir / "stage2"
    scene_ply = stage2_dir / "scene_unified.ply"
    bg_ply = stage2_dir / "background_2dgs.ply"

    # 扫描物体 PLY
    models: list[GSModelRecord] = []
    for p in sorted(stage2_dir.glob("object_*.ply")):
        match = re.match(r"object_(\d+)_(.+)\.ply", p.name)
        if not match:
            continue
        obj_id = int(match.group(1))
        label = match.group(2)
        # 计顶点数
        num = 0
        for line in p.read_text().splitlines():
            if line.startswith("element vertex"):
                num = int(line.split()[-1])
                break
        models.append(GSModelRecord(
            object_id=obj_id,
            label=label,
            ply_path=p,
            num_gaussians=num,
            bbox_3d=(0, 0, 0, 0, 0, 0),
            center_3d=(0, 0, 0),
            source="checkpoint",
        ))

    registry = GSModelRegistry(
        models=models,
        background_ply_path=bg_ply if bg_ply.exists() else None,
    )
    return Stage2Output(
        registry=registry,
        scene_ply_path=scene_ply,
    )


def _load_stage3(project_dir: Path) -> Stage3Output:
    """从检查点加载模块 3 输出。"""
    stage3_dir = project_dir / "stage3"
    return Stage3Output(
        transforms=[],
        edited_scene_ply_path=stage3_dir / "edited_scene.ply",
        inpainted_background_path=stage3_dir / "inpainted_background.png",
        keyframe_path=stage3_dir / "keyframe.png",
        keyframe_depth_path=stage3_dir / "keyframe_depth.png",
        keyframe_edge_path=stage3_dir / "keyframe_edge.png",
    )
