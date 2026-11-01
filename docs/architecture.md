# 架构总览

## 1. Monorepo 定位

AIforEducation 是一个面向 **AI + 教育** 的研究型 monorepo，包含五个独立但主题相关的子项目。四个围绕"用 AI 技术辅助艺术创作与艺术教育"（波点艺术生成、油画动态化、油画教学平台、绘画手势教练），TechLearnStudio 则把同一思路推广到"用 AI 辅助人类快速学习新技术与专业课"。

## 2. 子项目一览

| 子项目 | 核心目标 | 技术栈 | 语言 | 测试 |
|--------|---------|--------|------|------|
| **DotArtKit** | 统一波点艺术生成器：8 种流派（点彩/Ben-Day/欧普/点绘/叶序/草间弥生基础+深度感知/可学习映射） | Weighted Voronoi Stippling, YOLO26 (深度+语义分割), NumPy, SciPy(可选), PyTorch(可选) | Python | scripts/run_demos.py 冒烟 |
| **OilPaintingStudio** | 油画动态生成统一包：video（剧本→关键帧→I2V→剪辑）+ revive/Canvas3D（单画→分割→3DGS→线稿重排→动画） | OpenAI-compatible LLM, ComfyUI (LTX/Wan + ControlNet), YOLO, Depth Anything V2, TripoSplat 3DGS, Pydantic, ffmpeg | Python | pytest (58 项, mock 全链路) |
| **OilPaintingPlatform** | 油画教学 + AI 文生图网站：12 风格 + 28 提示词模板 + 6 视觉大模型 | FastAPI, Vue 3, Pinia, Provider 注册表抽象 | Python + JavaScript | 待补 |
| **TechLearnStudio** | 读取技术文档/讲义，自动生成 hyperframes 可交互网页 PPT + 动画，支持定时自动上新 | FastAPI, SQLModel, Vue 3, reveal.js, SVG/SMIL 动画, APScheduler, LLM | Python + JavaScript | pytest (43 项含 e2e) |
| **GestureCoach** | 分析绘画过程中的手势动态，诊断学习者与艺术家技法的偏差，给出纠正反馈 | MediaPipe Hands, DTW + Procrustes, FastAPI, React, Krita 插件 | Python + JavaScript | pytest (284 项) |

> 子项目沿革：DotArtKit 由原 `AIforPolkaDotsArt` + `AIforDotArt` 整合而来；OilPaintingStudio 由原 `OilPaintingVideo` + `OilPaintingRevive` 整合而来；GestureCoach 是独立仓库（submodule）。

## 3. 项目间关系

```
                    ┌──────────────────────────────────────────────┐
                    │           AIforEducation Monorepo            │
                    └──────────────────────┬───────────────────────┘
                                           │
    ┌──────────────┬──────────────┬────────┴─────────┬──────────────┐
    │              │              │                  │              │
 DotArtKit   OilPaintingStudio  OilPaintingPlatform TechLearnStudio GestureCoach
 (风格化图像  (video: 剧本→油画   (教学网站+         (技术学习       (过程评估
  生成)       视频; revive:      文生图)            hyperframes)    反馈+Krita)
              单画→3DGS→动画)
```

### 3.1 共享资源

- **`images/`** — 18 张经典油画高清扫描（达芬奇、梵高、西斯莱等），被 OilPaintingStudio、DotArtKit 等用作输入素材
- **`latex/`** — IJCAI 论文 LaTeX 模板及历史论文源码，被多个子项目的 `paper/` 或 `latex/` 子目录引用
- **`GestureCoach/`** — git submodule（独立仓库 `github.com/arthurlirui/GestureCoach`），clone 后需 `git submodule update --init`

### 3.2 技术交叉点

| 技术 | 涉及项目 | 说明 |
|------|---------|------|
| YOLO (ultralytics) | DotArtKit, OilPaintingStudio | 前者用于深度估计+语义分割，后者用于多目标分割 |
| ComfyUI HTTP API | OilPaintingStudio (video + revive) | 统一 async ComfyClient 封装（`common/comfy/client.py`），支持 /free 显存释放 |
| Pydantic v2 | OilPaintingStudio, TechLearnStudio | 阶段间/帧数据的类型安全传递 |
| OpenCV (cv2) | DotArtKit, OilPaintingStudio, GestureCoach | 图像处理基础工具 |
| FastAPI + Vue 3 | OilPaintingPlatform, TechLearnStudio, GestureCoach(前端为 React) | 三套前后端分离 Web 应用 |
| LLM (OpenAI-compatible) | OilPaintingStudio, TechLearnStudio, GestureCoach, OilPaintingPlatform | 剧本/课程合成/反馈生成/提示词增强，均带降级路径 |

## 4. 各项目架构要点

### 4.1 DotArtKit — 算子分层

```
dotartkit/
├── ops/        底层算子: voronoi(Lloyd 可选), depth(YOLO26), 形变场, 采样
├── styles/     8 个流派渲染器: seurat/benday/warp/stipple/vogel/
│               kusama_basic/kusama_depth/learned
├── api.py      MODES 注册表 → generate() 统一入口
└── cli.py      dotart list / generate / demo
```

- **依赖分级**: scipy/ultralytics/torch 全部可选，缺省时退化或给出清晰 ImportError
- **深度感知版** (kusama_depth): 需 GPU + YOLO26 权重，三层架构 + 语义双色

### 4.2 OilPaintingStudio — 两条管线共享 common

```
oilpainting_studio/
├── common/     config(LLM/ComfyUI 连接), llm_client, comfy(ComfyClient+工作流模板), utils
├── video/      screenplay(LLM 剧本) → pipeline(keyframe/animate/edit) → audio(BGM/TTS)
│               └── mesh2video (3D 白模→深度/法线引导 I2V, 独立扩展)
└── revive/     config(独立 revive_settings.yaml) + pipeline(director/checkpoint)
    └── stage1..stage5: YOLO 分割 → TripoSplat 3DGS → 线稿重排 → 关键帧 → ComfyUI 动画
```

- **设计哲学**: 每个外部依赖（YOLO/TripoSplat/ComfyUI/LLM）都有确定性 mock 回退，全流程可在无 GPU 环境下运行测试
- **数据契约**: Pydantic 模型 (`Stage1Output` → `Stage4Output`) 保证阶段间类型安全
- **检查点**: `meta.json` 记录每阶段完成状态，支持断点续跑
- **CLI**: `oilpaint-video` (generate/render/compose/full) + `oilpaint-revive` (health/run)

### 4.3 OilPaintingPlatform — Provider 注册表

```
backend/app/
├── routers/    health/styles/teaching/gallery/prompts/providers/generate
├── services/   providers/(mock/pollinations/openai/dashscope/zhipu/sdwebui)
│               prompt_builder(提示词合成引擎)
└── data/       styles.json / teaching.json / prompts.json / gallery.json
frontend/src/   6 页面 (Home/Create/Teaching/Article/Gallery/About) + 3 组件
```

- **Provider 抽象**: `ImageProvider` 基类 + `ProviderRegistry`，缺 API Key 自动回退 mock，前端可传 per-request 凭据（不落盘）

### 4.4 TechLearnStudio — 三模块架构

```
Studio(生产者)  → crawler(7 内容源) → composer(LLM+规则) → anim_gen(SVG/SMIL) → publish
Backend(仓库)   → FastAPI + SQLModel: 课程/帧 CRUD, 静态托管, sandbox(占位), 搜索(内存)
Frontend(播放)  → Vue 3 + reveal.js + 自研 hyperframes 插件
```

- **内容覆盖**: Python/Rust/Go/TS + 信号处理/无线通信/大模型专业课
- **已知边界**: sandbox 执行为 stub（回显不执行）；reveal.js/highlight 为 CDN 动态加载

### 4.5 GestureCoach — 闭环管线

```
tracking → features → template → DTW → diagnosis → feedback
(MediaPipe)  (角度/轨迹/节奏)  (模板库)  (改进DTW)  (四轴偏差)  (规则+LLM 双通道)
        + knowledge_base / fused_diagnosis / concept / master_styles
        + classroom(课堂管理) / artwork_archive / Krita 插件
```

- **设计哲学**: 过程导向而非结果导向——评估绘画"怎么画"而非"画得怎样"
- **原型策略**: MediaPipe 和 LLM 都是可选的，系统可在纯合成数据上离线运行
- **研究状态**: demo 数据为合成；论文 18 处 TBD 待真实用户研究（IRB 审批中）

## 5. 技术栈总览

### 运行时依赖矩阵

| 依赖 | DotArtKit | OilPaintingStudio | OilPaintingPlatform | TechLearnStudio | GestureCoach |
|------|:-:|:-:|:-:|:-:|:-:|
| Python ≥ 3.11 | ✅ | ✅ | ✅ | ✅ | ✅ |
| NumPy | ✅ | ✅ | — | — | ✅ |
| OpenCV (cv2) | ✅ | ✅ | — | — | ✅ |
| SciPy | 可选 | — | — | — | ✅ |
| PyTorch | 可选 | 可选 | — | — | ✅ |
| ultralytics (YOLO) | 可选 | 可选 | — | — | 可选 |
| MediaPipe | — | — | — | — | 可选 |
| Pydantic v2 | — | ✅ | ✅ | — (SQLModel) | ✅ |
| httpx | — | ✅ | — | ✅ | — |
| FastAPI | — | — | ✅ | ✅ | ✅ |
| Vue 3 / React | — | — | Vue | Vue | React |
| ffmpeg | — | ✅ | — | — | — |
| ComfyUI (外部) | — | 可选 | — | — | — |

### GPU 需求

| 项目 | 是否需要 GPU | 说明 |
|------|:---:|------|
| DotArtKit | 基础模式不需要 | kusama_depth / learned 需 GPU + 权重 |
| OilPaintingStudio | mock 模式不需要 | 真实推理需 GPU + ComfyUI |
| OilPaintingPlatform | 不需要 | 图像生成调用云端 API |
| TechLearnStudio | 不需要 | LLM 调用云端 API |
| GestureCoach | 原型不需要 | 真实检测/分割模型推理时需要 |

## 6. 学术产出

| 项目 | 论文 | 目标会议 | 状态 |
|------|------|---------|------|
| DotArtKit | "Spatially-Aware Stippling" | IJCAI'26 Arts track | 10pp 稿完成 |
| OilPaintingStudio | "Canvas3D" | IJCAI'26 主会 | 10pp 稿完成（figures_preview 30 个图表变体待挑选集成） |
| OilPaintingStudio | "InkFlow" (水墨视频扩散) | IJCAI 2027 | 早期框架稿 |
| GestureCoach | "GestureCoach" | IJCAI 2027 | 80%，待 IRB + 真实用户研究 |

详细投稿时间表见 [IJCAI2027_submission_status.md](IJCAI2027_submission_status.md)。
