"""GUI 数据模型（设计文档 §3.3–§3.4）。

project.json 与 scene.json 的 pydantic 模型；分段字段与
``revive.schemas`` 的 Stage*Output 对齐，保证 CLI 与 GUI 产物互通。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────── project.json ─────────────────────────

class StageStatus(str, Enum):
    TODO = "todo"
    RUNNING = "running"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


class PaintingSource(BaseModel):
    path: str = Field(description="相对项目根的原画路径, 如 source/painting.png")
    width: int = 0
    height: int = 0
    md5: str = ""
    thumb_path: str = Field(default="source/painting.thumb.jpg")


class StageState(BaseModel):
    status: StageStatus = StageStatus.TODO
    updated: datetime = Field(default_factory=_now)
    artifact: str | None = Field(default=None, description="阶段产物相对路径")
    detail: str = ""


class ProjectMeta(BaseModel):
    """project.json 主体（§3.3）。"""
    schema_version: int = 1
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    created_at: datetime = Field(default_factory=_now)
    painting: PaintingSource
    pipeline_state: dict[str, StageState] = Field(
        default_factory=lambda: {k: StageState() for k in
                                 ("segment", "gs", "scene", "keyframe", "compose")})

    def stage(self, key: str) -> StageState:
        if key not in self.pipeline_state:
            self.pipeline_state[key] = StageState()
        return self.pipeline_state[key]


class ObjectMeta(BaseModel):
    """stage1/objects/<oid>/meta.json（含 GUI 审校扩展字段）。"""
    object_id: int
    category: str = "object"
    label: str
    confidence: float = 0.0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    depth_range: tuple[float, float] = (0.0, 0.0)
    color: str = "#5b8cff"
    rejected: bool = False
    mask_version: int = 1
    mask_path: str = "mask.png"
    crop_path: str = "crop.png"
    gs_version: int = 0                # 0 = 尚未生成; 每次 TripoSplat 重跑 +1
    gs_source_ply: str | None = None   # 相对项目路径


class UndoEntry(BaseModel):
    """undo 栈条目（§3.3）。JSON 操作记 before/after；
    位图操作（mask.paint/lineart.paint）before/after 为 "file:.undo/<name>"
    快照文件标记（快照落盘, 非整图 base64 常驻内存）。

    undo/redo 栈持久化到 project/.undo/undo.json, 进程重启后由
    ProjectStore 回载（快照缺失的条目跳过）; 50 条上限滚动淘汰,
    被淘汰条目的快照文件一并清理。
    """
    op: str
    target: str
    before: Any | None = None
    after: Any | None = None
    ts: datetime = Field(default_factory=_now)


# ───────────────────────── scene.json ─────────────────────────

class Transform(BaseModel):
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_quat: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


class CameraRig(BaseModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    look_at: tuple[float, float, float] = (0.0, 0.0, -1.0)
    fov: float = 50.0
    locked_to_painting: bool = True


class SceneNode(BaseModel):
    """场景图节点（§3.4）。kind=gs_object/gs_background/group。"""
    node_id: str
    kind: Literal["gs_object", "gs_background", "group"] = "gs_object"
    label: str = ""
    source_ply: str = ""
    parent: str | None = None
    transform: Transform = Field(default_factory=Transform)
    visible: bool = True
    locked: bool = False
    keyframes: dict[str, Transform] = Field(default_factory=dict)


class SceneGraph(BaseModel):
    """scene.json 主体（§3.4）。"""
    schema_version: int = 1
    camera: CameraRig = Field(default_factory=CameraRig)
    ground: Literal["auto", "grid", "none"] = "auto"
    nodes: list[SceneNode] = Field(default_factory=list)
    edited_scene_ply_path: str | None = None


# ───────────────────────── 任务队列 ─────────────────────────

class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskInfo(BaseModel):
    """任务信息。

    线程安全约定: worker 线程写 log/progress/result, 请求线程读;
    读写均需经 TaskQueue 的锁（queue.snapshot(task) 在锁内拷贝后序列化）。
    log 上限 500 条, 超出丢弃最旧。
    """
    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    kind: str                          # segment / gs / snapshot / compose
    project_id: str
    label: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    progress: float = 0.0              # 0..1
    log: list[str] = Field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    cancel_requested: bool = Field(default=False, exclude=True)

    MAX_LOG: ClassVar[int] = 500
    """日志上限（类常量, 非字段）。"""

    def append_log(self, line: str) -> None:
        """追加日志（有界, 超出丢最旧）。append 对 list 原子; 读侧经
        TaskQueue.snapshot 在锁内拷贝, 避免序列化竞态。"""
        self.log.append(line)
        if len(self.log) > self.MAX_LOG:
            del self.log[:len(self.log) - self.MAX_LOG]


# ───────────────────────── 关键帧 ─────────────────────────

class KeyframeMeta(BaseModel):
    keyframe_id: str
    label: str = ""
    rgb_path: str
    depth_path: str | None = None
    edge_path: str | None = None
    lineart_path: str | None = None
    source: Literal["snapshot", "hand_drawn"] = "snapshot"


# ───────────────────────── API payload ─────────────────────────

class ScenePatch(BaseModel):
    """PATCH /scene 的增量更新。任一字段可选。"""
    node_id: str
    transform: Transform | None = None
    visible: bool | None = None
    locked: bool | None = None
    parent: str | None = None
    label: str | None = None
    add_keyframe: str | None = None    # 在该节点上追加关键帧位姿


class SegmentRunRequest(BaseModel):
    detector: Literal["yolo", "mock"] = "mock"
    conf_threshold: float = 0.4


class GSRunRequest(BaseModel):
    object_ids: list[int] = Field(default_factory=list,
                                  description="为空 = 所有未生成且未拒绝的物体")


class ComposeRunRequest(BaseModel):
    keyframe_ids: list[str] = Field(default_factory=list)
    model: Literal["wan2.2", "ltx"] = "wan2.2"
    depth_weight: float = 0.85
    canny_weight: float = 0.6
    prompt: str = ""
    aspect: Literal["16:9", "9:16"] = "16:9"
    duration_sec: int = 5
