# 架构总览

## 1. Monorepo 定位

AIforEducation 是一个面向 **AI + 教育** 的研究型 monorepo，包含七个独立但主题相关的子项目。五个围绕"用 AI 技术辅助艺术创作与艺术教育"（波点艺术生成、油画动态化、油画教学平台、名画三维沉浸教学、绘画手势教练），HistorySandbox 把同一思路推广到历史教育沙盘推演，TechLearnStudio 则推广到"用 AI 辅助人类快速学习新技术与专业课"。

## 2. 子项目一览

| 子项目 | 核心目标 | 技术栈 | 语言 | 测试 |
|--------|---------|--------|------|------|
| **DotArtKit** | 统一波点艺术生成器：8 种流派（点彩/Ben-Day/欧普/点绘/叶序/草间弥生基础+深度感知/可学习映射）+ 桌面波点编辑器 GUI（tkinter） | Weighted Voronoi Stippling, YOLO26 (深度+语义分割), NumPy, SciPy(可选), PyTorch(可选), tkinter | Python | pytest (80 项) |
| **OilPaintingStudio** | 油画动态生成统一包：video（剧本→关键帧→I2V→剪辑）+ revive/Canvas3D（单画→分割→3DGS→线稿重排→动画）+ GUI 工作站（FastAPI+Vue3+Three.js）+ pywebview 桌面论文 Demo | OpenAI-compatible LLM, ComfyUI (LTX/Wan + ControlNet), YOLO, Depth Anything V2, TripoSplat 3DGS, Pydantic, ffmpeg | Python + JavaScript | pytest (85 项, mock 全链路) |
| **OilPaintingPlatform** | 油画教学 + AI 文生图网站：12 风格 + 28 提示词模板 + 6 视觉大模型 | FastAPI, Vue 3, Pinia, Provider 注册表抽象 | Python + JavaScript | pytest (21 项) |
| **ArtRealm3D** | 艺境：世界名画三维沉浸式教学平台——程序化分层渲染（零图片依赖）+ 章节式导览 + 测验闭环 | FastAPI, Vue 3, Three.js, numpy/PIL 程序化渲染 | Python + JavaScript | pytest (22 项) |
| **HistorySandbox** | 读史：AI 历史教育三维沙盘推演平台——4 剧本 × 6 幕 + 世界模型交互推演（机动/进攻/结盟/假想）+ AI 讲解 | FastAPI, Vue 3, Three.js, 规则动力学 + LLM 可选回退 | Python + JavaScript | pytest (27 项) |
| **TechLearnStudio** | 读取技术文档/讲义，自动生成 hyperframes 可交互网页 PPT + 动画，支持定时自动上新 | FastAPI, SQLModel, Vue 3, reveal.js, SVG/SMIL 动画, APScheduler, LLM | Python + JavaScript | pytest (46 项含 e2e) |
| **GestureCoach** | 分析绘画过程中的手势动态，诊断学习者与艺术家技法的偏差，给出纠正反馈（v4：手势指令管线 GLM+规则双层） | MediaPipe Hands, DTW + Procrustes, FastAPI, React, Krita 插件 | Python + JavaScript | pytest (332 项) |

> 子项目沿革：DotArtKit 由原 `AIforPolkaDotsArt` + `AIforDotArt` 整合而来；OilPaintingStudio 由原 `OilPaintingVideo` + `OilPaintingRevive` 整合而来；GestureCoach 是独立仓库（submodule）。

## 3. 项目间关系

```
                    ┌───────────────────────────────────────────────────────┐
                    │                AIforEducation Monorepo                │
                    └─────────────────────────────┬─────────────────────────┘
                                                  │
   ┌───────────┬───────────────┬──────────┬──────┴─────┬──────────────┬─────────────┐
   │           │               │          │            │              │             │
DotArtKit  OilPaintingStudio  OilPainting  ArtRealm3D  HistorySandbox  TechLearn  GestureCoach
(风格化图像  (video+revive:   Platform    (名画三维    (历史三维       Studio     (过程评估
 生成+编辑器) 剧本→3DGS→动画  (教学网站+  沉浸导览+    沙盘推演+      (技术学习    反馈+Krita)
             +GUI 工作站)    文生图)     测验闭环)     世界模型)      hyperframes)
```

### 3.1 共享资源

- **`images/`** — 18 张经典油画高清扫描（达芬奇、梵高、西斯莱等），被 OilPaintingStudio、DotArtKit 等用作输入素材
- **`models/`** — 共享模型权重（YOLO 深度/分割等，多个子项目引用）
- **`latex/`** — IJCAI 论文 LaTeX 模板及历史论文源码，被多个子项目的 `paper/` 或 `latex/` 子目录引用
- **`GestureCoach/`** — git submodule（独立仓库 `github.com/arthurlirui/GestureCoach`），clone 后需 `git submodule update --init`

### 3.2 技术交叉点

| 技术 | 涉及项目 | 说明 |
|------|---------|------|
| YOLO (ultralytics) | DotArtKit, OilPaintingStudio | 前者用于深度估计+语义分割，后者用于多目标分割 |
| ComfyUI HTTP API | OilPaintingStudio (video + revive) | 统一 async ComfyClient 封装（`common/comfy/client.py`），支持 /free 显存释放 |
| Pydantic v2 | OilPaintingStudio, ArtRealm3D, HistorySandbox, OilPaintingPlatform | 阶段间/帧数据的类型安全传递 |
| OpenCV (cv2) | DotArtKit, OilPaintingStudio, GestureCoach | 图像处理基础工具 |
| FastAPI + Vue 3 + Three.js | OilPaintingStudio (GUI), ArtRealm3D, HistorySandbox | 三套前后端分离 + 三维可视化 Web 应用 |
| LLM (OpenAI-compatible) | OilPaintingStudio, TechLearnStudio, GestureCoach, OilPaintingPlatform, HistorySandbox | 剧本/课程/反馈/提示词/反事实推演合成，均带本地规则回退 |
| 程序化渲染 (numpy+PIL) | DotArtKit, ArtRealm3D | 无 GPU 的确定性图像合成（波点/分层画层） |

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

### 4.5 ArtRealm3D — 程序化分层渲染 + 章节叙事

```
知识库 (风格处方: palette + 几何语义)
   → renderer 程序化渲染 (numpy+PIL, 确定性, 零外部图片)
   → assets 签名缓存 (data/generated/mid/sig/)
   → Three.js 分层视差场景 (呼吸微动 + 指针环视)
   → 章节叙事驱动镜头 (进入画中→构图→背景→精神内核→尾声)
   → 测验闭环 (后端判分 + 逐题解析; 答案不下发客户端)
```

- **设计哲学**: 风格化抽象而非原画复刻——全部画层程序化生成，部署零图片资产
- **教学闭环**: 导览自动衔接学习检验，判分后逐题解析

### 4.6 HistorySandbox — 世界模型交互推演

```
剧本 JSON (4 剧本 × 6 幕: 疆域/路线/战役/讲解)
   → Three.js 低多边形沙盘 (经纬度→世界坐标 + 射线拾取)
   → 步进播放 + AI 讲解员 (LLM 可选, 本地引擎回退)
   → 世界模型交互推演: move/attack/retreat/alliance/hypothetical
   → 模拟步 (✦ 假想标记, id=900+ 哨兵) 增量应用回沙盘
```

- **设计哲学**: 像沙盘游戏一样"看"历史——过程可视 + 可干预 + 后果即时可见
- **反事实推演**: hypothetical 模式由 LLM 生成多分支推演（本地规则引擎回退），标注非史实

### 4.7 GestureCoach — 闭环管线

```
tracking → features → template → DTW → diagnosis → feedback
(MediaPipe)  (角度/轨迹/节奏)  (模板库)  (改进DTW)  (四轴偏差)  (规则+LLM 双通道)
        + knowledge_base / fused_diagnosis / concept / master_styles
        + classroom(课堂管理) / artwork_archive / Krita 插件
        + v4 手势指令管线 (gesture_command: GLM+规则双层, gesture_yolo 几何 fallback)
```

- **设计哲学**: 过程导向而非结果导向——评估绘画"怎么画"而非"画得怎样"
- **原型策略**: MediaPipe 和 LLM 都是可选的，系统可在纯合成数据上离线运行
- **研究状态**: demo 数据为合成；论文 18 处 TBD 待真实用户研究（IRB 审批中）

## 5. 技术栈总览

### 运行时依赖矩阵

| 依赖 | DotArtKit | OilPaintingStudio | OilPaintingPlatform | ArtRealm3D | HistorySandbox | TechLearnStudio | GestureCoach |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Python ≥ 3.11 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| NumPy | ✅ | ✅ | — | ✅ | — | — | ✅ |
| OpenCV (cv2) | ✅ | ✅ | — | — | — | — | ✅ |
| SciPy | 可选 | — | — | — | — | — | ✅ |
| PyTorch | 可选 | 可选 | — | — | — | — | ✅ |
| ultralytics (YOLO) | 可选 | 可选 | — | — | — | — | 可选 |
| MediaPipe | — | — | — | — | — | — | 可选 |
| Pydantic v2 | — | ✅ | ✅ | ✅ | ✅ | — (SQLModel) | ✅ |
| httpx | — | ✅ | — | — | ✅ | ✅ | — |
| FastAPI | — | GUI | ✅ | ✅ | ✅ | ✅ | ✅ |
| Vue 3 / React | — | Vue (GUI) | Vue | Vue | Vue | Vue | React |
| Three.js | — | GUI | — | ✅ | ✅ | — | — |
| ffmpeg | — | ✅ | — | — | — | — | — |
| ComfyUI (外部) | — | 可选 | — | — | — | — | — |

### GPU 需求

| 项目 | 是否需要 GPU | 说明 |
|------|:---:|------|
| DotArtKit | 基础模式不需要 | kusama_depth / learned 需 GPU + 权重 |
| OilPaintingStudio | mock 模式不需要 | 真实推理需 GPU + ComfyUI；桌面 Demo 三档回退 gpu→cpu→mock |
| OilPaintingPlatform | 不需要 | 图像生成调用云端 API |
| ArtRealm3D | 不需要 | 程序化渲染纯 CPU |
| HistorySandbox | 不需要 | 规则动力学 + LLM 云端/本地回退 |
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
