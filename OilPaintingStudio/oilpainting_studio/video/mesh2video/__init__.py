"""mesh2video —— 基于 3D 动态白膜的图生视频框架。

整体流程::

   3D mesh/动画  ─►  WhiteMeshRenderer  ─►  depth_seq + normal_seq + clay_seq
        │                                                       │
        │                                                       ▼
   风格参考图  ─────────────────────────►  ComfyUI I2V 工作流（深度 ControlNet / LTX guide）
                                                                │
                                                                ▼
                                                        风格化视频 .mp4

设计要点
--------
* **3D 动态白膜**：把任意带骨骼/形变动画的 3D 模型，渲染成时间一致的 *白膜灰模* 序列
  （`clay` pass）以及对应的 *深度图* / *法线图* 序列。白膜只承载几何与运动，不带纹理，
  便于下游 I2V 模型自由地施加艺术风格而不被源纹理污染。
* **风格稳定**：风格由单张参考图（painter LoRA / CLIP vision）锚定，跨帧不变；
  几何由深度/法线序列锁住，跨帧时序一致。两者解耦后用 ControlNet / LTXVAddGuide 注入。
* **可移植**：渲染端只依赖 trimesh + numpy + Pillow，离线生成 PNG/MP4 序列；
  生成端通过既有 ComfyClient 提交 API 格式工作流，不绑定具体 ComfyUI 节点版本。

模块
----
* :mod:`oilpaint.mesh2video.camera`   — 简单针孔相机与轨迹
* :mod:`oilpaint.mesh2video.renderer` — 白膜 / 深度 / 法线渲染器
* :mod:`oilpaint.mesh2video.animation` — 骨骼/形变动画驱动接口
* :mod:`oilpaint.mesh2video.pipeline` — 端到端编排（render → upload → ComfyUI → 拉回）
"""
from __future__ import annotations

from .camera import Camera, orbit_camera
from .renderer import WhiteMeshRenderer, RenderPass
from .animation import AnimationDriver, StaticDriver
from .pipeline import Mesh2VideoPipeline, Mesh2VideoConfig

__all__ = [
    "Camera",
    "orbit_camera",
    "WhiteMeshRenderer",
    "RenderPass",
    "AnimationDriver",
    "StaticDriver",
    "Mesh2VideoPipeline",
    "Mesh2VideoConfig",
]
