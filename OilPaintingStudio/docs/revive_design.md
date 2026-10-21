# 融合 3D 信息的图像视频生成框架 — 设计文档

> 将油画或水墨画的不同部分通过 3D 信息分割、重建、编辑，结合手绘线稿 + 深度信息 + 色块信息，
> 生成可控的高质量动画视频。
>
> 四模块流水线：YOLO 分割 → TripoSplat 3DGS 生成 → 线稿引导重定位 → ComfyUI ControlNet 动画生成。

## 系统概述

本框架融合三维信息（3DGS）、手绘线稿（物体轮廓 + 关键帧草图）、深度信息和色块信息，
通过四个模块实现从静态画作到可控动画视频的完整生成流程。

### 核心设计理念

- **3D 重建**：通过 TripoSplat 为每个分割物体生成单目三维高斯泼溅模型，实现 3D 空间中的自由编辑
- **线稿引导**：手绘线稿指引物体的目标位置和动画关键帧，实现精准的画面控制
- **深度 + 边缘双控**：通过 ControlNet 的深度和边缘通道同时引导动画生成，保证结构一致性
- **模块化注册表**：3DGS 模型注册表集中管理所有前景物体，支持独立操作和统一组装

## 四模块架构

```
┌──────────────────────────────────────────────────────────────┐
│                    输入：油画/水墨画 + 手绘线稿                   │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│ 模块 1: YOLO 多物体分割                                        │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│ │ YOLO26-seg   │  │ Depth        │  │ 控制线稿解析  │         │
│ │ 多物体 mask  │  │ Anything V2  │  │ (轮廓+关键帧) │         │
│ │ + 背景保留   │  │ 单目深度估计  │  │              │         │
│ └──────────────┘  └──────────────┘  └──────────────┘         │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│ 模块 2: TripoSplat 3DGS 生成 + 模型注册表                       │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│ │ 前景:        │  │ 背景:        │  │ 模型注册表    │         │
│ │ TripoSplat   │  │ RGB-D 反投影 │  │ GSModelRegistry│        │
│ │ → 3DGS surfel│  │ → 2DGS       │  │ (集中管理)    │         │
│ └──────────────┘  └──────────────┘  └──────────────┘         │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│ 模块 3: 线稿引导 3DGS 重定位 + 填色补缺                          │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│ │ 线稿目标轮廓  │  │ 边缘对齐优化  │  │ 填色补缺     │         │
│ │ 提取 + 匹配   │  │ (IoU 迭代)   │  │ (inpaint)   │         │
│ └──────────────┘  └──────────────┘  └──────────────┘         │
│                    → 编辑后关键帧 (RGB + Depth + Edge)         │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│ 模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成                 │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│ │ 多关键帧渲染  │  │ Wan2.2 I2V  │  │ LTX2.3       │         │
│ │ (3D → 2D)   │  │ +Depth CN   │  │ IC-LoRA      │         │
│ │              │  │ +Canny CN   │  │ Union Control│         │
│ └──────────────┘  └──────────────┘  └──────────────┘         │
│                    → 最终动画视频 (.mp4)                       │
└──────────────────────────────────────────────────────────────┘
```

## 模块详细设计

### 模块 1: YOLO 多物体图像分割

**目标**：将油画或水墨画的不同部分分割出来，形成多个物体的 mask，并保留背景。

**核心组件**：
- `segment.py`: YOLO 分割适配器
  - 支持 YOLOv8-seg / YOLO11-seg / YOLO26-seg（ultralytics 统一接口）
  - COCO 标签到画作物体类别的映射（person → person, bird → animal 等）
  - Mock fallback: K-Means 颜色聚类 + 连通域分析
- `depth.py`: Depth Anything V2 深度估计
  - 按物体类别做深度归一化（近大远小）
  - Mock fallback: 纵向梯度 + 亮度调制
- `parse_control.py`: 控制线稿解析
  - 物体轮廓线稿（指引模块 3 重定位）
  - 关键帧线稿（指引模块 4 动画）
  - 无线稿时自动生成 Canny 边缘

**输出**：`Stage1Output`
- `objects`: `list[SegmentedObject]` — 每个物体含 mask, bbox, crop, depth_range
- `background_mask_path`: 背景掩码（所有前景之外的区域）
- `background_path`: 背景图像（前景区域 inpaint 填充）
- `depth_path`: 单目深度图
- `controls`: 控制线稿信号

### 模块 2: TripoSplat 3DGS 生成 + 模型注册表

**目标**：针对每一个分割出来的前景物体生成单目三维高斯泼溅模型，并集中管理。

**核心组件**：
- `triposplat.py`: TripoSplat 3DGS 生成
  - `generate_object_3dgs()`: 为单个物体生成 3DGS，返回 `GSModelRecord`
  - 3DGS → 2DGS surfel 转换（最短轴 → 法线方向）
  - Mock fallback: 从裁剪图 + 深度反投影生成 3D 高斯点云
- `gs2d_init.py`: 背景生成
  - `depth_to_pointcloud()`: RGB-D 反投影为点云
  - `pointcloud_to_surfels()`: 点云 → surfel 表示
  - `surfels_to_ply()`: PLY 序列化
  - `generate_background_2dgs()`: 背景生成 2DGS surfel
- `assemble.py`: 场景组装 + 注册表构建
  - 合并背景 PLY + 各前景 PLY 为统一场景
  - 构建 `GSModelRegistry` 集中管理

**模型注册表设计**：
```python
class GSModelRegistry:
    models: list[GSModelRecord]      # 各前景物体 3DGS 记录
    background_ply_path: Path        # 背景 2DGS PLY
    def get_model(object_id) -> GSModelRecord | None  # 按 ID 查找
```

**输出**：`Stage2Output`
- `registry`: `GSModelRegistry` — 模型注册表
- `scene_ply_path`: 统一场景 PLY

### 模块 3: 线稿引导 3DGS 重定位 + 填色补缺

**目标**：根据手绘线稿，将多个高斯泼溅模型移动到线稿位置上，使边缘贴合，
并通过填色算法补上物体移动导致的缺口。

**核心组件**：
- `lineart_parse.py`: 线稿解析与目标轮廓提取
  - `load_lineart()`: 加载并二值化线稿
  - `extract_target_regions()`: 距离变换 + 连通域分析提取目标区域
  - `match_objects_to_targets()`: 贪心最近匹配物体到目标
- `reposition.py`: 3DGS 模型重定位
  - `optimize_repositioning()`: 迭代优化平移/旋转/缩放使渲染边缘与线稿边缘 IoU 最大
  - `apply_transform_to_surfels()`: 将变换应用到 surfel 点云
  - `render_object_to_2d()`: 渲染 3DGS 到 2D mask（用于边缘对齐计算）
  - `compute_edge_iou()`: 渲染边缘与目标线稿边缘的 IoU
- `inpaint.py`: 填色补缺
  - `compute_hole_mask()`: 计算物体移动后暴露的缺口
  - `inpaint_holes()`: OpenCV inpaint（Telea / Navier-Stokes）
  - `seamless_blend()`: 无缝融合（seamlessClone）

**关键算法 — 边缘对齐优化**：
```
for iteration in range(edge_align_iterations):
    rendered_mask = render_object_to_2d(surfels, translation, rotation, scale)
    iou = compute_edge_iou(rendered_mask, target_edge)
    # 小扰动各参数（tx, ty, rotation, scale）测试 IoU 变化
    # 选择 IoU 最大的方向更新参数
```

**输出**：`Stage3Output`
- `transforms`: `list[RepositionTransform]` — 每个物体的重定位变换（平移/旋转/缩放/edge_iou）
- `edited_scene_ply_path`: 编辑后统一场景 PLY
- `inpainted_background_path`: 填色补缺后背景图
- `keyframe_path` / `keyframe_depth_path` / `keyframe_edge_path`: 关键帧三件套

### 模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成

**目标**：将编辑后的三维场景渲染为初步的关键帧，多张关键帧通过 ComfyUI 框架
（Wan2.2 或 LTX2.3），结合 ControlNet（深度 + 边缘）控制模块，生成高质量动画。

**核心组件**：
- `stage4/__init__.py`: 关键帧生成
  - `render_keyframe_from_scene()`: 从编辑后场景渲染关键帧
  - `interpolate_camera_offsets()`: 平滑相机偏移序列
  - 输出: RGB + Depth + Edge 三件套
- `stage5/workflow.py`: ComfyUI 工作流构造
  - `build_wan_workflow()`: Wan2.2 I2V + ControlNet (depth + canny) 工作流
  - `build_ltx_workflow()`: LTX-2.3 IC-LoRA Union Control (depth + rgb) 工作流
- `stage5/__init__.py`: 动画生成
  - `generate_with_comfyui()`: ComfyUI HTTP API 调用
  - `generate_mock()`: 关键帧插值合成为视频（无 ComfyUI 时）

**ControlNet 双通道引导**：
- 深度通道（depth_guide_strength）: 保证 3D 结构一致性
- 边缘通道（edge_guide_strength）: 保证物体轮廓和位置控制

**输出**：`Stage4Output`
- `keyframes`: `list[KeyframeSpec]` — 关键帧规格列表
- `final_video_path`: 最终动画视频
- `generator`: 生成器名称（wan2.2/ltx2.3/mock）

## 软件架构

```
src/oilrev/
├── config.py              # 配置加载（.env + settings.yaml）
├── schemas.py             # 四模块数据模型（pydantic v2）
├── stage1/                # 模块 1: YOLO 分割
│   ├── __init__.py        #   编排: run_stage1()
│   ├── segment.py         #   YOLO 分割 + mock fallback
│   ├── depth.py           #   Depth Anything V2 + mock fallback
│   └── parse_control.py   #   控制线稿解析
├── stage2/                # 模块 2: 3DGS 生成
│   ├── __init__.py        #   编排: run_stage2()
│   ├── triposplat.py      #   TripoSplat 3DGS 生成 + 3DGS→2DGS 转换
│   ├── gs2d_init.py       #   RGB-D 反投影 + surfel PLY 序列化
│   └── assemble.py        #   场景组装 + 模型注册表
├── stage3/                # 模块 3: 线稿引导重定位
│   ├── __init__.py        #   编排: run_stage3()
│   ├── lineart_parse.py   #   线稿解析 + 目标轮廓提取 + 物体匹配
│   ├── reposition.py      #   边缘对齐优化 + 变换应用
│   └── inpaint.py         #   填色补缺 + 无缝融合
├── stage4/                # 模块 4: 关键帧生成
│   └── __init__.py        #   关键帧渲染: run_keyframe_generation()
├── stage5/                # 模块 4: 动画生成
│   ├── __init__.py        #   编排: run_stage5()
│   ├── workflow.py        #   ComfyUI 工作流构造（Wan2.2 / LTX2.3）
│   ├── ltx_iclora_workflow.json       # LTX IC-LoRA 工作流模板
│   └── wan_controlnet_workflow.json   # Wan2.2 ControlNet 工作流模板
├── comfy/
│   └── client.py          # ComfyUI HTTP 客户端
├── pipeline/
│   ├── director.py        # 四模块流水线编排器
│   └── checkpoint.py      # 检查点管理
├── utils/
│   ├── image.py           # 图像/视频工具
│   ├── eval.py            # 评估钩子
│   └── vram.py            # 显存管理
└── cli/
    └── main.py            # CLI 入口（click）
```

## 关键 GitHub 组件

| 组件 | 用途 | 仓库 |
|------|------|------|
| ultralytics (YOLO) | 多物体分割 | ultralytics/ultralytics |
| Depth Anything V2 | 单目深度估计 | DepthAnything/Depth-Anything-V2 |
| TripoSplat | 单图 3DGS 生成 | VAST-AI-Research/TripoSplat |
| 2DGS | 2D 高斯泼溅 | hbb1/2d-gaussian-splatting |
| ComfyUI-LTXVideo | LTX 视频生成 | Lightricks/ComfyUI-LTXVideo |
| Wan2.2 | I2V 视频生成 | Wan-Video/Wan2.2 |
| ControlNet | 深度+边缘控制 | lllyasviel/ControlNet |

## Mock 模式

所有外部依赖（YOLO、Depth Anything、TripoSplat、ComfyUI、Wan2.2、LTX2.3）均有
确定性的 mock fallback，使完整流程可在无 GPU 环境下测试：

| 组件 | Mock 策略 |
|------|----------|
| YOLO | K-Means 颜色聚类 + 连通域分析 |
| Depth Anything | 纵向梯度 + 亮度调制 |
| TripoSplat | RGB-D 反投影生成 3D 高斯点云 |
| 边缘对齐 | 简化梯度估计 + 小扰动搜索 |
| 填色补缺 | OpenCV inpaint (Telea) |
| ComfyUI | 关键帧插值合成为视频 |

## CLI 用法

```bash
# 探测 ComfyUI
oilrev health

# 端到端（mock 模式）
oilrev run painting.png --no-comfyui --project-id demo

# 端到端（ComfyUI 模式）
oilrev run painting.png --lineart object_lineart.png --keyframe kf1.png --keyframe kf2.png

# 从检查点恢复
oilrev run painting.png --resume --project-id demo
```
