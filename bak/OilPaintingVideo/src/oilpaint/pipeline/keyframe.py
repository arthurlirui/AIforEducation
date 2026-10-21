"""关键帧油画化：为每个镜头生成油画风格首帧。"""
from __future__ import annotations

import logging
from pathlib import Path

from ..comfy.client import ComfyClient
from ..comfy.workflows import apply_params, load_template, set_seed
from ..config import Settings, StylePreset
from ..screenplay.schemas import Shot

logger = logging.getLogger(__name__)

# 模板节点 id 约定（见 img2img_oilpaint.json）
_N_CKPT = "ckpt"
_N_LORA = "lora"
_N_LATENT = "latent"
_N_POS = "prompt_pos"
_N_NEG = "prompt_neg"
_N_SAMPLER = "sampler"
_N_SAVE = "save"


def build_positive(shot: Shot, style: StylePreset) -> str:
    """拼装正向提示词：风格前缀 + 画家 + 镜头画面 + 画质词。"""
    parts = [style.positive_prefix.strip()]
    painter = shot.painter or (style.painters[0] if style.painters else "")
    if painter:
        parts.append(f"painting by {painter}")
    parts.append(shot.prompt.strip())
    parts.append("masterpiece, best quality, highly detailed, classic oil on canvas texture")
    return ", ".join(p for p in parts if p)


def build_keyframe_workflow(
    settings: Settings, shot: Shot, style: StylePreset, out_prefix: str
) -> dict:
    template = load_template("img2img_oilpaint", settings.workflows_dir)

    params = {
        _N_CKPT: {"inputs.ckpt_name": settings.sdxl_checkpoint},
        _N_LATENT: {"inputs.width": settings.width, "inputs.height": settings.height},
        _N_POS: {"inputs.text": build_positive(shot, style)},
        _N_NEG: {"inputs.negative": style.negative},
        _N_SAMPLER: {
            "inputs.steps": style.steps,
            "inputs.cfg": style.cfg,
            "inputs.sampler_name": style.sampler,
            "inputs.scheduler": style.scheduler,
        },
        _N_SAVE: {"inputs.filename_prefix": out_prefix},
    }
    # LoRA（可选）
    if settings.oilpaint_lora:
        params[_N_LORA] = {
            "inputs.lora_name": settings.oilpaint_lora,
            "inputs.strength_model": settings.oilpaint_lora_strength,
            "inputs.strength_clip": settings.oilpaint_lora_strength,
        }

    wf = apply_params(template, params)
    set_seed(wf, _N_SAMPLER)
    return wf


async def render_keyframe(
    client: ComfyClient,
    settings: Settings,
    shot: Shot,
    style: StylePreset,
    save_dir: Path,
    out_prefix: str,
) -> Path:
    """生成单镜头关键帧，返回本地 PNG 路径。"""
    wf = build_keyframe_workflow(settings, shot, style, out_prefix)
    paths = await client.run(wf, outputs_node=_N_SAVE, save_to=save_dir, timeout=600)
    if not paths:
        raise RuntimeError(f"镜头 {shot.index} 关键帧未产出")
    return paths[0]
