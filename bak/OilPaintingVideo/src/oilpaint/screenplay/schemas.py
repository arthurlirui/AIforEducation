"""剧本数据模型（pydantic v2）。

结构：Script → Scene[] → Shot[]
每个 Shot 对应一个图生视频镜头（一张关键帧 + 一段动态视频）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Shot(BaseModel):
    """单个镜头：一张油画关键帧 + 一段图生视频。"""

    index: int = Field(description="镜头在整片中的序号，从 1 开始")
    scene_index: int = Field(description="所属场景序号")
    prompt: str = Field(description="镜头画面描述（不含风格词，由管线叠加）")
    painter: str | None = Field(default=None, description="指定画家，留空则用风格预设默认")
    camera_motion: str = Field(
        default="static",
        description="镜头运动：static / pan_left / pan_right / zoom_in / zoom_out / tilt_up / tilt_down",
    )
    duration_sec: float = Field(default=3.0, description="本镜头时长（秒）")
    i2v_model: str = Field(default="ltx", description="图生视频模型：ltx / wan")
    narration: str = Field(default="", description="旁白/字幕文本")
    mood: str = Field(default="", description="镜头情绪关键词，用于匹配 BGM")

    @field_validator("camera_motion")
    @classmethod
    def _check_motion(cls, v: str) -> str:
        allowed = {
            "static", "pan_left", "pan_right", "zoom_in",
            "zoom_out", "tilt_up", "tilt_down",
        }
        if v not in allowed:
            raise ValueError(f"camera_motion 必须是 {allowed} 之一，得到 {v!r}")
        return v

    @field_validator("i2v_model")
    @classmethod
    def _check_model(cls, v: str) -> str:
        if v not in {"ltx", "wan"}:
            raise ValueError(f"i2v_model 必须是 ltx 或 wan，得到 {v!r}")
        return v


class Scene(BaseModel):
    """场景：一个叙事单元，含若干镜头。"""

    index: int = Field(description="场景序号，从 1 开始")
    title: str = Field(default="", description="场景标题")
    summary: str = Field(default="", description="场景概要")
    shots: list[Shot] = Field(default_factory=list)


class Script(BaseModel):
    """完整剧本。"""

    title: str = Field(description="短片标题")
    synopsis: str = Field(default="", description="一句话简介")
    style: str = Field(description="风格预设 key（对应 styles.yaml）")
    aspect: str = Field(default="9:16", description="画幅")
    total_duration_sec: float = Field(default=0.0, description="总时长（秒）")
    scenes: list[Scene] = Field(default_factory=list)

    @property
    def shots(self) -> list[Shot]:
        """扁平化的镜头列表。"""
        return [s for scene in self.scenes for s in scene.shots]

    def recompute_duration(self) -> None:
        self.total_duration_sec = round(sum(s.duration_sec for s in self.shots), 2)


# ── 用于 LLM 输出校验的 JSON Schema（简化版，供 prompt 参考）──
SCRIPT_JSON_SCHEMA_HINT = {
    "title": "str: 短片标题",
    "synopsis": "str: 一句话简介",
    "style": "str: 风格 key，必须从给定列表选择",
    "scenes": [
        {
            "index": "int: 场景序号",
            "title": "str: 场景标题",
            "summary": "str: 场景概要",
            "shots": [
                {
                    "index": "int: 全片镜头序号",
                    "scene_index": "int: 所属场景序号",
                    "prompt": "str: 画面描述（人物/场景/动作/光线），不含风格词",
                    "painter": "str|null: 指定画家或 null",
                    "camera_motion": "static|pan_left|pan_right|zoom_in|zoom_out|tilt_up|tilt_down",
                    "duration_sec": "float: 2~5 秒",
                    "i2v_model": "ltx|wan",
                    "narration": "str: 旁白字幕",
                    "mood": "str: 情绪关键词",
                }
            ],
        }
    ],
}
