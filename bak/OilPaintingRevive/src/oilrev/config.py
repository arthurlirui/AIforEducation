"""配置加载：.env + settings.yaml。

四模块框架的全局配置参数。
模块 1: YOLO 分割 + 深度估计
模块 2: TripoSplat 3DGS 生成 + 模型注册表
模块 3: 线稿引导重定位 + 填色补缺
模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

_ASPECT_DIMS = {"9:16": (1080, 1920), "16:9": (1920, 1080)}


@dataclass
class Settings:
    # 画幅与视频
    aspect: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 24
    duration_sec: int = 5
    coarse_resolution: tuple[int, int] = (768, 512)

    # ── Module 1: 分割 ──
    yolo_model: str = "yolov8x-seg.pt"       # YOLO 分割模型权重
    yolo_conf_threshold: float = 0.4          # 检测置信度阈值
    yolo_iou_threshold: float = 0.5           # NMS IoU 阈值
    da_v2_model: str = "depth_anything_v2_vitlarge.pth"
    depth_max: float = 12.0                    # 深度归一化上限
    # 物体类别到深度范围的映射（近大远小）
    object_depth_ranges: dict[str, list[float]] = field(
        default_factory=lambda: {
            "person": [1.0, 3.5],
            "animal": [1.5, 4.0],
            "building": [5.0, 10.0],
            "plant": [2.0, 5.0],
            "vehicle": [2.0, 5.0],
            "object": [1.5, 5.0],
            "background": [8.0, 12.0],
        }
    )

    # ── Module 2: 3DGS 生成 ──
    triposplat_model: str = "triposplat.ckpt"
    triposplat_repo: str = ""                  # TripoSplat 仓库本地路径
    focal_length: float = 1000.0               # 焦距（像素）
    gaussians_per_object: int = 5000           # 每个前景物体的高斯点数
    gs2d_repo: str = ""                        # 2DGS 仓库本地路径

    # ── Module 3: 线稿引导重定位 ──
    edge_align_iterations: int = 50            # 边缘对齐迭代次数
    edge_align_lr: float = 0.01                # 边缘对齐学习率
    inpaint_radius: int = 5                    # 填色补缺半径（像素）
    inpaint_method: str = "telea"              # inpaint 方法: telea / ns
    lineart_threshold: float = 0.15            # 线稿二值化阈值

    # ── Module 4: 动画生成 ──
    video_generator: str = "wan2.2"            # wan2.2 / ltx2.3 / mock
    num_keyframes: int = 5                     # 关键帧数量
    ltx_model: str = "ltxv-2b-v0.9.5.safetensors"
    ltx_iclora: str = "LTX-2-19b-IC-LoRA-Union-Control.safetensors"
    ltx_steps: int = 30
    ltx_cfg: float = 1.0
    ltx_5a_resolution: tuple[int, int] = (768, 512)
    ltx_5b_denoise: float = 0.4
    depth_guide_strength: float = 1.0
    rgb_guide_strength: float = 0.6
    edge_guide_strength: float = 0.8           # ControlNet 边缘引导强度
    wan_model: str = "wan2.2_i2v_14b_720p.safetensors"
    controlnet_depth: str = "control_v11f1p_sd15_depth"
    controlnet_canny: str = "control_v11p_sd15_canny"

    # ── ComfyUI ──
    comfy_host: str = "127.0.0.1"
    comfy_port: int = 8188
    concurrency: int = 1

    # ── 评估 ──
    eval_style_threshold: float = 0.75

    # ── 路径 ──
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    workflows_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "workflows")

    @property
    def comfy_url(self) -> str:
        return f"http://{self.comfy_host}:{self.comfy_port}"

    def depth_range_for(self, category: str) -> tuple[float, float]:
        """根据物体类别返回深度范围。"""
        r = self.object_depth_ranges.get(category, [1.0, 10.0])
        return float(r[0]), float(r[1])


def load_settings(path: Path | None = None) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    sp = path or (CONFIG_DIR / "settings.yaml")
    raw: dict[str, Any] = {}
    if sp.exists():
        raw = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}

    s = Settings()
    for k, v in raw.items():
        if hasattr(s, k):
            if k in ("coarse_resolution", "ltx_5a_resolution"):
                setattr(s, k, tuple(v))
            elif k == "object_depth_ranges":
                s.object_depth_ranges = {kk: list(vv) for kk, vv in v.items()}
            elif k in ("output_dir", "workflows_dir"):
                if v:
                    setattr(s, k, Path(v))
            else:
                setattr(s, k, v)

    # 画幅
    if s.aspect in _ASPECT_DIMS:
        s.width, s.height = _ASPECT_DIMS[s.aspect]

    # env 覆盖
    s.comfy_host = os.getenv("COMFY_HOST", s.comfy_host)
    s.comfy_port = int(os.getenv("COMFY_PORT", str(s.comfy_port)))
    return s
