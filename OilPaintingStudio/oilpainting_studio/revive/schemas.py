"""四模块数据模型（pydantic v2）。

定义融合 3D 信息 + 手绘线稿 + 深度 + 色块的图像视频生成框架中
各模块的输入/输出结构，保证模块间数据衔接的类型安全与可序列化。

模块 1: YOLO 多物体分割 → 多物体 mask + 背景
模块 2: TripoSplat 单目三维高斯泼溅生成 + 模型注册表
模块 3: 线稿引导 3DGS 模型重定位 + 填色补缺
模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ────────────────────── Module 1: 分割 ──────────────────────

class ObjectCategory(str, Enum):
    """分割物体类别（YOLO 类别映射 + 自定义画作物体）。"""
    PERSON = "person"
    ANIMAL = "animal"
    BUILDING = "building"
    PLANT = "plant"
    VEHICLE = "vehicle"
    OBJECT = "object"       # 其他可辨识物体
    BACKGROUND = "background"


class SegmentedObject(BaseModel):
    """单个被分割出的物体。"""
    object_id: int = Field(description="唯一物体 ID（从 0 开始）")
    category: ObjectCategory
    label: str = Field(description="YOLO 检测标签（如 person, bird, house）")
    confidence: float = Field(description="检测置信度")
    mask_path: Path = Field(description="二值掩码 PNG 路径")
    bbox: tuple[int, int, int, int] = Field(description="包围盒 (x0,y0,x1,y1)")
    crop_path: Path = Field(description="裁剪图像 PNG 路径（仅物体区域）")
    depth_range: tuple[float, float] = Field(description="该物体深度范围 [near, far]")


class ControlSignals(BaseModel):
    """手绘控制线稿解析结果。"""
    edge_path: Path | None = None              # 物体轮廓线稿（Canny-like，用于模块 3）
    keyframe_paths: list[Path] = Field(default_factory=list)  # 关键帧线稿（用于模块 4）


class Stage1Output(BaseModel):
    """模块 1 输出：多物体分割 + 深度 + 背景保留 + 控制线稿。"""
    painting_path: Path
    objects: list[SegmentedObject] = Field(description="分割出的前景物体列表")
    background_mask_path: Path = Field(description="背景掩码（所有前景之外的区域）")
    background_path: Path = Field(description="背景图像（前景区域已填为均值色）")
    depth_path: Path = Field(description="单目深度图（16-bit PNG）")
    controls: ControlSignals = Field(default_factory=ControlSignals, description="控制线稿")
    width: int
    height: int
    detector: str = Field(default="mock", description="使用的检测器名称")


# ────────────────────── Module 2: 3DGS 生成 ──────────────────────

class GSModelRecord(BaseModel):
    """单个 3DGS 模型注册记录。"""
    object_id: int = Field(description="对应 SegmentedObject.object_id")
    label: str
    ply_path: Path = Field(description="三维高斯泼溅 .ply 文件路径")
    num_gaussians: int = Field(description="高斯点数量")
    bbox_3d: tuple[float, float, float, float, float, float] = Field(
        description="3D 包围盒 (xmin,ymin,zmin,xmax,ymax,zmax)")
    center_3d: tuple[float, float, float] = Field(description="模型中心 3D 坐标")
    source: str = Field(default="triposplat", description="生成来源")


class GSModelRegistry(BaseModel):
    """3DGS 模型注册表：集中管理所有前景物体的高斯泼溅模型。"""
    models: list[GSModelRecord] = Field(default_factory=list)
    background_ply_path: Path | None = Field(default=None, description="背景 2DGS PLY")

    @property
    def num_models(self) -> int:
        return len(self.models)

    def get_model(self, object_id: int) -> GSModelRecord | None:
        for m in self.models:
            if m.object_id == object_id:
                return m
        return None


class Stage2Output(BaseModel):
    """模块 2 输出：TripoSplat 3DGS 模型注册表。"""
    registry: GSModelRegistry
    scene_ply_path: Path = Field(description="统一场景 PLY（背景 + 所有前景）")


# ────────────────────── Module 3: 线稿引导重定位 ──────────────────────

class RepositionTransform(BaseModel):
    """单个物体的重定位变换。"""
    object_id: int
    label: str
    translation: tuple[float, float, float] = Field(description="平移量 (dx,dy,dz)")
    rotation_angle: float = Field(default=0.0, description="绕 Z 轴旋转角度（弧度）")
    scale: float = Field(default=1.0, description="缩放比例")
    target_bbox: tuple[int, int, int, int] = Field(description="线稿目标包围盒")
    edge_iou: float = Field(default=0.0, description="边缘对齐 IoU")


class Stage3Output(BaseModel):
    """模块 3 输出：重定位后的场景 + 填色补缺。"""
    transforms: list[RepositionTransform] = Field(default_factory=list)
    edited_scene_ply_path: Path = Field(description="编辑后统一场景 PLY")
    inpainted_background_path: Path = Field(description="填色补缺后背景图")
    keyframe_path: Path = Field(description="编辑后场景渲染的关键帧")
    keyframe_depth_path: Path = Field(description="关键帧深度图")
    keyframe_edge_path: Path = Field(description="关键帧边缘图")


# ────────────────────── Module 4: 动画生成 ──────────────────────

class KeyframeSpec(BaseModel):
    """单张关键帧规格。"""
    frame_index: int
    lineart_path: Path | None = Field(default=None, description="该帧的手绘线稿指引")
    render_path: Path = Field(description="3D 渲染关键帧 PNG")
    depth_path: Path = Field(description="关键帧深度图 PNG")
    edge_path: Path = Field(description="关键帧边缘图 PNG")


class Stage4Output(BaseModel):
    """模块 4 输出：动画视频。"""
    keyframes: list[KeyframeSpec] = Field(default_factory=list)
    final_video_path: Path
    workflow_path: Path | None = None
    generator: str = Field(default="mock", description="视频生成器 (wan2.2/ltx2.3/mock)")
    eval_metrics: dict[str, float] = Field(default_factory=dict)


# ────────────────────── 全局 ──────────────────────

class ProjectMeta(BaseModel):
    """项目元数据与检查点索引。"""
    project_id: str
    painting_path: Path
    created_at: str
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_stage: int = 0

    def mark_stage(self, stage: int, info: dict[str, Any]) -> None:
        self.stages[str(stage)] = info
        self.current_stage = max(self.current_stage, stage)


# ────────────────────── Module 6: 3D 场景图 ──────────────────────
# Canvas3D-v2 新增：将 stage1 分割 + stage2 物体级 3DGS 组织为带节点属性
# 与关系边的三维场景图，作为视角可控与空间关系可控视频的统一中间表示。

class SpatialRelationType(str, Enum):
    """场景图中两个节点之间的空间关系类型。"""
    # 2D 投影关系
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    ABOVE = "above"
    BELOW = "below"
    # 深度关系
    IN_FRONT_OF = "in_front_of"
    BEHIND = "behind"
    # 拓扑关系
    INSIDE = "inside"
    ADJACENT = "adjacent"
    OCCLUDES = "occludes"
    # 物理支撑（启发式）
    SUPPORTS = "supports"
    LEANS_ON = "leans_on"


class SceneGraphNode(BaseModel):
    """场景图节点：单个前景物体或背景。"""
    object_id: int = Field(description="对应 SegmentedObject.object_id；背景节点为 -1")
    label: str
    category: ObjectCategory
    node_type: str = Field(description="foreground / background")
    # 几何属性（世界坐标，度量尺度）
    center_3d: tuple[float, float, float]
    bbox_3d: tuple[float, float, float, float, float, float] = Field(
        description="3D 包围盒 (xmin,ymin,zmin,xmax,ymax,zmax)")
    volume: float = Field(default=0.0, description="包围盒体积（立方米）")
    height_3d: float = Field(default=0.0, description="米制高度")
    depth_range: tuple[float, float] = Field(description="[near, far] 深度范围")
    # 渲染属性
    ply_path: Path | None = None
    mask_path: Path | None = None
    # 语义属性
    salience: float = Field(default=0.0, description="显著性 [0,1]")


class SpatialRelation(BaseModel):
    """场景图中两个节点之间的有向空间关系。"""
    src_id: int
    dst_id: int
    rel_type: SpatialRelationType
    confidence: float = Field(default=1.0, description="关系置信度 [0,1]")
    # 可量化属性（可选）
    distance_3d: float | None = None
    overlap_ratio: float | None = None
    depth_gap: float | None = None


class SceneGraph(BaseModel):
    """完整三维场景图：节点 + 关系 + 全局场景属性。"""
    nodes: list[SceneGraphNode] = Field(default_factory=list)
    relations: list[SpatialRelation] = Field(default_factory=list)
    background_node_id: int | None = None
    # 全局场景属性
    scene_extent: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 0.0), description="场景三轴尺度 (sx, sy, sz)")
    focal_length: float = 1000.0
    principal_point: tuple[float, float] = (0.0, 0.0)
    # 序列化路径
    graph_path: Path | None = None

    def get_node(self, object_id: int) -> SceneGraphNode | None:
        for n in self.nodes:
            if n.object_id == object_id:
                return n
        return None

    def relations_of(self, node_id: int) -> list[SpatialRelation]:
        return [r for r in self.relations if r.src_id == node_id or r.dst_id == node_id]


class Stage6Output(BaseModel):
    """模块 6 输出：三维场景图。"""
    scene_graph: SceneGraph
    graph_path: Path = Field(description="scene_graph.json 路径")
    num_nodes: int
    num_relations: int


# ────────────────────── Module 7: 视角可控新视角 ──────────────────────
# Canvas3D-v2 新增：用户指定视角轨迹（手动 / 轨道 / 推拉 / 俯仰 / 自动），
# 模块从编辑后场景渲染多视角关键帧流，附带每帧每节点可见性 mask。

class CameraPose(BaseModel):
    """单相机位姿。"""
    position: tuple[float, float, float]
    look_at: tuple[float, float, float]
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    fov_deg: float = 55.0


class ViewpointTrajectory(BaseModel):
    """视角轨迹。"""
    poses: list[CameraPose] = Field(default_factory=list)
    interpolation: str = Field(default="bspline", description="bspline/linear/lookat_orbit")
    mode: str = Field(default="manual", description="manual/orbit/dolly/crane/auto_orbit")
    orbit_params: dict[str, Any] | None = None
    focus_node_id: int | None = None


class ViewframeSpec(BaseModel):
    """单视角帧规格（含可见性 mask）。"""
    frame_index: int
    pose: CameraPose
    render_path: Path
    depth_path: Path
    edge_path: Path
    visibility_mask_path: Path = Field(description="每节点可见性 mask (多通道 PNG 或 npz)")
    visible_node_ids: list[int] = Field(default_factory=list)


class Stage7Output(BaseModel):
    """模块 7 输出：多视角关键帧流。"""
    trajectory: ViewpointTrajectory
    keyframes: list[ViewframeSpec] = Field(default_factory=list)
    avg_visible_nodes: float = Field(default=0.0)


# ────────────────────── Module 8: 空间关系可控视频 ──────────────────────
# Canvas3D-v2 新增：在 ArtiFlow 双控制（深度+边缘）之上注入第三路「关系图嵌入」，
# 用文本 + 空间关系图联合驱动 video diffusion 生成三维关系可控的动态视频。

class SpatialEditType(str, Enum):
    MOVE = "move"
    ROTATE = "rotate"
    SCALE = "scale"
    ADD_RELATION = "add_relation"
    REMOVE_RELATION = "remove_relation"
    CHANGE_RELATION = "change_relation"


class SpatialEdit(BaseModel):
    """单条空间关系编辑指令。"""
    edit_type: SpatialEditType
    target_node_id: int | None = None
    translation: tuple[float, float, float] | None = None
    rotation_deg: float | None = None
    scale_factor: float | None = None
    relation: SpatialRelation | None = None
    text_prompt: str = ""


class SpatialEditSpec(BaseModel):
    """空间关系编辑规格（模块 8 输入）。"""
    edits: list[SpatialEdit] = Field(default_factory=list)
    edited_graph_path: Path | None = None
    text_prompt: str = Field(default="", description="全局视频意图文本")
    negative_prompt: str = ""
    num_frames: int = 25
    fps: int = 8
    depth_strength: float = 0.85
    edge_strength: float = 0.6
    relation_strength: float = 0.7
    generation_mode: str = Field(default="i2v", description="i2v/t2v/hybrid")


class Stage8Output(BaseModel):
    """模块 8 输出：空间关系可控的动态视频。"""
    final_video_path: Path
    workflow_path: Path | None = None
    generator: str = Field(default="mock")
    relation_embedding_path: Path | None = None
    consistency_metrics: dict[str, float] = Field(default_factory=dict)
