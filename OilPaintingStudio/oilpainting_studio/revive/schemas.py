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
