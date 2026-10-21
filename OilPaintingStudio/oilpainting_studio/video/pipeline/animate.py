"""图生视频调度：按 shot.i2v_model 选 LTX 或 Wan 模板，注入关键帧与运动参数。"""
from __future__ import annotations

import logging
from pathlib import Path

from ...common.comfy.client import ComfyClient
from ...common.comfy.workflows import apply_params, load_template, set_seed
from ...common.config import Settings
from .screenplay.schemas import Shot

logger = logging.getLogger(__name__)

# 镜头运动 → 生成提示词
_MOTION_TEXT = {
    "static": "subtle natural motion, gentle atmosphere",
    "pan_left": "camera slowly panning left, smooth horizontal motion",
    "pan_right": "camera slowly panning right, smooth horizontal motion",
    "zoom_in": "camera slowly zooming in, gradual forward motion",
    "zoom_out": "camera slowly zooming out, gradual backward motion",
    "tilt_up": "camera slowly tilting up, smooth vertical motion",
    "tilt_down": "camera slowly tilting down, smooth vertical motion",
}


def _motion_text(shot: Shot) -> str:
    return _MOTION_TEXT.get(shot.camera_motion, _MOTION_TEXT["static"])


def _num_frames(shot: Shot, fps: int) -> int:
    """帧数对齐到 8 的倍数（多数视频模型偏好），最少 9。"""
    n = max(9, int(round(shot.duration_sec * fps)))
    # 对齐到 8+1（如 9,17,25,...），更安全用奇数
    return n | 1


def _build_ltx(settings: Settings, shot: Shot, image_name: str, out_prefix: str) -> dict:
    template = load_template("ltx_i2v", settings.workflows_dir)
    # LTX 分辨率取画幅缩放（控制显存）
    w, h = settings.width, settings.height
    # 等比缩小到长边 ~768，避免显存爆
    scale = 768 / max(w, h)
    w = max(64, int(w * scale) // 64 * 64)
    h = max(64, int(h * scale) // 64 * 64)

    params = {
        "input_image": {"inputs.image": image_name},
        "ltx_model": {"inputs.model": settings.ltx_model},
        "ltx_pos": {"inputs.text": _motion_text(shot)},
        "ltx_sampler": {
            "inputs.steps": settings.ltx_steps,
            "inputs.cfg": settings.ltx_cfg,
            "inputs.width": w,
            "inputs.height": h,
            "inputs.num_frames": _num_frames(shot, settings.fps),
        },
        "ltx_save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)
    set_seed(wf, "ltx_sampler")
    return wf


def _build_wan(settings: Settings, shot: Shot, image_name: str, out_prefix: str) -> dict:
    template = load_template("wan_i2v", settings.workflows_dir)
    w, h = settings.width, settings.height
    # Wan 720p：长边 ~1280，缩到 16 的倍数
    scale = 1280 / max(w, h)
    w = max(16, int(w * scale) // 16 * 16)
    h = max(16, int(h * scale) // 16 * 16)

    params = {
        "input_image": {"inputs.image": image_name},
        "wan_model": {"inputs.model": settings.wan_model},
        "wan_pos": {"inputs.text": _motion_text(shot)},
        "wan_sampler": {
            "inputs.steps": settings.wan_steps,
            "inputs.cfg": settings.wan_cfg,
            "inputs.guidance_scale": settings.wan_guidance_scale,
            "inputs.width": w,
            "inputs.height": h,
            "inputs.num_frames": _num_frames(shot, settings.fps),
        },
        "wan_save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)
    set_seed(wf, "wan_sampler")
    return wf


async def render_clip(
    client: ComfyClient,
    settings: Settings,
    shot: Shot,
    keyframe_path: Path,
    save_dir: Path,
    out_prefix: str,
) -> Path:
    """对单镜头做图生视频，返回本地 mp4 路径。"""
    # 上传关键帧到 ComfyUI input
    up = await client.upload_image(keyframe_path)
    image_name = up["name"]  # ComfyUI input 目录中的文件名

    model = shot.i2v_model or settings.default_i2v_model
    if model == "wan":
        wf = _build_wan(settings, shot, image_name, out_prefix)
        save_node = "wan_save"
    else:
        wf = _build_ltx(settings, shot, image_name, out_prefix)
        save_node = "ltx_save"

    # 视频生成耗时更长
    paths = await client.run(wf, outputs_node=save_node, save_to=save_dir, timeout=1800)
    if not paths:
        raise RuntimeError(f"镜头 {shot.index} 视频未产出")
    return paths[0]
