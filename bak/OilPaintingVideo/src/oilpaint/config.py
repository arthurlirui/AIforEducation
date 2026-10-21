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

    return s
