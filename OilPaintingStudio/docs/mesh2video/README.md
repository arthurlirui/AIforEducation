# Mesh2Video —— 基于 3D 动态白膜的图生视频框架

把任意 3D 模型渲染成**动态白膜**（clay / depth / normal 三路序列），再交给
ComfyUI 的开源 I2V 模型（**Wan2.1 / LTX-Video**）生成**风格稳定**的艺术视频。

```
   3D mesh / 动画
        │  WhiteMeshRenderer（软件光栅化，无需 GPU/OpenGL）
        ▼
   depth_seq + normal_seq + clay_seq  (PNG/MP4)
        │
        │  风格参考图（单张）───► 锚定全局风格
        ▼
   ComfyUI I2V 工作流
     ├─ Wan2.1 + depth Control LoRA   （几何强控，推荐）
     └─ LTX-Video + LTXVAddGuide      （快、显存友好）
        │  TeaCache / STG / Context overlap  → 时序稳定
        ▼
   风格化视频 .mp4
```

## 设计要点

1. **3D 动态白膜**：白膜只承载几何与运动，不带纹理，让 I2V 模型自由施加艺术风格
   而不被源纹理污染。相机环绕 / 网格形变都视为"动态"。
2. **风格 × 几何解耦**：风格由单张参考图（CLIP vision / 首帧）锚定，跨帧不变；
   几何由 depth/normal 序列锁住，跨帧时序一致。两者通过 ControlNet / LTXVAddGuide
   独立注入，互不打架。
3. **风格稳定三件套**：① 风格图锚定 ② depth/normal 锁几何 ③ TeaCache（Wan）/
   STG（LTX）/ Context overlap 压时序抖动。
4. **可移植**：渲染端只依赖 `trimesh + numpy + Pillow + imageio`，离线产出 PNG/MP4；
   生成端走 ComfyUI HTTP API（已有 `ComfyClient`），节点版本变化时只改 JSON 模板。

## 文件结构

```
OilPaintingVideo/
├── src/oilpaint/mesh2video/
│   ├── __init__.py        # 对外 API
│   ├── camera.py          # 针孔相机 + orbit_camera 轨迹
│   ├── renderer.py        # WhiteMeshRenderer（clay/depth/normal 软件光栅化）
│   ├── animation.py       # AnimationDriver: Static / Morph / Callable
│   ├── pipeline.py        # Mesh2VideoPipeline + Mesh2VideoConfig（端到端编排）
│   └── example.py         # 命令行示例
├── src/oilpaint/comfy/templates/
│   ├── wan_i2v_3d_depth.json   # Wan2.1 + depth Control LoRA 工作流
│   └── ltx_i2v_3d_guide.json   # LTX-Video + LTXVAddGuide 工作流
├── config/mesh2video.yaml  # 配置
└── tests/test_mesh2video.py # 冒烟测试（6 passed）
```

## 安装

```bash
cd OilPaintingVideo
pip install -e ".[mesh2video]"   # trimesh / numpy / imageio / imageio-ffmpeg
```

## 快速开始

### 1) 仅离线渲染白膜序列（验证 3D 端，不调 ComfyUI）

```bash
python -m oilpaint.mesh2video.example \
    --mesh assets/bust.glb --render-only --work-dir output/m2v_debug
```

产物：`output/m2v_debug/{clay,depth,normal}/clay_00000.png ...` 与对应 mp4。

### 2) 端到端：3D 白膜 → Wan2.1 油画风视频

```bash
python -m oilpaint.mesh2video.example \
    --config config/mesh2video.yaml \
    --mesh assets/bust.glb \
    --style-image assets/style_vangogh.png \
    --backend wan --num-frames 49
```

### 3) 用代码调用

```python
import asyncio, trimesh, numpy as np
from oilpaint.mesh2video import (
    Mesh2VideoPipeline, Mesh2VideoConfig, StaticDriver, orbit_camera,
)

mesh = trimesh.load("bust.glb", force="mesh")
cams = orbit_camera(target=[0,0,0], radius=2.5, num_frames=49)
driver = StaticDriver(mesh=mesh, num_frames=49)

cfg = Mesh2VideoConfig(
    comfy_host="127.0.0.1", comfy_port=8188,
    backend="wan", style_image="assets/style_vangogh.png",
    num_frames=49, width=832, height=480,
    depth_control_strength=0.7,
)
asyncio.run(Mesh2VideoPipeline(cfg).run(driver, cams))
```

## 工作流拓扑

### Wan2.1 路径（`wan_i2v_3d_depth.json`，推荐主路径）

```
LoadImage(style_ref)  ──┬─► WanVideoCLIPVisionEncode ──► image_embeds
                        └─► WanVideoImageToVideoEncode ──► i2v_embeds (首帧锚定)
VHS_LoadVideo(depth_seq) ─► WanVideoEncode ─► WanVideoControlEmbeds ─► latents (几何)
WanVideoModelLoader + LoadWanVideoT5TextEncoder ─► WanVideoTextEncode (pos/neg)
WanVideoLoraSelect(depth control lora, strength=1.0)
WanVideoTeaCache(rel_l1_thresh=0.1)  +  WanVideoContextOptions(overlap=16)
   └─► WanVideoSampler ─► WanVideoDecode ─► VHS_VideoCombine
```

风格稳定：`image_embeds` 锁风格、`latents`(depth) 锁几何、TeaCache+Context 锁时序。
控制强度：`depth_control_strength`（默认 0.7）越大越贴几何，越小越自由。

### LTX-Video 路径（`ltx_i2v_3d_guide.json`，快、显存友好）

```
LoadImage(style_ref) ─► LTXVPreprocess ─► LTXVImgToVideo (首帧, strength=0.9)
VHS_LoadVideo(clay_seq) ─► LTXVAddGuide (frame_idx=0, strength=0.6)  ← 结构引导
LTXVApplySTG(block_indices="14,19") + ModelSamplingLTXV
   └─► KSampler ─► VAEDecode ─► VHS_VideoCombine
```

LTX 无原生 depth ControlNet，用白膜 clay 序列通过 `LTXVAddGuide` 注入结构引导，
配合 STG 做时序稳定。`guide_strength`（默认 0.6）控制几何贴合度。

## ComfyUI 前置依赖

### Wan2.1 路径
- 自定义节点：[ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)（Kijai）
- 权重：
  - `wan2.1_i2v_480p_bf16.safetensors`（或 720p / 14B）
  - `umt5_xxl_fp8_e4m3fn_scaled.safetensors`
  - `wan_2.1_vae.safetensors`
  - `wan2.1-1.3b-control-lora-depth-v0.1_comfy.safetensors`（depth Control LoRA，spacepxl）
  - CLIP vision: `open_clip_pytorch_model.safetensors`
- 视频组合：`ComfyUI-VideoHelperSuite`（VHS_VideoCombine / VHS_LoadVideo）

### LTX-Video 路径
- 自定义节点：[ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)
- 权重：`ltxv-2b-0.9.6-distilled.safetensors`、`ltxv-vae.safetensors`、`umt5_xxl_*.safetensors`

## 与调研结论的对应

本框架对应调研报告（`latex/FamousPaintingVideoStyle/`）中的 **Idea 1（Stroke-Anchored
Co-Painting）** 与 **Idea 4（Living-Canvas）** 的工程骨架：以 3D 白膜作为结构引导、
单张风格图锚定风格、开源本地视频骨干（Wan2.1 / LTX-Video）做生成，并保留控制强度
旋钮（`depth_control_strength` / `guide_strength`）实现精确↔模糊的连续控制。

## 现有工作流参考（调研结论）

| 项目 / 节点 | 作用 | 链接 |
|------------|------|------|
| ComfyUI-WanVideoWrapper | Wan2.1/2.2 I2V 节点全套 | https://github.com/kijai/ComfyUI-WanVideoWrapper |
| ComfyUI-LTXVideo | LTX-Video 官方节点 + STG | https://github.com/Lightricks/ComfyUI-LTXVideo |
| Wan2.1-Fun-Control | depth/canny/pose 控制视频 → Wan I2V | https://github.com/aigc-apps/VideoX-Fun |
| NVIDIA Playblast-to-Cinematic | Blender 灰模 + 风格图 → I2V（最接近本框架的现成模板） | https://github.com/NVIDIA/NVIDIA-GenAI-Creator-Toolkit |
| RenderMesh / File3DToMesh | ComfyUI 内置 3D→depth/normal 渲染 | https://docs.comfy.org/built-in-nodes/RenderMesh |
| Tex4D | 学术参考：mesh 序列 + 深度条件 VDM → 一致纹理 | https://openreview.net/forum?id=0Lpz2o6NDE |

## 测试

```bash
pytest tests/test_mesh2video.py -v
# 6 passed：相机/渲染器/序列/形变/Wan注入/LTX注入
```

## 扩展方向

- **替换渲染后端**：`WhiteMeshRenderer` 软件光栅化慢，可换 pyrender / Blender / ComfyUI
  `RenderMesh` 节点，输出格式（PNG/MP4）完全兼容。
- **骨骼动画**：用 `MorphDriver` 喂 Blender 烘焙的顶点序列，或实现一个
  `SkeletalDriver` 直接解 FBX 蒙皮。
- **多区域控制**（Idea 4）：渲染时按 mesh 子部件分区域输出多路 depth，
  分别接多个 ControlNet 分支 + 各自 `strength`。
- **风格 LoRA**：在 Wan 路径加 `WanVideoLoraSelect` 装载画家风格 LoRA（梵高/莫奈），
  与 depth Control LoRA 叠加。
