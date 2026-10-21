# SAM 3D 调研报告：集成到 Canvas3D 项目用于三维信息计算

> 论文: *SAM 3D: 3Dfy Anything in Images* (arXiv:2511.16624v2, Meta Superintelligence Labs, CVPR 2026 Best Paper Nominee)
> 代码: https://github.com/facebookresearch/sam-3d-objects
> 调研日期: 2026-10-15

---

## 1. SAM 3D 工作概述

SAM 3D 是一个从单张 RGB 图像重建 3D 物体的生成式基础模型。给定一张图像和一个二值 mask（指定目标物体），模型输出：

| 输出 | 说明 |
|------|------|
| **Geometry (shape)** | 物体 3D 形状，表示为 64³ 分辨率体素网格，经 VAE 解码为 mesh 或 3D Gaussian Splat |
| **Texture** | 物体纹理（高分辨率，由 Texture & Refinement 模型生成） |
| **Layout / Pose** | 6DoF 位姿：旋转 R∈ℝ⁶ (6D rotation)、平移 t∈ℝ³、缩放 s∈ℝ³，均在相机坐标系下 |

### 核心架构：两阶段 Latent Flow Matching

```
输入: 图像 I + 二值 mask M
         │
    ┌────▼────────────────────────────────┐
    │  DINOv2 Encoder                      │
    │  ├─ 裁剪物体 (cropped I, cropped M)  │  ← 高分辨率局部视图
    │  └─ 全图 (full I, full mask)         │  ← 全局场景上下文
    └────┬─────────────────────────────────┘
         │ 4 组 conditioning tokens
    ┌────▼────────────────────────────────┐
    │  Stage 1: Geometry Model             │
    │  1.2B 参数, Mixture-of-Transformers  │
    │  Flow Matching, NFE 4 (蒸馏后)       │
    │  输出: 粗糙体素 O (64³) + 位姿(R,t,s)│
    └────┬────────────────────────────────┘
         │ active voxels
    ┌────▼────────────────────────────────┐
    │  Stage 2: Texture & Refinement       │
    │  600M 参数, Sparse Latent Flow       │
    │  输出: 精细几何 + 高分辨率纹理        │
    └────┬────────────────────────────────┘
         │
    ┌────▼────────────────────────────────┐
    │  VAE Decoders (一对)                  │
    │  ├─ Mesh decoder  → OBJ/GLB          │
    │  └─ Gaussian decoder → 3DGS (.ply)   │
    └──────────────────────────────────────┘
```

### 可选输入：场景点图 (Scene Point Map)

模型支持可选的条件输入——一个粗糙的场景点图 P，可来自：
- 硬件传感器（如 iPhone LiDAR）
- **单目深度估计**（如 Depth Anything V2）

这使 SAM 3D 能与现有深度估计流水线集成，用于改善 layout 预测精度。

### 多物体场景重建

SAM 3D 原生支持多物体场景重建。`make_scene()` 函数将多个单物体重建结果变换到统一场景坐标系（利用各自的 R, t, s），然后拼接 Gaussian 属性（xyz, features, scaling, rotation, opacity），输出一个统一的场景级 3DGS。

---

## 2. 开源代码详情

### 仓库结构

```
sam-3d-objects/
├── sam3d_objects/          # 核心模型代码
├── notebook/
│   ├── inference.py        # 公共推理 API (Inference 类)
│   ├── images/             # 示例图像
│   └── *.ipynb             # 单物体/多物体/Body对齐 notebook
├── checkpoints/
│   └── hf/
│       └── pipeline.yaml   # 模型配置
├── environments/
│   └── default.yml         # mamba 环境定义
├── patching/
│   └── hydra               # hydra 安全补丁
├── doc/
│   └── setup.md            # 安装文档
├── demo.py                 # 快速入门脚本
├── requirements.txt
├── requirements.inference.txt
├── requirements.p3d.txt
└── pyproject.toml
```

### 硬件与环境要求

- **OS**: Linux 64-bit only（不支持 Windows）
- **GPU**: NVIDIA GPU, ≥32GB VRAM
- **CUDA**: 12.1
- **PyTorch**: 2.5.1
- **关键依赖**: kaolin==0.17.0, gsplat, pytorch3d, DINOv2

### 安装步骤

```bash
# 创建环境
mamba env create -f environments/default.yml
mamba activate sam-3d-objects

# PyTorch/CUDA 依赖
export PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"

# 安装核心包
pip install -e '.[dev]'
pip install -e '.[p3d]'

# 推理依赖
export PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"
pip install -e '.[inference]'

# hydra 补丁
./patching/hydra
```

### 模型权重下载

需在 HuggingFace 上申请访问权限后：

```bash
pip install 'huggingface-hub[cli]<1.0'
TAG=hf
hf download \
  --repo-type model \
  --local-dir checkpoints/${TAG}-download \
  --max-workers 1 \
  facebook/sam-3d-objects
mv checkpoints/${TAG}-download/checkpoints checkpoints/${TAG}
rm -rf checkpoints/${TAG}-download
```

### Python 推理 API

```python
import sys
sys.path.append("notebook")
from inference import Inference, load_image, load_single_mask, make_scene

# 加载模型
config_path = "checkpoints/hf/pipeline.yaml"
inference = Inference(config_path, compile=False)

# 加载图像和 mask
image = load_image("path/to/image.png")
mask = load_single_mask("path/to/masks_dir", index=0)

# 单物体重建
output = inference(image, mask, seed=42)

# 输出字典包含:
#   output["gaussian"][0]  → 3DGS 对象 (Gaussian splat)
#   output["rotation"]     → 四元数 R (ℝ⁴)
#   output["translation"]  → 平移 t (ℝ³)
#   output["scale"]        → 缩放 s (ℝ³)

# 导出 Gaussian splat 为 PLY
output["gaussian"][0].save_ply("object.ply")

# 多物体场景合成
output2 = inference(image, mask2, seed=42)
scene_gs = make_scene(output, output2)
scene_gs.save_ply("scene.ply")

# 可选: 传入场景点图改善 layout
# output = inference(image, mask, seed=42, pointmap=pointmap_tensor)
```

### 渲染 API

```python
from inference import ready_gaussian_for_video_rendering, render_video

# 归一化 + 对齐
scene_gs = ready_gaussian_for_video_rendering(scene_gs, fix_alignment=True)

# 桌面旋转视频渲染
frames = render_video(scene_gs, resolution=512, num_frames=300, r=2.0, fov=40)
```

---

## 3. 与 Canvas3D 当前流水线的对比分析

### 当前 Canvas3D 架构（4 模块）

| 模块 | 功能 | 当前方法 |
|------|------|----------|
| **PaintParse** | 画作实例分割 + 深度估计 + 图层分配 | YOLO-Seg + Depth Anything V2 + LoRA 微调 |
| **MonoSplat** | 单目 3DGS 物体提升 | **TripoSplat** (单图→3DGS) + 深度推导的度量缩放 |
| **SketchComp** | 线稿引导的 3D 场景合成 | 轮廓刚性配准 + 深度感知修复 |
| **ArtiFlow** | ControlNet 条件视频合成 | 多视图渲染 + Dual ControlNet + Video DiT |

### SAM 3D 可替代/增强的环节

#### 3.1 直接替代 MonoSplat 中的 TripoSplat（核心替换）

| 对比维度 | 当前: TripoSplat | 替换为: SAM 3D |
|----------|-----------------|----------------|
| **输入** | 单张裁剪图 | 单张图 + mask（与 PaintParse 输出直接对接） |
| **输出** | 3D Gaussians (规范化空间, 无度量) | 3D Gaussians **+ 纹理 + 位姿(R,t,s)** |
| **度量尺度** | ❌ 需要 Depth Anything V2 手动推导 λ_i | ✅ 内置 pose prediction，可选接收 pointmap |
| **纹理质量** | 仅 SH 一阶颜色系数 | ✅ 高分辨率纹理 (Texture & Refinement 模型) |
| **多物体** | 逐物体独立，无场景感知 | ✅ 全图上下文 (DINOv2 full-image encoding) |
| **遮挡处理** | 无场景感知，遮挡区域靠 SketchComp 修复 | ✅ 训练时专门处理遮挡和杂乱场景 |
| **推理速度** | 单次前向 | Stage1 NFE=4 (蒸馏后), sub-second |
| **模型规模** | — | Geometry 1.2B + Texture 600M = 1.8B 参数 |
| **GPU 需求** | 中等 | ≥32GB VRAM |

**关键优势**：
1. **消除手动度量缩放**：当前 MonoSplat 需要用 `λ_i = d_i · h_i^px / f` 手动从 Depth Anything V2 的相对深度推导度量尺度。SAM 3D 直接预测 (R, t, s)，且可接受 pointmap 条件输入（正好可喂入 Depth Anything V2 的深度图），由模型端到端学习尺度。
2. **纹理质量提升**：TripoSplat 仅输出 SH 一阶颜色系数；SAM 3D 的 Texture & Refinement 模型生成高分辨率纹理，对画作中精细笔触纹理的保留至关重要。
3. **场景级一致性**：SAM 3D 的 DINOv2 全图编码器提供全局上下文，对画作中物体间空间关系的理解优于逐物体独立重建。

#### 3.2 增强 PaintParse 的深度估计（可选增强）

SAM 3D 的 pointmap 条件输入接受单目深度估计结果。这意味着 PaintParse 中 Depth Anything V2 的输出不仅用于图层分配，还可以：
- 作为 SAM 3D 的 pointmap 条件，改善 layout 预测精度
- 形成更紧密的模块间耦合：PaintParse 的深度输出 → SAM 3D 的条件输入

#### 3.3 简化 SketchComp 的深度修复（间接影响）

当前 SketchComp 需要对物体位移后的遮挡区域做深度感知修复。如果 SAM 3D 提供了更完整的 3D 形状（含不可见面的完整几何而非仅 2.5D 表面），SketchComp 的修复负担减轻——因为 SAM 3D 重建的是 full 3D shape，物体旋转/位移后原本不可见的面也有几何和纹理信息。

---

## 4. 集成方案

### 方案 A: 完全替代 TripoSplat（推荐）

将 MonoSplat 模块重构为以 SAM 3D 为核心：

```
PaintParse 输出:
  - 实例 mask {M_i}
  - 深度图 D_mono (Depth Anything V2)
        │
        ▼
MonoSplat (SAM 3D 版):
  for each object i:
    output_i = SAM3D(image=P, mask=M_i, pointmap=D_mono→pointmap)
    → 3DGS_i (含纹理)
    → (R_i, t_i, s_i)  ← 直接获得位姿，无需手动缩放
  scene_gs = make_scene(output_1, ..., output_K)
        │
        ▼
SketchComp:  使用 scene_gs 进行线稿引导的物体重定位
```

**论文修改要点**：
- §3.2 MonoSplat：替换 TripoSplat 为 SAM 3D，删除手动度量缩放公式 `λ_i = d_i · h_i^px / f`，改为描述 SAM 3D 的位姿预测 + pointmap 条件
- 新增引用：SAM 3D (arXiv:2511.16624)
- Fig 3 (MonoSplat 图)：将 "TripoSplat" 框改为 "SAM 3D"，删除 "Metric Rescale" 框（或改为 "Pointmap Conditioning"）

### 方案 B: 作为可选后端（保守）

保留 TripoSplat 为默认后端，SAM 3D 作为可选的高质量后端。在实验中对比两者。这种方式适合论文中有 ablation study 的场景。

### 环境与部署考量

| 问题 | 说明 |
|------|------|
| **OS 限制** | SAM 3D 仅支持 Linux 64-bit。当前开发环境为 Windows，需在 WSL2 或 Linux 服务器上部署推理 |
| **GPU 需求** | ≥32GB VRAM，需要 A100-40G / A6000 / H100 等高端 GPU |
| **依赖复杂度** | kaolin + pytorch3d + gsplat + DINOv2，安装链较长 |
| **推理时间** | Stage1 (Geometry) sub-second (NFE=4 蒸馏后)；Stage2 (Texture) 额外数秒；总体约 5-10 秒/物体 |

---

## 5. 论文引用信息

```bibtex
@article{sam3d2026,
  title={SAM 3D: 3Dfy Anything in Images},
  author={SAM 3D Team and Chen, Xingyu and Chu, Fu-Jen and Gleize, Pierre
           and Liang, Kevin J and Sax, Alexander and Tang, Hao
           and Wang, Weiyao and Guo, Michelle and Hardin, Thibaut
           and Li, Xiang and Doll{\'a}r, Piotr and Gkioxari, Georgia
           and Feiszli, Matt and Malik, Jitendra},
  journal={arXiv preprint arXiv:2511.16624},
  year={2026}
}
```

---

## 6. 已知局限

1. **微小物体几何精度不足**：论文 Limitations 部分提到对精细小物体几何精度仍有不足
2. **无物理约束**：易出现物体悬浮、穿插等违背物理常识的重建结果
3. **Linux-only**：代码不支持 Windows 原生运行
4. **高 VRAM**：32GB 门槛对消费级显卡不友好
5. **艺术画作域偏移**：SAM 3D 训练数据以真实照片为主，对油画/水墨画等艺术风格可能有域偏移——但 DINOv2 的强泛化能力 + 全图上下文编码有助于缓解

---

## 7. 结论与建议

SAM 3D 是一个高度契合 Canvas3D 项目需求的工作：

1. **输入完美对接**：PaintParse 输出的 (image, mask) 正是 SAM 3D 的输入格式
2. **输出直接可用**：3DGS + (R,t,s) 直接喂入 SketchComp，无需手动度量缩放
3. **深度条件可选对接**：Depth Anything V2 的深度图可作为 pointmap 条件
4. **多物体场景原生支持**：`make_scene()` 直接合成多物体 3DGS 场景
5. **纹理质量显著提升**：对画作动画中物体多视角渲染的纹理连续性至关重要

**推荐采用方案 A**（完全替代 TripoSplat），在论文中将 MonoSplat 模块重构为 SAM 3D 驱动的版本，同时保留 Depth Anything V2 作为 pointmap 条件输入。这将：
- 简化流水线（删除手动度量缩放）
- 提升 3D 重建质量和纹理保真度
- 增强场景级一致性
- 引用 CVPR 2026 Best Paper Nominee 增强论文说服力

**下一步行动**：在 Linux 服务器上部署 SAM 3D 推理环境，用画作图像测试重建质量，确认艺术风格域偏移程度后再正式修改论文。
