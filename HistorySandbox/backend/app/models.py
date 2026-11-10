"""Core domain models for the historical sandbox platform."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MapScale = Literal["world", "region", "country"]


class Nation(BaseModel):
    """A polity visible on the sandbox (country / kingdom / bloc)."""
    id: str
    name: str
    color: str = "#7f8c9b"
    side: str = "neutral"           # e.g. allied / enemy / neutral, per event
    description: str = ""


class GeoArea(BaseModel):
    """A simplified 2D polygon on the map plane (lon/lat vertices)."""
    nation: str
    points: list[tuple[float, float]]


TerrainType = Literal["mountain", "river", "city", "fort", "forest", "desert", "wasteland"]


class Terrain(BaseModel):
    """A stylized terrain feature drawn in the traditional Chinese map manner.

    - mountain: 山脉，points 为山脊折线
    - river:    河流，points 为河道折线
    - forest:   树林，points 为 [中心点]，radius 为分布半径
    - desert:   沙漠，points 为区域轮廓（>=3 点则成面，否则为点状）
    - wasteland: 荒原，同 desert 的几何规则
    - city:     城池，points 为 [中心点]
    - fort:     要塞/关隘，points 为 [中心点]
    """
    type: TerrainType
    name: str = ""
    points: list[tuple[float, float]]
    label: str = ""                       # 地图上的古地名标注
    radius: float = 0.0                   # forest/desert/wasteland 分布半径（度）
    size: float = 1.0                     # 山体高度 / 城池规模等倍率
    color: str = ""                       # 可选覆盖色
    note: str = ""                        # 教学注释（如「天下第一关」）


class MapDef(BaseModel):
    scale: MapScale = "world"
    center: tuple[float, float] = (0.0, 0.0)
    zoom: float = 1.0
    areas: list[GeoArea] = []
    terrain: list[Terrain] = []           # 山川/河流/城池/要塞/树林/沙漠/荒原
    graticule: bool = True


class Actor(BaseModel):
    """A sandbox token (figure/piece) placed on the map."""
    id: str
    nation: str
    name: str
    kind: str = "army"              # army / fleet / person / trade / city / battle
    position: tuple[float, float]   # lon/lat at step 0
    strength: int = 100


class Arrow(BaseModel):
    """An advance / campaign arrow drawn between two lon/lat points."""
    label: str = ""
    points: list[tuple[float, float]]   # polyline lon/lat
    color: str = "#e74c3c"
    dashed: bool = False
    width: float = 1.0


class Highlight(BaseModel):
    """A glowing circle marking a key location."""
    position: tuple[float, float]
    radius: float = 3.0
    color: str = "#f1c40f"
    label: str = ""


class Marker(BaseModel):
    """A placed token appearing at a step (battle flags, trade nodes...)."""
    id: str
    kind: str = "battle"            # battle / city / trade / treaty / discovery
    position: tuple[float, float]
    label: str
    color: str = "#e67e22"


class SandboxStep(BaseModel):
    """One move of the sandbox replay — the atomic unit of the narration."""
    id: int
    date: str                        # display date, e.g. "208年冬"
    title: str
    narrative: str                   # what the narrator reads
    background: str = ""             # background context (背景)
    spirit: str = ""                 # spiritual core / values (精神内核)
    significance: str = ""           # historical significance (历史意义)
    camera: tuple[float, float] | None = None    # focus (lon, lat)
    camera_zoom: float | None = None
    actors: list[Actor] = []
    arrows: list[Arrow] = []
    highlights: list[Highlight] = []
    markers: list[Marker] = []
    hypothetical: bool = False       # True = world-model simulation, not recorded history


class HistoricalEvent(BaseModel):
    """A complete playable scenario on the sandbox."""
    id: str
    title: str
    subtitle: str = ""
    era: str = ""                    # e.g. "东汉末年"
    year_start: str = ""
    year_end: str = ""
    scale: MapScale = "world"
    cover: str = ""                  # cover color / emoji hint
    summary: str = ""
    spirit_core: str = ""            # one-line value theme
    map: MapDef = Field(default_factory=MapDef)
    nations: list[Nation] = []
    steps: list[SandboxStep] = []


class NarrationRequest(BaseModel):
    event_id: str
    step_id: int
    style: Literal["immersive", "academic", "storytelling"] = "immersive"


class AskRequest(BaseModel):
    event_id: str
    step_id: int | None = None
    question: str = Field(max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)


class AskAnswer(BaseModel):
    question: str
    answer: str
    source: Literal["llm", "local"] = "local"
    references: list[str] = []


class Narration(BaseModel):
    event_id: str
    step_id: int
    text: str
    source: Literal["llm", "local"] = "local"


# ------------------------------------------------- world-model interaction

CommandKind = Literal["move", "attack", "alliance", "retreat", "hypothetical"]


class WorldCommand(BaseModel):
    """A user intervention into the running sandbox simulation."""
    event_id: str
    step_id: int                     # the historical step we branch from
    command: CommandKind
    actor_id: str = ""               # target chess piece (move/attack/retreat)
    target_nation: str = ""          # alliance partner nation id
    target_position: tuple[float, float] | None = None   # destination lon/lat
    question: str = Field(default="", max_length=500)     # free-text counterfactual (hypothetical)
    seed: int = 42                   # deterministic simulation randomness
