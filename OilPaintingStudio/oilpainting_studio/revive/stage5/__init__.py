"""模块 4.2：动画视频生成。

将多张关键帧通过 ComfyUI 框架（Wan2.2 或 LTX2.3），
结合 ControlNet（深度 + 边缘）控制模块，生成高质量动画。
无 ComfyUI 时用 mock（关键帧插值合成为视频）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import cv2
import numpy as np

from ...common.comfy.client import ComfyClient
from ...common.config import Settings
from ..schemas import Stage3Output, Stage4Output, KeyframeSpec
from ...common.utils.image import frames_to_video
from .workflow import build_ltx_workflow, build_wan_workflow

logger = logging.getLogger(__name__)


async def generate_with_comfyui(
    settings: Settings,
    stage3: Stage3Output,
    keyframes: list[KeyframeSpec],
    output_dir: Path,
) -> Stage4Output:
    """通过 ComfyUI 生成动画。"""
    client = ComfyClient(settings.comfy_url, settings.concurrency)
    try:
        num_frames = max(settings.duration_sec * settings.fps, 9)

        if settings.video_generator == "wan2.2":
            # Wan2.2: 使用第一帧作为关键帧 + depth + edge ControlNet
            first_kf = keyframes[0]
            up_img = await client.upload_image(first_kf.render_path)
            up_depth = await client.upload_image(first_kf.depth_path)
            up_edge = await client.upload_image(first_kf.edge_path)

            wf = build_wan_workflow(
                settings, up_img["name"], up_depth["name"], up_edge["name"], num_frames)
            wf_path = output_dir / "workflow_wan.json"
            wf_path.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")

            clips = await client.run(wf, outputs_node="save", save_to=output_dir, timeout=1800)
            final_path = clips[0] if clips else None
            generator = "wan2.2"
        else:
            # LTX2.3: 使用关键帧序列合成为视频后上传
            rgb_video = output_dir / "keyframes_rgb.mp4"
            depth_video = output_dir / "keyframes_depth.mp4"
            _create_keyframe_video(keyframes, "render_path", rgb_video, settings.fps)
            _create_keyframe_video(keyframes, "depth_path", depth_video, settings.fps)

            up_rgb = await client.upload_video(rgb_video)
            up_depth = await client.upload_video(depth_video)

            wf = build_ltx_workflow(settings, up_rgb["name"], up_depth["name"], num_frames)
            wf_path = output_dir / "workflow_ltx.json"
            wf_path.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")

            clips = await client.run(wf, outputs_node="save", save_to=output_dir, timeout=1800)
            final_path = clips[0] if clips else None
            generator = "ltx2.3"

        await client.free_memory()

        if final_path is None:
            raise RuntimeError("ComfyUI 未返回输出视频")

        return Stage4Output(
            keyframes=keyframes,
            final_video_path=final_path,
            workflow_path=wf_path,
            generator=generator,
        )
    finally:
        await client.aclose()


def generate_mock(
    settings: Settings,
    stage3: Stage3Output,
    keyframes: list[KeyframeSpec],
    output_dir: Path,
) -> Stage4Output:
    """Mock 生成：关键帧插值合成为视频。"""
    # 如果只有一帧关键帧，复制为多帧
    num_frames = max(settings.duration_sec * settings.fps, 9)

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    if len(keyframes) == 1:
        # 单帧 → 重复 + 轻微抖动模拟动画
        base = cv2.imread(str(keyframes[0].render_path))
        for i in range(num_frames):
            t = i / max(1, num_frames - 1)
            # 轻微亮度变化模拟动画
            frame = cv2.convertScaleAbs(base, alpha=1.0 + 0.05 * np.sin(t * 2 * np.pi), beta=0)
            cv2.imwrite(str(frames_dir / f"frame_{i:04d}.png"), frame)
    else:
        # 多帧 → 线性插值
        for i in range(num_frames):
            t = i / max(1, num_frames - 1)
            kf_idx = t * (len(keyframes) - 1)
            kf_lo = int(kf_idx)
            kf_hi = min(kf_lo + 1, len(keyframes) - 1)
            alpha = kf_idx - kf_lo

            img_lo = cv2.imread(str(keyframes[kf_lo].render_path))
            img_hi = cv2.imread(str(keyframes[kf_hi].render_path))
            frame = cv2.addWeighted(img_lo, 1 - alpha, img_hi, alpha, 0)
            cv2.imwrite(str(frames_dir / f"frame_{i:04d}.png"), frame)

    final_path = output_dir / "final_mock.mp4"
    frames_to_video(frames_dir, final_path, settings.fps)
    logger.info("Mock 动画生成: %s", final_path)
    return Stage4Output(
        keyframes=keyframes,
        final_video_path=final_path,
        generator="mock",
    )


def _create_keyframe_video(
    keyframes: list[KeyframeSpec],
    attr: str,
    output_path: Path,
    fps: int,
) -> None:
    """将关键帧的某个图像属性合成为视频。"""
    paths = [getattr(kf, attr) for kf in keyframes]
    first = cv2.imread(str(paths[0]))
    h, w = first.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
    for p in paths:
        writer.write(cv2.imread(str(p)))
    writer.release()


def run_stage5(
    stage3: Stage3Output,
    project_dir: Path,
    settings: Settings,
    keyframes: list[KeyframeSpec] | None = None,
    use_comfyui: bool = True,
) -> Stage4Output:
    """执行模块 4 动画生成。"""
    from .stage4 import run_keyframe_generation

    stage5_dir = project_dir / "stage5"
    stage5_dir.mkdir(parents=True, exist_ok=True)

    # 生成关键帧（如果未提供）
    if keyframes is None:
        keyframes = run_keyframe_generation(stage3, project_dir, settings)

    if use_comfyui:
        try:
            return asyncio.run(generate_with_comfyui(settings, stage3, keyframes, stage5_dir))
        except Exception as e:
            logger.warning("ComfyUI 生成失败 (%s)，降级为 mock", e)
            return generate_mock(settings, stage3, keyframes, stage5_dir)
    return generate_mock(settings, stage3, keyframes, stage5_dir)
