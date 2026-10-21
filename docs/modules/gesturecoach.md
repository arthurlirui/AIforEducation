# GestureCoach — 模块与文件参考

> **路径**: `GestureCoach/` ｜ **版本**: 0.1.0 ｜ **依赖**: Python ≥ 3.11, NumPy, SciPy, Pillow, PyTorch, torchvision, MediaPipe (可选), OpenCV, FastAPI, uvicorn, Pydantic, openai (可选), pytest

## 项目简介

GestureCoach 是一个面向绘画教育的**过程导向**技能评估系统。它不评估最终作品，而是分析绘画**过程**中的手势动态，形成一个闭环：艺术家技法表示 → 学习者偏差诊断 → 可执行的纠正反馈。

闭环管线: **追踪 → 特征提取 → (模板匹配) → DTW 诊断 → 反馈**

当前为原型阶段 (roadmap phase 2)：MediaPipe 和 LLM 均为可选，系统可在纯合成数据上离线运行，使用确定性规则引擎反馈。

## 文件结构

```
GestureCoach/
├── gesturecoach/               # 核心 Python 包
│   ├── __init__.py             # 包标记 + 版本号
│   ├── types.py                # 核心数据结构 (枚举 + dataclass)
│   ├── config.py               # 集中可调参数
│   ├── tracking.py             # 手部关键点提取 (MediaPipe)
│   ├── features.py             # 技法特征提取 (角度/轨迹/节奏)
│   ├── dtw.py                  # 改进 DTW + Procrustes MPJPE
│   ├── diagnosis.py            # 四轴偏差诊断
│   ├── feedback.py             # 反馈生成 (规则引擎 + LLM)
│   ├── template.py             # 技法模板库
│   ├── pipeline.py             # 端到端编排
│   ├── stages.py               # 绘画阶段识别 (ST-GCN + Bi-GRU)
│   ├── detection_types.py      # 检测/分割共享数据结构
│   ├── detection.py            # YOLOv5 画笔检测
│   ├── segmentation.py         # U-Net 手-笔分割
│   ├── toolhand.py             # 两阶段检测+分割管线
│   ├── synth.py                # 合成手部序列生成器
│   ├── synth_frame.py          # 合成 RGB 帧生成器
│   ├── synth_stages.py         # 合成阶段标注序列
│   └── api.py                  # FastAPI 服务 (REST + WebSocket)
├── frontend/                   # React + Vite 前端
│   └── src/
│       ├── App.jsx             # 主应用 (WebRTC + MediaPipe)
│       ├── FeedbackPanel.jsx   # 反馈面板
│       ├── diagnosisClient.js  # 诊断 API 客户端
│       ├── handTracking.js     # 手部追踪客户端逻辑
│       ├── skeletonOverlay.jsx # 骨架叠加渲染
│       ├── styles.css          # 样式
│       └── main.jsx            # 入口
├── data_collection/            # 数据采集与标注工具包
├── tests/                      # pytest 测试套件 (12+ 文件)
├── krita_plugins/              # Krita 插件 (油画风景 demo)
├── latex/                      # CVPR 论文 LaTeX
├── paper/                      # 论文 Markdown 草稿
├── requirements.txt            # Python 依赖
└── README.md                   # 项目说明
```

## 依赖关系图

```
                    ┌──────────────────────────────┐
                    │     GestureCoachPipeline      │
                    └──────────────────────────────┘
                                  │
  tracking → features → template → DTW → diagnosis → feedback
  (MediaPipe)  (角度/轨迹/节奏)  (模板库) (改进DTW)  (四轴偏差) (规则+LLM)
                                  │
              ┌───────────────────┴──────────────────┐
              │          并行视觉路径                 │
              │  detection_types → detection →        │
              │  segmentation → toolhand              │
              └──────────────────────────────────────┘
                                  │
                    stages (ST-GCN + Bi-GRU 或启发式)
                    (自动绘画阶段分割)
                                  │
                    api (FastAPI REST + WebSocket)
                    → frontend (React + WebRTC)
```

---

## 逐文件说明

### 核心管线模块

#### types.py — 核心数据结构

**职责**: 定义全模块共享的数据结构，保持管线解耦。

| 类型 | 说明 |
|------|------|
| `PaintingStage` (枚举) | sketch / block_in / detail |
| `Handedness` (枚举) | 左手 / 右手 |
| `Severity` (枚举) | good / minor / major |
| `FeedbackTone` (枚举) | rigid / elastic |
| `HandFrame` | 单帧手部数据 (关键点 + 置信度 + 时间戳) |
| `HandSequence` | 手部序列 (含 `landmarks_array` / `confidence_array` 属性) |
| `TrajectoryFeatures` | 笔尖轨迹特征 (速度/加速度/曲率) |
| `RhythmFeatures` | 节奏特征 (频谱能量/主频/谱质心) |
| `TechniqueFeatures` | 技法特征 (关节角度序列 + 轨迹 + 节奏) |
| `TechniqueTemplate` | 技法模板 (参考特征 + 统计量) |
| `Deviation` | 单轴偏差 (轴名/严重度/相似度/详情) |
| `DiagnosisResult` | 四轴诊断结果 |
| `FeedbackItem` | 单条反馈 |
| `FeedbackResult` | 反馈结果 (含可视化叠加) |

**被调用方**: 几乎所有其他模块

---

#### config.py — 集中可调参数

**职责**: 集中管理所有可调常量 (手部模型索引、DTW 权重、严重度阈值、姿态启发式、时间界限) 和运行时 `PipelineConfig` dataclass。

| 参数组 | 关键常量 |
|--------|---------|
| 手部模型 | `NUM_KEYPOINTS=21`, `WRIST`, `THUMB_TIP`, `INDEX_*`, `FINGER_CHAINS`, `BRUSH_TIP_KEYPOINT=INDEX_TIP` |
| DTW | `DTW_ALPHA=0.6`, `DTW_BETA=0.4` |
| 滑动窗口 | `DEFAULT_WINDOW_FRAMES=90`, `DEFAULT_STRIDE_FRAMES=15`, `TARGET_FPS=30` |
| 严重度 | `SEVERITY_GOOD=0.85`, `SEVERITY_MINOR=0.65` |
| 姿态阈值 | `GRIP_TOO_TIGHT_INDEX_PIP_DEG=95.0`, `WRIST_OVER_BEND_DEG=45.0` |
| 速度 | `TOO_FAST_SPEED=1.5`, `TOO_SLOW_SPEED=0.05` |
| `PipelineConfig` | dataclass (fps, 窗口/步长, DTW alpha/beta, 置信度阈值, `enable_llm_feedback`, `llm_model="gpt-4o"`, 每轴偏差阈值) |
| `DEFAULT_CONFIG` | 默认配置单例 |

---

#### tracking.py — 手部关键点提取

**职责**: 在视频上运行 MediaPipe Hands 提取手部关键点 (第 3.2 节)，通过时间插值 + 平滑处理遮挡，归一化关键点 (腕相对、尺度不变)。MediaPipe 延迟导入，原型无需摄像头即可运行。

| 组件 | 说明 |
|------|------|
| `HandTracker` 类 | `_ensure_mediapipe()` (支持旧版 `solutions.hands` 和新版 Tasks API，自动下载模型), `extract_from_video(...)`, `preprocess(seq)` (插值→平滑→归一化), `interpolate_occlusions(seq)`, `smooth_sequence(seq, kernel)`, `build_sequence(...)` |
| `normalize_landmarks(landmarks)` | 减去腕点，除以平均关键点距离 |

**被调用方**: `pipeline` (`HandTracker.preprocess`), `synth`/`template`/`diagnosis` (`build_sequence`, `normalize_landmarks`)

---

#### features.py — 技法特征提取

**职责**: 从 HandSequence 计算关节角度时间序列、笔尖轨迹 (速度/加速度/曲率) 和节奏 (FFT → PSD)。对应论文第 3.3 节。

| 函数 | 说明 |
|------|------|
| `compute_joint_angles(landmarks)` | 每指 PIP/DIP 关节角度 |
| `extract_joint_angle_series(seq)` | → dict[指 → (T,2)] |
| `extract_trajectory(seq)` | → `TrajectoryFeatures` |
| `extract_rhythm(trajectory, fps)` | → `RhythmFeatures` (Hann 窗 FFT) |
| `extract_features(seq)` | → `TechniqueFeatures` |

**被调用方**: `diagnosis` (学习者特征), `template` (艺术家特征+统计), `stages` (启发式回退)

---

#### dtw.py — 改进 DTW + Procrustes MPJPE

**职责**: 用于手部动作比较的改进 DTW + Procrustes MPJPE (第 3.4 节)。融合代价 `d(i,j) = α·‖l−r‖ + β·(1−cos)`。提供全矩阵和滑动窗口增量两种接口。

| 函数/类 | 说明 |
|---------|------|
| `improved_dtw(L, R, alpha, beta)` | → (归一化距离, 代价矩阵, 路径) |
| `procrustes_mpjpe(L, R, path)` | scipy Procrustes 对齐 + MPJPE |
| `dtw_similarity_score` | exp 映射到 [0,1] |
| `compare_sequences(L, R)` | 公共接口 |
| `IncrementalDTW` 类 | 滑动窗口实时 DTW |

**被调用方**: `diagnosis` 的 `diagnose_spatial` / `diagnose_direction`

---

#### diagnosis.py — 四轴偏差诊断

**职责**: 四轴偏差诊断 (第 3.4 节): 空间 (Procrustes MPJPE via DTW 路径)、姿态 (关节角度偏差 + 握笔过紧刚性启发式)、方向 (仅余弦 DTW on 运动向量)、时间 (速度分布 + 节奏能量)。

| 函数 | 说明 |
|------|------|
| `diagnose_spatial(...)` | Procrustes MPJPE 空间偏差 |
| `diagnose_posture(...)` | z-score vs 模板统计 + 握笔过紧检查 |
| `diagnose_direction(...)` | α=0 的 DTW on 帧间差分 |
| `diagnose_temporal(...)` | 速度 + 节奏能量, 过快/过慢标记 |
| `diagnose(learner, template, config)` | → `DiagnosisResult` (聚合四轴) |
| `_template_sequence(...)` | 从模板重建 HandSequence |

**被调用方**: `pipeline.run_offline` / `run_window`

---

#### feedback.py — 反馈生成

**职责**: 反馈生成 (第 3.5 节)。第一层: 确定性规则引擎，将偏差映射为中文指导，区分刚性/弹性。第二层: 可选 LLM (GPT-4o) 改写。强制支持性语言 ("可以尝试…" 而非 "你错了…")。

| 函数 | 说明 |
|------|------|
| `generate_rule_feedback(diagnosis, config)` | → `FeedbackResult` (含 `visual_overlay` 关节→颜色) |
| `build_llm_prompt(...)` | 构建 LLM 提示 |
| `generate_llm_feedback(...)` | LLM 改写，失败时回退到规则 |
| `generate_feedback(...)` | 公共入口，按 `enable_llm_feedback` 分派 |

---

#### template.py — 技法模板库

**职责**: 技法模板库 / 知识库 (第 3.3 节)。存储按阶段的艺术家参考模式 + 汇总统计。

| 组件 | 说明 |
|------|------|
| `build_template(seq, label)` | → `TechniqueTemplate` (提取特征, 计算每指 PIP/DIP 均值/标准差) |
| `TemplateLibrary` 类 | 内存字典, 按 `PaintingStage` 索引: `add`, `add_from_sequence`, `get`, `stages` |

---

#### pipeline.py — 端到端编排

**职责**: 将各模块串联成闭环 (第 3.1/3.6 节)。支持离线 (全序列) 和实时 (滑动窗口) 两种模式。

| 方法 | 说明 |
|------|------|
| `add_artist_sequence(seq, label)` | 预处理 + 存储模板 |
| `segment_stages(learner)` | 自动绘画阶段分割 |
| `run_offline(learner, stage)` | 全序列诊断 + 反馈 |
| `windows(learner)` | 滑动窗口生成器 |
| `run_window(window, stage)` | 单窗口诊断 |
| `run_realtime(learner)` | 流式处理 |

**被调用方**: `api.py`

---

#### api.py — FastAPI 服务

**职责**: 通过 HTTP/WebSocket 暴露管线，提供健康检查、模板注册、离线诊断、流式实时诊断和前端静态文件服务。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/templates` | POST | 注册艺术家模板 |
| `/diagnose` | POST | 离线诊断 |
| `/ws/realtime` | WS | 流式实时诊断 |
| `/` | GET | SPA 前端 (fallback) |

**运行**: `uvicorn gesturecoach.api:app --port 8000`

---

### 并行视觉路径模块

#### detection_types.py — 检测/分割共享数据结构

| 类型 | 说明 |
|------|------|
| `SegClass` (IntEnum) | BACKGROUND=0, HAND=1, BRUSH=2 |
| `BBox` | xyxy + 置信度/类别, 含 width/height/cx/cy/area/iou |
| `DetectionResult` | BBox 列表 + `best` 属性 |
| `SegmentationResult` | 掩码 + 概率图 + 裁剪框, 含 hand_ratio/brush_ratio |

#### detection.py — YOLOv5 画笔检测

**职责**: YOLOv5 风格的画笔检测 (第 2.1 节)，为下游 U-Net 分割提供初始边界框。包含可训练 PyTorch YOLO 模型和确定性启发式回退。

| 组件 | 说明 |
|------|------|
| `YOLOBrushNet` | 完整单类检测器 (CSP backbone + YOLO head) |
| `nms(...)`, `decode_predictions(...)` | NMS + 预测解码 |
| `YOLOBrushDetector` | 封装 (`from_pretrained` via torch.hub) |
| `HeuristicBrushDetector` | 阈值 + 连通组件，选最细长暗区域 |

#### segmentation.py — U-Net 手-笔语义分割

**职责**: 在 YOLO 检测到的画笔区域内，U-Net 分离画笔与手 (3 类: bg/hand/brush)，缓解遮挡 (第 2.1 节)。包含可训练 PyTorch U-Net + 启发式回退。

| 组件 | 说明 |
|------|------|
| `UNet` | 编码-解码, 4 下/上采样 + skip connection, base=16 |
| `UNetSegmenter` | 裁剪/缩放预处理, softmax + argmax, 双线性上采样回原分辨率 |
| `HeuristicSegmenter` | 强度 + 空间先验 (手=最大暖区域, 笔=最暗细长暗组件) |

#### toolhand.py — 两阶段检测+分割管线

**职责**: 编排 YOLO → U-Net，将裁剪局部掩码映射回全帧坐标，并通过掩码遮蔽画笔遮挡的关键点。

| 组件 | 说明 |
|------|------|
| `ToolHandPipeline` 类 | `run(image)` → (DetectionResult, 全帧 SegmentationResult) |
| `refine_hand_landmarks_with_mask(...)` | 将画笔掩码内的关键点设为 NaN 供下游插值 |

---

### 阶段识别模块

#### stages.py — 绘画阶段识别 (ST-GCN + Bi-GRU)

**职责**: 通过 Bi-GRU + ST-GCN 自动将录制分割为 sketch/block_in/detail (第 2.1/3.3 节)。包含可训练 PyTorch 模块 + 启发式回退。

| 组件 | 说明 |
|------|------|
| `STGCN` | 3 层时空图卷积 (骨架邻接 via FINGER_CHAINS) |
| `BiGRUHead` | 双向 GRU → 逐帧 logits |
| `StageNet` | ST-GCN → Bi-GRU |
| `StageRecognizer` | 封装: `predict`, `_smooth`, `segment` |
| `HeuristicStageSegmenter` | 基于速度/曲率统计: sketch=快/低曲率, detail=慢/高曲率 |

---

### 合成数据模块

#### synth.py — 合成手部序列生成器

**职责**: 为离线测试/demo 生成解剖学合理的 21 关键点手部序列，可控偏差 (握笔力度/速度/方向噪声)，给定种子确定性。

| 函数 | 说明 |
|------|------|
| `_make_pose(index_curl, ...)` | → 归一化 (21,3) 姿态 |
| `synthetic_hand_sequence(...)` | → `HandSequence` (沿正弦笔触动画) |

#### synth_frame.py — 合成 RGB 帧生成器

**职责**: 为检测/分割测试生成合成 RGB 帧 (手部椭圆 + 画笔暗矩形)。

| 函数 | 说明 |
|------|------|
| `synthetic_painting_frame(size, seed, brush_present)` | → (size,size,3) uint8 |
| `synthetic_painting_frame_mask(...)` | → 3 类真值掩码 |

#### synth_stages.py — 合成阶段标注序列

**职责**: 为 ST-GCN + Bi-GRU 训练/测试生成带阶段标注的合成序列，三段具有可区分的运动特征。

| 函数 | 说明 |
|------|------|
| `stage_labeled_sequence(total_frames, split, fps, seed, jitter)` | → (HandSequence, labels) |
| `make_dataset(n_samples, total_frames, seed_base)` | → list of (sequence, labels) |

---

## data_collection/ 目录

完整的、可直接执行的数据采集与标注工具包，涵盖 IRB 申请 → 艺术家录制 → 标注 → 摄入 → 学习者研究 → 专家评分 → 分析全流程。

| 文件 | 说明 |
|------|------|
| `01_IRB_application.md` | IRB 伦理审查申请 |
| `02_consent_artists.md` | 艺术家知情同意书 |
| `03_consent_learners.md` | 学习者知情同意书 |
| `04_data_collection_protocol.md` | 数据采集协议 |
| `05_annotation_guidelines.md` | 标注指南 |
| `06_user_study_protocol.md` | 用户研究协议 |
| `07_questionnaire.md` | 问卷 |
| `08_expert_scoring_rubric.md` | 专家评分标准 |
| `annotation_tool.py` | 标注工具 (关键点模式 + 阶段模式) |
| `ingest_videos.py` | 真实视频摄入管线 → 模板库 |
| `generate_demo_dataset.py` | 合成 demo 数据集生成 |
| `run_technical_evaluation.py` | 技术评估 (PCK/延迟/FPS/精确率) |

---

## 前端 (frontend/)

React 18 + Vite + MediaPipe Hands 的 Web 应用，提供实时摄像头手部追踪、骨架叠加和反馈面板。

| 文件 | 说明 |
|------|------|
| `App.jsx` | 主应用: getUserMedia 摄像头, MediaPipe Hands, 骨架叠加, 滑动窗口 (30帧/1秒, 步长15帧/0.5秒) 流式到 `/ws/realtime` |
| `FeedbackPanel.jsx` | 反馈面板组件 |
| `diagnosisClient.js` | 诊断 API 客户端 |
| `handTracking.js` | 手部追踪客户端逻辑 |
| `skeletonOverlay.jsx` | 骨架叠加渲染 |
| `styles.css` | 样式 |
| `main.jsx` | 入口 |

---

## 测试 (tests/)

| 文件 | 说明 |
|------|------|
| `conftest.py` | pytest 共享 fixtures |
| `test_api.py` | API 端点测试 |
| `test_detection.py` | 画笔检测测试 |
| `test_diagnosis_feedback.py` | 诊断+反馈测试 |
| `test_dtw.py` | DTW 测试 |
| `test_features.py` | 特征提取测试 |
| `test_integration_stages.py` | 阶段识别集成测试 |
| `test_integration_toolhand.py` | 工具-手管线集成测试 |
| `test_pipeline.py` | 管线测试 |
| `test_segmentation.py` | 分割测试 |
| `test_stages.py` | 阶段识别测试 |
| `test_tracking.py` | 追踪测试 |

**运行**: `pytest tests/`
