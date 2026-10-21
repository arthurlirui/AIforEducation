# 架构总览

## 1. Monorepo 定位

AIforEducation 是一个面向 **AI + 教育** 的研究型 monorepo，包含五个独立但主题相关的子项目。前四个围绕"用 AI 技术辅助艺术创作与艺术教育"，TechLearnStudio 则把同一思路推广到"用 AI 辅助人类快速学习新技术与专业课"，涵盖视觉风格迁移、过程评估、动态化生成、技术学习等方向。

## 2. 子项目一览

| 子项目 | 核心目标 | 技术栈 | 语言 | 测试 |
|--------|---------|--------|------|------|
| **AIforPolkaDotsArt** | 将输入图片转化为草间弥生风格的波点艺术 | Weighted Voronoi Stippling, YOLO26 (深度+语义分割), OpenCV, NumPy, SciPy | Python | 无正式测试 (demo + 参数扫描) |
| **GestureCoach** | 分析绘画过程中的手势动态，诊断学习者与艺术家技法的偏差，给出纠正反馈 | MediaPipe Hands, DTW + Procrustes, ST-GCN + Bi-GRU, FastAPI, React | Python + JavaScript | pytest (12+ 测试文件) |
| **OilPaintingRevive** | 将静态油画扫描件 + 手绘线稿转化为可探索的油画风格动态视频 | YOLO 分割, Depth Anything V2, TripoSplat 3DGS, ComfyUI (Wan/LTX + ControlNet), Pydantic | Python | pytest (mock 全链路) |
| **OilPaintingVideo** | LLM 生成剧本 → ComfyUI 生成油画关键帧 → I2V 视频生成 → ffmpeg 自动剪辑 | OpenAI-compatible LLM, ComfyUI (LTX/Wan I2V), Pydantic, Click CLI, ffmpeg | Python | pytest (集成 + 单元) |
| **TechLearnStudio** | 读取技术文档/讲义，自动生成 hyperframes 可交互网页 PPT + 动画，讲解技术原理与设计思路，支持自动更新 | FastAPI, Vue3, 自研 Hyperframe Engine, Pyodide, Docker sandbox, APScheduler, LLM | Python + TypeScript | 设计稿阶段 |

## 3. 项目间关系

```
                    ┌──────────────────────────────────────────────┐
                    │           AIforEducation Monorepo            │
                    └──────────────────────┬───────────────────────┘
                                           │
           ┌───────────────────┬───────────┴───────────┬───────────────────┐
           │                   │                       │                   │
    AIforPolkaDotsArt    GestureCoach         OilPaintingRevive    OilPaintingVideo
    (风格化图像生成)     (过程评估反馈)        (静态画→动态视频)      (剧本→油画视频)
           │                   │                       │                   │
    stippling 核心      tracking→features       YOLO→3DGS→重排        LLM→ComfyUI→ffmpeg
    + depth-aware       →DTW→diagnosis          →关键帧→动画          全链路自动化
    + 语义双染色         →feedback              + mock fallback        + mesh2video 扩展
```

### 3.1 共享资源

- **`images/`** — 18 张经典油画高清扫描（达芬奇、梵高、西斯莱等），被 OilPaintingRevive 和 OilPaintingVideo 用作输入素材
- **`latex/`** — IJCAI'26 论文 LaTeX 模板及论文源码，被多个子项目的 `paper/` 或 `latex/` 子目录引用

### 3.2 技术交叉点

| 技术 | 涉及项目 | 说明 |
|------|---------|------|
| YOLO (ultralytics) | AIforPolkaDotsArt, OilPaintingRevive | 前者用于深度估计+语义分割，后者用于多目标分割 |
| ComfyUI HTTP API | OilPaintingRevive, OilPaintingVideo | 两者都有独立的 async ComfyClient 封装 |
| Pydantic v2 | OilPaintingRevive, OilPaintingVideo | 用于阶段间数据模型的类型安全传递 |
| OpenCV (cv2) | 全部四个项目 | 图像处理基础工具 |
| PyTorch | GestureCoach, OilPaintingRevive | 前者用于 ST-GCN/YOLO/U-Net，后者用于 Depth Anything V2 |

## 4. 各项目架构要点

### 4.1 AIforPolkaDotsArt — 双层架构

```
stippling.py (共享计算核心: Voronoi stippling)
     ├── kusama.py (基础版渲染器: 亮度密度调制)
     │     └── run_demo.py, gen_test_images.py
     └── depth_kusama.py (深度感知版: 深度→半径, 语义双染色)
           └── run_depth_demo.py, run_param_test.py
```

- **基础版**: 纯 CPU (NumPy + SciPy + OpenCV)，Voronoi stippling + Canny 边缘 + 恐惧真空背景填充
- **深度感知版**: 需 GPU + YOLO26 模型权重，三层架构 (精细点层 + 深度强调层 + 边缘层)，前景感知深度归一化

### 4.2 GestureCoach — 闭环管线

```
              ┌─────────────────────────────────────────────┐
              │              GestureCoachPipeline            │
              └─────────────────────────────────────────────┘
                                │
  tracking → features → template → DTW → diagnosis → feedback
  (MediaPipe)  (角度/轨迹/节奏)  (模板库)  (改进DTW)  (四轴偏差)  (规则引擎+LLM)
                                │
              ┌─────────────────┴──────────────────┐
              │         并行视觉路径                │
              │  detection → segmentation → toolhand│
              │  (YOLO)       (U-Net)       (两阶段)│
              └────────────────────────────────────┘
                                │
                    stages (ST-GCN + Bi-GRU)
                    (自动绘画阶段分割)
                                │
                    api (FastAPI REST + WebSocket)
                    frontend (React + WebRTC + MediaPipe)
```

- **设计哲学**: 过程导向而非结果导向——评估绘画"怎么画"而非"画得怎样"
- **原型策略**: MediaPipe 和 LLM 都是可选的，系统可在纯合成数据上离线运行

### 4.3 OilPaintingRevive — 四模块管线

```
Module 1 (stage1)          Module 2 (stage2)         Module 3 (stage3)         Module 4 (stage4+5)
┌─────────────────┐        ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ YOLO 分割       │──→     │ TripoSplat 3DGS │──→    │ 线稿引导重排    │──→    │ 关键帧渲染      │
│ Depth Anything  │        │ 2DGS 背景       │       │ 边缘对齐优化    │       │ ComfyUI 动画    │
│ 控制线稿解析    │        │ 场景组装        │       │ 孔洞修复        │       │ (Wan/LTX)       │
└─────────────────┘        └─────────────────┘       └─────────────────┘       └─────────────────┘
     schemas.Stage1Output       schemas.Stage2Output      schemas.Stage3Output      schemas.Stage4Output
```

- **设计哲学**: 每个外部依赖都有确定性 mock 回退，全流程可在无 GPU/ComfyUI 环境下运行
- **数据契约**: Pydantic 模型 (`Stage1Output` → `Stage4Output`) 保证阶段间类型安全
- **检查点**: `meta.json` 记录每阶段完成状态，支持断点续跑

### 4.4 OilPaintingVideo — 三阶段管线

```
Stage 1: Generate              Stage 2: Render                Stage 3: Compose
┌─────────────────────┐        ┌─────────────────────┐        ┌─────────────────────┐
│ LLM 生成剧本        │──→     │ ComfyUI 关键帧      │──→     │ ffmpeg 自动剪辑     │
│ (screenplay.json)   │        │ ComfyUI I2V 视频    │        │ 转场 + BGM + 字幕   │
│ Pydantic 校验+修复  │        │ (LTX/Wan 逐镜头)    │        │ → final.mp4         │
└─────────────────────┘        └─────────────────────┘        └─────────────────────┘
     screenplay.schemas              pipeline.keyframe/animate      pipeline.edit
```

- **扩展模块**: `mesh2video` — 3D 白模 → 深度/法线引导 → I2V 风格化（独立于主剧本管线）
- **工作流覆盖**: 内置 ComfyUI JSON 模板，用户可在 `workflows/` 目录放置同名文件覆盖
- **音频**: BGM 按情绪选择 (`audio/bgm.py`)，TTS 旁白为占位符 (`audio/tts.py`)

## 5. 技术栈总览

### 运行时依赖矩阵

| 依赖 | AIforPolkaDotsArt | GestureCoach | OilPaintingRevive | OilPaintingVideo |
|------|:-:|:-:|:-:|:-:|
| Python ≥ 3.11 | ✅ | ✅ | ✅ | ✅ |
| NumPy | ✅ | ✅ | ✅ | ✅ (可选) |
| OpenCV (cv2) | ✅ | ✅ | ✅ | — |
| SciPy | ✅ | ✅ | — | — |
| PyTorch | ✅ (ultralytics) | ✅ | ✅ (可选) | — |
| ultralytics (YOLO) | ✅ | — | ✅ (可选) | — |
| MediaPipe | — | ✅ (可选) | — | — |
| Pydantic v2 | — | — | ✅ | ✅ |
| httpx | — | — | ✅ | ✅ |
| FastAPI | — | ✅ | — | — |
| Click | — | — | ✅ | ✅ |
| PyYAML | — | — | ✅ | ✅ |
| ffmpeg | — | — | — | ✅ |
| ComfyUI (外部) | — | — | ✅ (可选) | ✅ (可选) |
| React + Vite | — | ✅ (前端) | — | — |

### GPU 需求

| 项目 | 是否需要 GPU | 说明 |
|------|:---:|------|
| AIforPolkaDotsArt | 基础版不需要，深度版需要 | 深度版需 CUDA + YOLO26 权重 |
| GestureCoach | 不需要 (原型) | 真实模型推理时需要 GPU |
| OilPaintingRevive | 不需要 (mock 模式) | 真实推理需 GPU + ComfyUI |
| OilPaintingVideo | 不需要 (mock 模式) | 真实生成需 GPU + ComfyUI |

## 6. 学术产出

| 项目 | 论文 | 目标会议 | 状态 |
|------|------|---------|------|
| AIforPolkaDotsArt | "Spatially-Aware Stippling" | IJCAI'26 Arts track | 草稿完成 (10pp) |
| GestureCoach | "GestureCoach" | CVPR | 草稿完成 |
| OilPaintingRevive | "Canvas3D" | IJCAI'26 | 草稿完成 (10pp) |
| OilPaintingVideo | "FamousPaintingVideoStyle" | IJCAI'26 | 草稿完成 |
