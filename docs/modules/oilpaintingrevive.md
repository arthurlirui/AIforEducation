# OilPaintingRevive — 模块与文件参考

> **路径**: `OilPaintingRevive/` ｜ **包名**: `oilpainting-revive` (导入名 `oilrev`) ｜ **版本**: 0.1.0 ｜ **Python**: ≥ 3.11 ｜ **许可**: MIT

## 项目简介

将静态油画数字扫描件 + 手绘控制线稿转化为可探索的油画风格动态视频。管线分四个模块：YOLO 分割 → TripoSplat 3DGS 生成 → 线稿引导重排 + 修复 → 关键帧渲染 + ComfyUI ControlNet/LTX 动画生成。

**设计哲学**: 每个外部依赖都有确定性 mock 回退，全流程可在无 GPU/ComfyUI 环境下运行。

## 文件结构

```
OilPaintingRevive/
├── src/oilrev/                    # 源码包 (src-layout)
│   ├── __init__.py                # 包标记 + 版本号
│   ├── config.py                  # 配置加载 (.env + settings.yaml)
│   ├── schemas.py                 # Pydantic v2 数据模型 (阶段间契约)
│   ├── cli/                       # Click CLI
│   │   ├── __init__.py
│   │   └── main.py                # health / run 命令
│   ├── comfy/                     # ComfyUI HTTP 客户端
│   │   ├── __init__.py
│   │   └── client.py              # 异步 ComfyUI REST API 封装
│   ├── pipeline/                  # 管线编排
│   │   ├── __init__.py
│   │   ├── checkpoint.py          # 检查点持久化 (meta.json)
│   │   └── director.py            # 顶层四模块编排器
│   ├── stage1/                    # 模块1: 分割 + 深度 + 控制线稿
│   │   ├── __init__.py            # 阶段编排
│   │   ├── segment.py             # YOLO 多目标分割
│   │   ├── depth.py               # Depth Anything V2 深度估计
│   │   └── parse_control.py       # 手绘控制线稿解析
│   ├── stage2/                    # 模块2: 3DGS 生成
│   │   ├── __init__.py            # 阶段编排
│   │   ├── triposplat.py          # TripoSplat 3DGS 生成
│   │   ├── gs2d_init.py           # 2DGS 场景初始化
│   │   └── assemble.py            # 场景组装
│   ├── stage3/                    # 模块3: 重排 + 修复 + 关键帧
│   │   ├── __init__.py            # 阶段编排
│   │   ├── lineart_parse.py       # 线稿目标区域解析
│   │   ├── reposition.py          # 线稿引导 3DGS 重排
│   │   └── inpaint.py             # 孔洞修复
│   ├── stage4/                    # 模块4.1: 关键帧生成
│   │   └── __init__.py
│   ├── stage5/                    # 模块4.2: 动画生成
│   │   ├── __init__.py            # ComfyUI/mock 动画
│   │   ├── workflow.py            # ComfyUI 工作流构建
│   │   ├── ltx_iclora_workflow.json   # LTX IC-LoRA 模板
│   │   └── wan_controlnet_workflow.json # Wan ControlNet 模板
│   └── utils/                     # 工具函数
│       ├── __init__.py
│       ├── eval.py                # 评估 (风格一致性/边缘对齐/深度保真)
│       ├── image.py               # 帧序列 → MP4
│       └── vram.py                # GPU 内存管理
├── config/settings.yaml           # 全局配置
├── tests/test_pipeline.py         # 全 mock 模式端到端测试
├── docs/design.md                 # 设计文档
├── pyproject.toml                 # 项目元数据与依赖
├── .env.example                   # 环境变量模板
├── assets/                        # 输入素材 (画作 + 控制线稿)
└── output/                        # 输出目录
```

## 依赖关系图

```
config.settings.yaml + .env
        │  load_settings()
        ▼
   config.Settings  ──────────────────────────────────────────┐
        │                                                      │
        ▼                                                      ▼
schemas.Stage1Output  ─run_stage1─►  schemas.Stage2Output  (stage2)
        └─run_stage2─►                  └─run_stage3─►  schemas.Stage3Output  (stage3)
                                                        └─run_keyframe_generation─► list[KeyframeSpec] (stage4)
                                                                                    └─run_stage5─► schemas.Stage4Output (stage5)
        ▲
pipeline/director.run_pipeline() 编排 Stage1→5, 通过 checkpoint.ProjectMeta 持久化
        ▲
cli/main.py (oilrev run / oilrev health)   ← tests/test_pipeline.py (全 mock)
```

---

## 逐文件说明

### 顶层模块

#### __init__.py — 包标记

**职责**: 包初始化，声明版本号 `__version__ = "0.1.0"`。

#### config.py — 配置加载

**职责**: 从 `.env` 和 `config/settings.yaml` 加载并合并全局配置到单一 `Settings` dataclass。

| 组件 | 说明 |
|------|------|
| `Settings` (dataclass) | 全部参数: aspect/video, Module 1-4, ComfyUI, eval, paths; `comfy_url` 属性, `depth_range_for(category)` 方法 |
| `load_settings(path=None)` | 加载 .env → 读 settings.yaml → 类型强转 → 推导宽高 → 环境变量覆盖 |
| `_ASPECT_DIMS` | `{"9:16": (1080,1920), "16:9": (1920,1080)}` |

**依赖**: `os`, `dataclasses`, `pathlib`, `yaml`, `dotenv`

#### schemas.py — Pydantic 数据模型

**职责**: 定义所有四个模块的 Pydantic v2 数据模型，保证阶段间类型安全、可序列化的数据传递。

| 模型 | 所属模块 | 说明 |
|------|---------|------|
| `ObjectCategory` | 模块1 | str 枚举: PERSON/ANIMAL/BUILDING/PLANT/VEHICLE/OBJECT/BACKGROUND |
| `SegmentedObject` | 模块1 | 物体: id, category, mask_path, bbox, crop_path, depth_range |
| `ControlSignals` | 模块1 | 控制信号: edge_path, keyframe_paths |
| `Stage1Output` | 模块1 | 分割+深度+控制线稿输出 |
| `GSModelRecord` | 模块2 | 3DGS 模型记录: ply_path, num_gaussians, bbox_3d |
| `GSModelRegistry` | 模块2 | 模型注册表: `get_model(id)` 查找 |
| `Stage2Output` | 模块2 | 3DGS 生成输出: registry + scene_ply_path |
| `RepositionTransform` | 模块3 | 重排变换: translation, rotation, scale, edge_iou |
| `Stage3Output` | 模块3 | 重排+修复+关键帧输出 |
| `KeyframeSpec` | 模块4 | 关键帧: frame_index, lineart/render/depth/edge 路径 |
| `Stage4Output` | 模块4 | 动画输出: keyframes, final_video_path, eval_metrics |
| `ProjectMeta` | 全局 | 项目元数据: `mark_stage(stage, info)` 检查点追踪 |

---

### CLI 模块 (cli/)

#### cli/main.py — Click CLI 入口

**职责**: 暴露 `health` (探测 ComfyUI/配置) 和 `run` (一键端到端) 命令。

| 命令 | 说明 |
|------|------|
| `health` | 探测 ComfyUI 可用性 + 配置检查 |
| `run` | 一键: 画作 + 线稿 → 视频; 支持 `--no-comfyui` (mock) 和 `--resume` |

**入口**: `oilrev = "oilrev.cli.main:cli"`

---

### ComfyUI 客户端 (comfy/)

#### comfy/client.py — 异步 ComfyUI REST 客户端

**职责**: 封装 ComfyUI REST API 的异步 HTTP 客户端 (上传/排队/轮询/下载)，带并发限制。

| 方法 | 说明 |
|------|------|
| `health()` | 健康检查 |
| `upload_image(path)` / `upload_video(path)` | 上传素材 |
| `queue_prompt(workflow)` | 提交工作流 |
| `get_history(prompt_id)` | 轮询历史 |
| `download_view(filename, ...)` | 下载输出 |
| `run(workflow, ...)` | 高级: 提交 → 轮询 → 收集结果 |

---

### 管线编排 (pipeline/)

#### pipeline/checkpoint.py — 检查点持久化

**职责**: 通过 `meta.json` 项目文件持久化/恢复每阶段进度。

| 函数 | 说明 |
|------|------|
| `new_project(output_dir, project_id)` | 创建项目目录 |
| `init_meta(...)` / `load_meta(...)` / `save_meta(...)` | 元数据管理 |
| `mark_stage(meta, stage, info)` | 标记阶段完成 |
| `get_completed_stage(meta)` | 查询最高已完成阶段 |

#### pipeline/director.py — 顶层管线编排器

**职责**: 按序运行 Stage 1→5，带检查点续跑、阶段间 GPU 释放、最终视频路径解析。

| 函数 | 说明 |
|------|------|
| `run_pipeline(...)` | 完整管线执行 |
| `_load_stage1/2/3(...)` | 从磁盘重建阶段输出 (用于 resume) |

---

### 模块1: 分割 + 深度 + 控制线稿 (stage1/)

#### stage1/__init__.py — 阶段1编排

**职责**: 多目标 YOLO 分割 + 单目深度估计 + 控制线稿解析，产出 `Stage1Output`。

| 函数 | 说明 |
|------|------|
| `run_stage1(painting_path, project_dir, settings, ...)` | 调用 segment + depth + parse_control |

#### stage1/segment.py — YOLO 多目标分割

**职责**: 通过 YOLOv8/11/26-seg 进行多目标分割，带 K-Means + 连通组件 mock 回退。

| 函数 | 说明 |
|------|------|
| `run_segmentation(...)` | 分割 → 逐物体掩码/裁剪 + 修复背景 |
| `segment_with_yolo(...)` | 真实 YOLO 分割 |
| `segment_mock(...)` | K-Means + 连通组件回退 |
| `_label_to_category(label)` | COCO 标签 → ObjectCategory |
| `_create_background(...)` | 生成修复背景 |

#### stage1/depth.py — Depth Anything V2 深度估计

**职责**: 单目深度估计适配器，带亮度梯度 mock 回退，支持按物体类别的深度归一化。

| 函数 | 说明 |
|------|------|
| `run_depth_estimation(...)` | 深度估计入口 |
| `estimate_depth_da_v2(...)` | 真实 Depth Anything V2 |
| `estimate_depth_mock(...)` | 亮度梯度回退 |
| `normalize_depth_by_objects(...)` | 按物体类别归一化 |
| `load_depth(path)` | 16-bit PNG I/O |

#### stage1/parse_control.py — 控制线稿解析

**职责**: 加载并对齐手绘控制线稿 (物体轮廓 + 关键帧草图) 到画作尺寸；无线稿时自动生成 Canny 边缘图。

| 函数 | 说明 |
|------|------|
| `parse_controls(...)` | → `ControlSignals` |
| `_load_and_align(line_path, target_h, target_w)` | 加载 + 尺寸对齐 |

---

### 模块2: 3DGS 生成 (stage2/)

#### stage2/__init__.py — 阶段2编排

**职责**: 为每个前景物体生成 3DGS 模型，为背景生成 2DGS，组装统一场景 PLY。

| 函数 | 说明 |
|------|------|
| `run_stage2(stage1, project_dir, settings)` | → `Stage2Output` |

#### stage2/triposplat.py — TripoSplat 3DGS 生成

**职责**: 每物体单目 3DGS 生成 via TripoSplat (占位, raises ImportError) + 深度反投影 mock; 3D→2DGS surfel 转换; 背景 2DGS 生成。

| 函数 | 说明 |
|------|------|
| `generate_object_3dgs(...)` | 单物体 3DGS |
| `generate_background_2dgs(...)` | 背景 2DGS |
| `generate_with_triposplat(...)` | 真实 TripoSplat (占位) |
| `generate_triposplat_mock(...)` | 深度反投影回退 |
| `convert_3dgs_to_2dgs(...)` | 3D→2DGS 转换 |

#### stage2/gs2d_init.py — 2DGS 场景初始化

**职责**: RGB-D 反投影到点云，转换为 surfel 表示 (法线/尺度/不透明度/SH)，ASCII PLY 序列化。

| 函数 | 说明 |
|------|------|
| `depth_to_pointcloud(...)` | 深度 → 点云 |
| `pointcloud_to_surfels(...)` | 点云 → surfels |
| `surfels_to_ply(...)` | surfels → ASCII PLY |

**被复用**: `surfels_to_ply` 被 `triposplat.py` 和 `stage3/reposition.py` 调用

#### stage2/assemble.py — 场景组装

**职责**: 合并背景 2DGS 和逐物体 3DGS PLY 为单一 ASCII PLY 场景，构建 `GSModelRegistry`。

| 函数 | 说明 |
|------|------|
| `assemble_scene(...)` | → `Stage2Output` |
| `_merge_ply_files(...)` | PLY 合并 |
| `_load_ply_vertex_count(...)` | PLY 顶点计数 |

---

### 模块3: 重排 + 修复 + 关键帧 (stage3/)

#### stage3/__init__.py — 阶段3编排

**职责**: 线稿引导的 3DGS 重排 + 边缘对齐，背景孔洞修复，从编辑后场景合成关键帧 (RGB/深度/边缘)。

| 函数 | 说明 |
|------|------|
| `run_stage3(stage1, stage2, project_dir, settings)` | → `Stage3Output` |
| `_render_keyframe(surfels, img_h, img_w, focal)` | 场景 → 关键帧 |

#### stage3/lineart_parse.py — 线稿目标区域解析

**职责**: 将手绘线稿解析为目标物体区域 (距离变换 + 连通组件)，通过贪心最近中心匹配将物体分配到目标。

| 函数 | 说明 |
|------|------|
| `load_lineart(...)` | 加载线稿 |
| `extract_target_regions(...)` | 提取目标区域 |
| `match_objects_to_targets(...)` | 物体→目标匹配 |

#### stage3/reposition.py — 线稿引导 3DGS 重排

**职责**: 2D 目标反投影, 2D 掩码渲染, 边缘 IoU 计算, 无梯度迭代优化平移/旋转/缩放, PLY surfel I/O。

| 函数 | 说明 |
|------|------|
| `optimize_repositioning(...)` | 迭代优化 |
| `compute_target_3d_position(...)` | 2D→3D 目标位置 |
| `render_object_to_2d(...)` | 物体→2D 渲染 |
| `compute_edge_iou(...)` | 边缘 IoU |
| `apply_transform_to_surfels(...)` | 应用变换 |
| `load_surfels_from_ply(...)` / `save_surfels_to_ply(...)` | PLY I/O |

**被复用**: `load_surfels_from_ply` 被 `stage4` 调用

#### stage3/inpaint.py — 孔洞修复

**职责**: 使用 OpenCV inpaint (Telea/NS) 修复物体移动后暴露的背景区域，支持无缝融合。

| 函数 | 说明 |
|------|------|
| `compute_hole_mask(...)` | 计算孔洞掩码 |
| `inpaint_holes(...)` | 修复孔洞 |
| `inpaint_all_holes(...)` | 批量修复 |
| `seamless_blend(...)` | seamlessClone 无缝融合 |

---

### 模块4: 关键帧 + 动画 (stage4/ + stage5/)

#### stage4/__init__.py — 关键帧生成

**职责**: 将编辑后的 3D 场景渲染为多个关键帧，使用平滑相机偏移插值，输出每帧 RGB/深度/Canny 边缘。

| 函数 | 说明 |
|------|------|
| `run_keyframe_generation(...)` | → `list[KeyframeSpec]` |
| `render_keyframe_from_scene(...)` | 单帧渲染 |
| `interpolate_camera_offsets(...)` | 相机偏移插值 |

#### stage5/__init__.py — 动画生成

**职责**: 驱动 ComfyUI (Wan2.2 或 LTX2.3 + ControlNet) 从关键帧生成视频，带 mock 回退 (关键帧插值)。

| 函数 | 说明 |
|------|------|
| `run_stage5(...)` | 动画生成入口 |
| `generate_with_comfyui(...)` | 真实 ComfyUI 生成 (async) |
| `generate_mock(...)` | 关键帧插值回退 |
| `_create_keyframe_video(...)` | 插值视频创建 |

#### stage5/workflow.py — ComfyUI 工作流构建

**职责**: 通过加载模板 + 注入参数构建 ComfyUI 工作流 JSON (Wan2.2 I2V + depth/canny ControlNet 和 LTX-2.3 IC-LoRA)。

| 函数 | 说明 |
|------|------|
| `load_workflow_template(name)` | 加载模板 JSON |
| `apply_params(template, params)` | 按节点 ID/字段路径注入参数 |
| `build_wan_workflow(...)` | 构建 Wan 工作流 |
| `build_ltx_workflow(...)` | 构建 LTX 工作流 |

**模板文件**: `wan_controlnet_workflow.json`, `ltx_iclora_workflow.json`

---

### 工具模块 (utils/)

#### utils/eval.py — 评估

**职责**: 风格一致性 (颜色直方图余弦相似度), 边缘对齐 (平均边缘 IoU), 深度保真 (深度图方差)。

| 函数 | 说明 |
|------|------|
| `eval_style_consistency(...)` | 颜色直方图余弦相似度 |
| `eval_edge_alignment(...)` | 边缘 IoU |
| `eval_depth_fidelity(...)` | 深度方差 |
| `run_evaluation(...)` | 综合评估 |

#### utils/image.py — 帧序列 → MP4

**职责**: 通过 OpenCV VideoWriter 将 PNG 帧目录组装为 MP4 视频。

| 函数 | 说明 |
|------|------|
| `frames_to_video(frames_dir, output_path, fps)` | 帧 → MP4 |

#### utils/vram.py — GPU 内存管理

**职责**: 清空 CUDA 缓存并可选垃圾回收/卸载模型，torch 缺失时安全 no-op。

| 函数 | 说明 |
|------|------|
| `release_gpu_memory(...)` | 清空 CUDA 缓存 |
| `unload_all_models(...)` | 卸载模型 |

**被调用方**: `pipeline/director.py` (阶段间调用)

---

## 配置文件

### config/settings.yaml

扁平 YAML (无嵌套分区)，按注释头分组:

| 分区 | 关键字段 |
|------|---------|
| 宽高与视频 | `aspect`, `fps`, `duration_sec`, `coarse_resolution` |
| 模块1 (分割+深度) | `yolo_model`, `yolo_conf_threshold`, `da_v2_model`, `depth_max`, `object_depth_ranges` |
| 模块2 (3DGS) | `triposplat_model`, `focal_length`, `gaussians_per_object` |
| 模块3 (重排+修复) | `edge_align_iterations`, `edge_align_lr`, `inpaint_method`, `lineart_threshold` |
| 模块4 (动画) | `video_generator`, `num_keyframes`, `ltx_model`, `wan_model`, `controlnet_*` |
| ComfyUI | `comfy_host`, `comfy_port`, `concurrency` |
| 评估 | `eval_style_threshold` |
| 路径 | `output_dir`, `workflows_dir` |

### pyproject.toml 依赖

| 分类 | 依赖 |
|------|------|
| 核心 | httpx, pyyaml, pillow, python-dotenv, click, pydantic≥2.6, numpy, opencv-python-headless |
| dev (可选) | pytest, pytest-asyncio |
| torch (可选) | torch, torchvision |
| gs (可选) | plyfile, tqdm |

### .env.example

`COMFY_HOST`, `COMFY_PORT` — ComfyUI 连接

---

## 测试

### tests/test_pipeline.py

全 mock 模式端到端 + 逐模块测试，无需 GPU/YOLO/DepthAnything/TripoSplat/ComfyUI。

| 测试类 | 覆盖 |
|--------|------|
| `TestModule1` | 分割、背景保留、Canny 边缘 |
| `TestModule2` | 3DGS 生成、模型注册表、背景 2DGS |
| `TestModule3` | 重排、修复、关键帧尺寸 |
| `TestModule4` | 关键帧生成、mock 动画 |
| `TestFullPipeline` | 全管线 mock、检查点持久化 |
| `TestSchemas` | Pydantic 序列化 |
| `TestWorkflowTemplate` | LTX/Wan 模板加载 + 参数注入 |

**运行**: `pip install -e ".[dev]" && pytest`
