"""配置加载：.env（密钥/端点）+ settings.yaml（创作参数）+ styles.yaml（风格预设）。

优先级：CLI 参数 > 环境变量 > settings.yaml > 代码默认值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # OilPaintingVideo/
CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass
class StylePreset:
    key: str
    name: str
    painters: list[str]
    positive_prefix: str
    negative: str
    sampler: str
    scheduler: str
    cfg: float
    steps: int
    bgm_mood: str


@dataclass
class Settings:
    # 画幅
    aspect: str = "9:16"
    width: int = 1080
    height: int = 1920

    # 图生视频模型
    default_i2v_model: str = "ltx"

    # 视频
    target_duration_sec: int = 30
    fps: int = 24
    shot_duration_sec: int = 3
    concurrency: int = 2

    # 风格
    default_style: str = "impressionism"
    styles: dict[str, StylePreset] = field(default_factory=dict)

    # ComfyUI 模型名
    sdxl_checkpoint: str = "sd_xl_base_1.0.safetensors"
    oilpaint_lora: str = ""
    oilpaint_lora_strength: float = 0.8
    ltx_model: str = "ltx-video-2b-v0.9.5.safetensors"
    ltx_steps: int = 30
    ltx_cfg: float = 1.0
    wan_model: str = "wan2.2_i2v_720p_bf16.safetensors"
    wan_steps: int = 30
    wan_cfg: float = 6.0
    wan_guidance_scale: float = 5.0

    # 路径
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    workflows_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "workflows")
    assets_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "assets")
    ffmpeg_path: str = ""

    # 剪辑
    transition: str = "xfade"
    transition_duration_sec: float = 0.5
    burn_subtitle: bool = True
    subtitle_font: str = ""

    # LLM / ComfyUI 连接
    llm_api_key: str = ""
    llm_base_url: str = "https://llmapi.pcl.ac.cn/v1"
    llm_model: str = "DeepSeek-V4-Pro"
    comfy_host: str = "127.0.0.1"
    comfy_port: int = 8188

    # ── Revive 管线（原 OilPaintingRevive）配置 ──
    # 修复：config/settings.yaml 引用了这些字段但 dataclass 原先未声明，
    # 代码各处直接 settings.focal_length 访问，会 AttributeError。
    yolo_model: str = "yolov8x-seg.pt"
    yolo_conf_threshold: float = 0.4
    yolo_iou_threshold: float = 0.5
    da_v2_model: str = "depth_anything_v2_vitlarge.pth"
    depth_max: float = 12.0
    object_depth_ranges: dict[str, list[float]] = field(default_factory=dict)

    triposplat_model: str = "triposplat.ckpt"
    triposplat_repo: str = ""
    focal_length: float = 1000.0
    gaussians_per_object: int = 5000
    gs2d_repo: str = ""

    edge_align_iterations: int = 50
    edge_align_lr: float = 0.01
    inpaint_radius: int = 5
    inpaint_method: str = "telea"
    lineart_threshold: float = 0.15

    video_generator: str = "wan2.2"          # wan2.2 / ltx2.3 / mock
    num_keyframes: int = 5
    duration_sec: int = 5                     # revive 视频时长（秒）
    ltx_iclora: str = ""
    ltx_5a_resolution: tuple[int, int] = (768, 512)
    ltx_5b_denoise: float = 0.4
    depth_guide_strength: float = 1.0
    rgb_guide_strength: float = 0.6
    edge_guide_strength: float = 0.8
    controlnet_depth: str = "control_v11f1p_sd15_depth"
    controlnet_canny: str = "control_v11p_sd15_canny"
    coarse_resolution: tuple[int, int] = (768, 512)
    eval_style_threshold: float = 0.75

    # ── Canvas3D-v2 新增 ──
    scene_graph_threshold_xy: float = 0.1     # 2D 关系判定阈值（场景尺度比例）
    scene_graph_overlap_threshold: float = 0.05
    view_trajectory_mode: str = "auto_orbit"  # manual/orbit/dolly/crane/auto_orbit
    view_orbit_angle_deg: float = 30.0
    view_num_poses: int = 8
    spatial_relation_strength: float = 0.7
    spatial_text_mode: str = "i2v"            # i2v / t2v / hybrid
    spatial_gnn_hidden: int = 128

    @property
    def comfy_url(self) -> str:
        return f"http://{self.comfy_host}:{self.comfy_port}"

    def style(self, key: str | None = None) -> StylePreset:
        k = key or self.default_style
        if k not in self.styles:
            raise KeyError(f"未知风格预设: {k}（可用: {list(self.styles)}）")
        return self.styles[k]


_ASPECT_DIMS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def _load_styles(path: Path) -> dict[str, StylePreset]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, StylePreset] = {}
    for key, v in data.items():
        out[key] = StylePreset(
            key=key,
            name=v.get("name", key),
            painters=v.get("painters", []),
            positive_prefix=v.get("positive_prefix", ""),
            negative=v.get("negative", ""),
            sampler=v.get("sampler", "dpmpp_2m"),
            scheduler=v.get("scheduler", "karras"),
            cfg=float(v.get("cfg", 7.0)),
            steps=int(v.get("steps", 30)),
            bgm_mood=v.get("bgm_mood", "calm"),
        )
    return out


def load_settings(settings_path: Path | None = None) -> Settings:
    """加载 .env + settings.yaml + styles.yaml，合并为 Settings。"""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    sp = settings_path or (CONFIG_DIR / "settings.yaml")
    raw: dict[str, Any] = {}
    if sp.exists():
        raw = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}

    s = Settings()
    # 画幅 → 分辨率
    s.aspect = raw.get("aspect", s.aspect)
    if s.aspect in _ASPECT_DIMS:
        s.width, s.height = _ASPECT_DIMS[s.aspect]
    else:
        # 支持 "WxH" 自定义
        if "x" in s.aspect:
            w, h = s.aspect.split("x", 1)
            s.width, s.height = int(w), int(h)

    s.default_i2v_model = raw.get("default_i2v_model", s.default_i2v_model)
    s.target_duration_sec = int(raw.get("target_duration_sec", s.target_duration_sec))
    s.fps = int(raw.get("fps", s.fps))
    s.shot_duration_sec = int(raw.get("shot_duration_sec", s.shot_duration_sec))
    s.concurrency = int(raw.get("concurrency", s.concurrency))
    s.default_style = raw.get("default_style", s.default_style)

    s.sdxl_checkpoint = raw.get("sdxl_checkpoint", s.sdxl_checkpoint)
    s.oilpaint_lora = raw.get("oilpaint_lora", s.oilpaint_lora)
    s.oilpaint_lora_strength = float(raw.get("oilpaint_lora_strength", s.oilpaint_lora_strength))
    s.ltx_model = raw.get("ltx_model", s.ltx_model)
    s.ltx_steps = int(raw.get("ltx_steps", s.ltx_steps))
    s.ltx_cfg = float(raw.get("ltx_cfg", s.ltx_cfg))
    s.wan_model = raw.get("wan_model", s.wan_model)
    s.wan_steps = int(raw.get("wan_steps", s.wan_steps))
    s.wan_cfg = float(raw.get("wan_cfg", s.wan_cfg))
    s.wan_guidance_scale = float(raw.get("wan_guidance_scale", s.wan_guidance_scale))

    # 路径
    od = raw.get("output_dir") or ""
    s.output_dir = Path(od) if od else s.output_dir
    wd = raw.get("workflows_dir") or ""
    s.workflows_dir = Path(wd) if wd else s.workflows_dir
    ad = raw.get("assets_dir") or ""
    s.assets_dir = Path(ad) if ad else s.assets_dir
    s.ffmpeg_path = raw.get("ffmpeg_path") or ""

    # 剪辑
    s.transition = raw.get("transition", s.transition)
    s.transition_duration_sec = float(raw.get("transition_duration_sec", s.transition_duration_sec))
    s.burn_subtitle = bool(raw.get("burn_subtitle", s.burn_subtitle))
    s.subtitle_font = raw.get("subtitle_font") or ""

    # 环境变量覆盖连接信息
    s.llm_api_key = os.getenv("LLM_API_KEY", s.llm_api_key)
    s.llm_base_url = os.getenv("LLM_BASE_URL", s.llm_base_url)
    s.llm_model = os.getenv("LLM_MODEL", s.llm_model)
    s.comfy_host = os.getenv("COMFY_HOST", s.comfy_host)
    s.comfy_port = int(os.getenv("COMFY_PORT", str(s.comfy_port)))
    # ffmpeg 路径：env 优先
    s.ffmpeg_path = os.getenv("FFMPEG_PATH") or s.ffmpeg_path or ""

    # 风格预设
    s.styles = _load_styles(CONFIG_DIR / "styles.yaml")

    # ── Revive 字段 ──
    s.yolo_model = raw.get("yolo_model", s.yolo_model)
    s.yolo_conf_threshold = float(raw.get("yolo_conf_threshold", s.yolo_conf_threshold))
    s.yolo_iou_threshold = float(raw.get("yolo_iou_threshold", s.yolo_iou_threshold))
    s.da_v2_model = raw.get("da_v2_model", s.da_v2_model)
    s.depth_max = float(raw.get("depth_max", s.depth_max))
    odr = raw.get("object_depth_ranges")
    if isinstance(odr, dict):
        s.object_depth_ranges = {k: list(v) for k, v in odr.items()}

    s.triposplat_model = raw.get("triposplat_model", s.triposplat_model)
    s.triposplat_repo = raw.get("triposplat_repo", s.triposplat_repo)
    s.focal_length = float(raw.get("focal_length", s.focal_length))
    s.gaussians_per_object = int(raw.get("gaussians_per_object", s.gaussians_per_object))
    s.gs2d_repo = raw.get("gs2d_repo", s.gs2d_repo)

    s.edge_align_iterations = int(raw.get("edge_align_iterations", s.edge_align_iterations))
    s.edge_align_lr = float(raw.get("edge_align_lr", s.edge_align_lr))
    s.inpaint_radius = int(raw.get("inpaint_radius", s.inpaint_radius))
    s.inpaint_method = raw.get("inpaint_method", s.inpaint_method)
    s.lineart_threshold = float(raw.get("lineart_threshold", s.lineart_threshold))

    s.video_generator = raw.get("video_generator", s.video_generator)
    s.num_keyframes = int(raw.get("num_keyframes", s.num_keyframes))
    s.duration_sec = int(raw.get("duration_sec", s.duration_sec))
    s.ltx_iclora = raw.get("ltx_iclora", s.ltx_iclora)
    cr = raw.get("ltx_5a_resolution")
    if isinstance(cr, list) and len(cr) == 2:
        s.ltx_5a_resolution = (int(cr[0]), int(cr[1]))
    s.ltx_5b_denoise = float(raw.get("ltx_5b_denoise", s.ltx_5b_denoise))
    s.depth_guide_strength = float(raw.get("depth_guide_strength", s.depth_guide_strength))
    s.rgb_guide_strength = float(raw.get("rgb_guide_strength", s.rgb_guide_strength))
    s.edge_guide_strength = float(raw.get("edge_guide_strength", s.edge_guide_strength))
    s.controlnet_depth = raw.get("controlnet_depth", s.controlnet_depth)
    s.controlnet_canny = raw.get("controlnet_canny", s.controlnet_canny)
    cr2 = raw.get("coarse_resolution")
    if isinstance(cr2, list) and len(cr2) == 2:
        s.coarse_resolution = (int(cr2[0]), int(cr2[1]))
    s.eval_style_threshold = float(raw.get("eval_style_threshold", s.eval_style_threshold))

    # ── Canvas3D-v2 字段 ──
    s.scene_graph_threshold_xy = float(raw.get("scene_graph_threshold_xy", s.scene_graph_threshold_xy))
    s.scene_graph_overlap_threshold = float(raw.get("scene_graph_overlap_threshold", s.scene_graph_overlap_threshold))
    s.view_trajectory_mode = raw.get("view_trajectory_mode", s.view_trajectory_mode)
    s.view_orbit_angle_deg = float(raw.get("view_orbit_angle_deg", s.view_orbit_angle_deg))
    s.view_num_poses = int(raw.get("view_num_poses", s.view_num_poses))
    s.spatial_relation_strength = float(raw.get("spatial_relation_strength", s.spatial_relation_strength))
    s.spatial_text_mode = raw.get("spatial_text_mode", s.spatial_text_mode)
    s.spatial_gnn_hidden = int(raw.get("spatial_gnn_hidden", s.spatial_gnn_hidden))

    # env 覆盖：revive 模型路径
    s.yolo_model = os.getenv("YOLO_MODEL") or s.yolo_model
    s.da_v2_model = os.getenv("DA_V2_CHECKPOINT") or s.da_v2_model

    return s
