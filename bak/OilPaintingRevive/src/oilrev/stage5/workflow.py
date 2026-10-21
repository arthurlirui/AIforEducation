"""模块 4.2：ComfyUI ControlNet 动画生成工作流构造。

构造 ComfyUI 工作流，将关键帧通过 ControlNet（深度 + 边缘）引导
Wan2.2 或 LTX2.3 生成高质量动画。

支持两种生成器：
- wan2.2: Wan2.2 I2V + ControlNet (depth + canny)
- ltx2.3: LTX-2.3 IC-LoRA Union Control (depth + rgb)
"""
from __future__ import annotations

import copy
import json
import logging
import random
from pathlib import Path
from typing import Any

from ..config import Settings

logger = logging.getLogger(__name__)

WAN_WORKFLOW_TEMPLATE = Path(__file__).parent / "wan_controlnet_workflow.json"
LTX_WORKFLOW_TEMPLATE = Path(__file__).parent / "ltx_iclora_workflow.json"


def load_workflow_template(generator: str, workflows_dir: Path | None = None) -> dict[str, Any]:
    """加载工作流模板。workflows_dir 下同名文件优先。"""
    if generator == "wan2.2":
        template_path = WAN_WORKFLOW_TEMPLATE
        override_name = "wan_controlnet_workflow.json"
    else:
        template_path = LTX_WORKFLOW_TEMPLATE
        override_name = "ltx_iclora_workflow.json"

    if workflows_dir is not None:
        override = workflows_dir / override_name
        if override.exists():
            return json.loads(override.read_text(encoding="utf-8"))
    return json.loads(template_path.read_text(encoding="utf-8"))


def apply_params(template: dict, params: dict[str, dict[str, Any]]) -> dict:
    """按 {node_id: {field: value}} 注入参数。field 含 '.' 时深入。"""
    wf = copy.deepcopy(template)
    for node_id, fields in params.items():
        if node_id not in wf:
            logger.warning("节点 %s 不在模板中", node_id)
            continue
        for field, value in fields.items():
            if "." in field:
                obj = wf[node_id]
                keys = field.split(".")
                for k in keys[:-1]:
                    obj = obj.setdefault(k, {})
                obj[keys[-1]] = value
            else:
                wf[node_id].setdefault("inputs", {})[field] = value
    return wf


def build_wan_workflow(
    settings: Settings,
    keyframe_image: str,
    depth_image: str,
    edge_image: str,
    num_frames: int,
    out_prefix: str = "oilrev_wan",
) -> dict[str, Any]:
    """构造 Wan2.2 I2V + ControlNet (depth + canny) 工作流。"""
    template = load_workflow_template("wan2.2", settings.workflows_dir)
    params = {
        "input_image": {"inputs.image": keyframe_image},
        "input_depth": {"inputs.image": depth_image},
        "input_edge": {"inputs.image": edge_image},
        "wan_model": {"inputs.model": settings.wan_model},
        "controlnet_depth": {"inputs.strength": settings.depth_guide_strength},
        "controlnet_canny": {"inputs.strength": settings.edge_guide_strength},
        "sampler": {
            "inputs.steps": settings.ltx_steps,
            "inputs.cfg": settings.ltx_cfg,
            "inputs.num_frames": num_frames,
        },
        "save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)
    wf["sampler"]["inputs"]["seed"] = random.randint(0, 2**63 - 1)
    return wf


def build_ltx_workflow(
    settings: Settings,
    rgb_video_name: str,
    depth_video_name: str,
    num_frames: int,
    out_prefix: str = "oilrev_ltx",
) -> dict[str, Any]:
    """构造 LTX-2.3 IC-LoRA (depth + rgb) 工作流。"""
    template = load_workflow_template("ltx2.3", settings.workflows_dir)
    w, h = settings.ltx_5a_resolution
    params = {
        "input_rgb": {"inputs.video": rgb_video_name},
        "input_depth": {"inputs.video": depth_video_name},
        "ltx_model": {"inputs.model": settings.ltx_model},
        "iclora_loader": {
            "inputs.lora_name": settings.ltx_iclora,
            "inputs.strength_model": 1.0,
        },
        "iclora_guide_depth": {"inputs.strength": settings.depth_guide_strength},
        "iclora_guide_rgb": {"inputs.strength": settings.rgb_guide_strength},
        "sampler": {
            "inputs.steps": settings.ltx_steps,
            "inputs.cfg": settings.ltx_cfg,
            "inputs.width": w,
            "inputs.height": h,
            "inputs.num_frames": num_frames,
        },
        "save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)
    wf["sampler"]["inputs"]["seed"] = random.randint(0, 2**63 - 1)
    return wf
