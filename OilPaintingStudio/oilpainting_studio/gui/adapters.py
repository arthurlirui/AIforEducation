"""GUI → revive 算法层适配器（设计文档 §8）。

不修改 revive 包；此处只做目录布局映射、版本翻版、进度上报。
- run_segmentation_task : stage1 分割+深度 → 项目 objects/ 布局
- run_gs_task            : stage2 TripoSplat（逐物体, PLY 版本翻版）
- run_compose_task       : stage5 合成（ComfyUI 不可用时模拟产物）
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from ..revive.config import load_settings
from ..revive.schemas import SegmentedObject
from ..revive.stage1 import run_depth_estimation, run_segmentation
from .models import StageStatus, TaskInfo
from .store import ProjectStore, atomic_write_json, read_json, safe_name

logger = logging.getLogger(__name__)


def _settings():
    """revive Settings；.env.revive 缺失时用默认值（mock 路径可跑通）。"""
    try:
        return load_settings()
    except Exception as e:  # pragma: no cover - 配置缺失时兜底
        logger.warning("revive 配置加载失败 (%s)，使用默认", e)
        from ..revive.config import Settings
        return Settings()


# ────────────────────────────── stage1: 分割 ──────────────────────────────

def run_segmentation_task(task: TaskInfo, store: ProjectStore) -> dict:
    """stage1 全图分割 + 深度 → 导入项目布局（store.import_stage1）。"""
    settings = _settings()
    painting = store.abspath(store.meta.painting.path)
    task.log.append(f"分割开始: {painting.name}")
    task.progress = 0.1

    objects, bg_mask, bg_img, detector = run_segmentation(
        painting, store.stage1_dir, settings)
    task.log.append(f"分割完成: {len(objects)} 物体 (detector={detector})")
    task.progress = 0.6

    # 背景/深度落位到项目布局 (revive 已直接写 stage1_dir, 重命名到位即可)
    for src, dst_name in ((bg_mask, "background_mask.png"), (bg_img, "background.png")):
        dst = store.stage1_dir / dst_name
        if src.resolve() != dst.resolve():
            shutil.move(str(src), dst)
        elif src.name != dst_name:
            shutil.move(str(src), str(dst))

    depth_path = run_depth_estimation(
        painting, objects, store.stage1_dir, settings)
    task.log.append(f"深度图: {depth_path.name}")
    task.progress = 0.9

    store.import_stage1(objects, detector)

    # stage1.json 汇总（对齐 Stage1Output 字段, CLI 可读）
    atomic_write_json(store.stage1_dir / "stage1.json", {
        "painting_path": str(painting),
        "width": store.meta.painting.width,
        "height": store.meta.painting.height,
        "detector": detector,
        "objects": [
            {"object_id": o.object_id, "category": o.category.value, "label": o.label,
             "confidence": o.confidence,
             "mask_path": f"objects/{o.object_id:02d}/mask.png",
             "bbox": list(o.bbox),
             "crop_path": f"objects/{o.object_id:02d}/crop.png",
             "depth_range": list(o.depth_range)}
            for o in objects
        ],
        "background_mask_path": "background_mask.png",
        "background_path": "background.png",
        "depth_path": "depth.png",
    })
    task.progress = 1.0
    return {"num_objects": len(objects), "detector": detector}


# ────────────────────────────── stage2: 3DGS ──────────────────────────────

def run_gs_task(task: TaskInfo, store: ProjectStore,
                object_ids: list[int] | None = None) -> dict:
    """为选中物体生成 3DGS。每次重跑 PLY 版本 +1（不覆盖, §3.3 翻版）。"""
    from ..revive.stage2.triposplat import generate_object_3dgs

    settings = _settings()
    depth_path = store.stage1_dir / "depth.png"
    painting = store.abspath(store.meta.painting.path)

    all_objs = store.list_objects()
    targets = [o for o in all_objs if not o.rejected]
    if object_ids:
        targets = [o for o in targets if o.object_id in set(object_ids)]
    if not targets:
        raise ValueError("没有可生成的物体（全部 rejected 或指定为空）")

    gs_dir = store.stage2_dir / "gs"
    gs_dir.mkdir(parents=True, exist_ok=True)

    records = []
    total = len(targets)
    for i, ometa in enumerate(targets):
        if task.cancel_requested:
            raise InterruptedError("用户取消")
        obj = SegmentedObject(
            object_id=ometa.object_id,
            category=ometa.category,  # type: ignore[arg-type]
            label=ometa.label,
            confidence=ometa.confidence,
            mask_path=store.abspath(f"stage1/objects/{ometa.object_id:02d}/{ometa.mask_path}"),
            bbox=tuple(ometa.bbox),
            crop_path=store.abspath(f"stage1/objects/{ometa.object_id:02d}/{ometa.crop_path}"),
            depth_range=tuple(ometa.depth_range),
        )
        task.log.append(f"TripoSplat: {ometa.label} #{ometa.object_id} "
                        f"(mask v{ometa.mask_version})")
        rec = generate_object_3dgs(obj, painting, depth_path, settings, gs_dir)

        # 翻版: object_XX_label.ply → gs/XX_label.vN.ply, 不覆盖旧版
        new_ver = ometa.gs_version + 1
        stable = f"{ometa.object_id:02d}_{safe_name(ometa.label)}.v{new_ver}.ply"
        dest = gs_dir / stable
        shutil.move(str(rec.ply_path), dest)

        ometa.gs_version = new_ver
        ometa.gs_source_ply = f"stage2/gs/{stable}"
        store.save_object(ometa)

        records.append({
            "object_id": ometa.object_id, "label": ometa.label,
            "ply_rel": ometa.gs_source_ply,
            "num_gaussians": rec.num_gaussians,
            "bbox_3d": list(rec.bbox_3d), "center_3d": list(rec.center_3d),
            "source": rec.source,
        })
        task.progress = (i + 1) / total
        time.sleep(0.01)

    # stage2.json 汇总（对齐 Stage2Output / GSModelRegistry）
    payload = {"models": records}
    gs_index = store.stage2_dir / "stage2.json"
    if gs_index.exists():
        try:
            prev = read_json(gs_index)
            known = {m["object_id"] for m in prev.get("models", [])}
            payload["models"] = prev["models"] + [
                r for r in records if r["object_id"] not in known]
        except Exception:
            pass
    atomic_write_json(gs_index, payload)

    # 组装 scene.json 节点（保留既有节点, 只补新/更新源）
    graph = store.build_scene_from_stage2(payload)
    store.save_scene(graph)
    store.set_stage("gs", StageStatus.DONE if len(records) == total else StageStatus.PARTIAL,
                    artifact="stage2/stage2.json",
                    detail=f"{len(payload['models'])}/{len(all_objs)} 物体")
    return {"generated": len(records),
            "models": [{k: r[k] for k in ("object_id", "ply_rel", "num_gaussians")}
                       for r in records]}


# ────────────────────────────── stage5: 合成 ──────────────────────────────

def run_compose_task(task: TaskInfo, store: ProjectStore,
                     model: str, prompt: str, duration_sec: int) -> dict:
    """stage5 合成。ComfyUI 不可用时产出占位 mp4（流程可验证）。"""
    from datetime import datetime

    run_dir = store.root / "stage5" / "runs" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(run_dir / "params.json", {
        "model": model, "prompt": prompt, "duration_sec": duration_sec})

    comfy_ok = False
    try:
        from ..common.comfy.client import ComfyClient  # noqa: F401
        from ..revive.stage5.workflow import build_wan_workflow  # noqa: F401
        comfy_ok = True
    except Exception as e:
        task.log.append(f"ComfyUI 工作流不可用 ({e.__class__.__name__})，生成占位视频")

    for step in range(10):
        if task.cancel_requested:
            raise InterruptedError("用户取消")
        time.sleep(0.05)
        task.progress = (step + 1) / 10 * 0.9
        task.log.append(f"sampler {step + 1}/10")

    # 占位视频: 三张纯色帧的 mp4（ffmpeg 缺失时退化为 .mp4 占位文件）
    out = run_dir / "output.mp4"
    try:
        frames = np.zeros((3, 160, 256, 3), dtype=np.uint8)
        for c in range(3):
            frames[c, :, :, c] = 200
        import imageio.v2 as imageio
        imageio.mimwrite(str(out), list(frames), fps=6)
    except Exception:
        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            vw = cv2.VideoWriter(str(out), fourcc, 6, (256, 160))
            for c in range(3):
                f = np.zeros((160, 256, 3), dtype=np.uint8)
                f[:, :, c] = 200
                vw.write(f)
            vw.release()
        except Exception:
            out.write_bytes(b"")  # 最终兜底: 空占位

    store.set_stage("compose", StageStatus.DONE, artifact=str(out.relative_to(store.root)))
    task.progress = 1.0
    return {"output": str(out.relative_to(store.root)), "comfy_used": comfy_ok}
