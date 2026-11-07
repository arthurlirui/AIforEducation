# OilPaintingStudio — 模块与文件参考

> **路径**: `OilPaintingStudio/` ｜ **版本**: 1.1.0 ｜ **依赖**: Python ≥ 3.11, httpx, pyyaml, pillow, python-dotenv, click, pydantic, numpy, opencv-python-headless（核心）；ComfyUI / LLM API / ffmpeg / torch（外部，可选，均有 mock 降级）｜ **测试**: pytest 85 项全绿

## 项目简介

经典油画动态艺术生成统一项目，整合两条互补管线 + GUI 工作站 + 桌面论文 Demo + 三份论文初稿：

1. **video**（原 OilPaintingVideo）— LLM 剧本 → ComfyUI 油画关键帧 → I2V 视频 (LTX/Wan2.2) → ffmpeg 自动剪辑
2. **revive**（原 OilPaintingRevive，即 IJCAI 论文 Canvas3D）— 单幅油画 → YOLO 分割 + 深度 → TripoSplat 3DGS → 线稿引导重排 → 关键帧 → ComfyUI ControlNet 动画
3. **gui**（2026-11-04 新增）— 画作物体级三维编辑工作站：FastAPI 服务端 + Vue3/Three.js 前端五步工作台（分割审校 → 3DGS → 场景组装 → 关键帧线稿 → 合成）
4. **desktop**（2026-11-04 新增）— pywebview 桌面论文 Demo：Canvas3D 管线浓缩为一键三步演示（分割→深度→3D 化身），GPU/CPU/MOCK 三档设备自动回退

两管线共享 `common/`（配置、LLM 客户端、ComfyClient、工具函数）。每个外部依赖都有确定性 mock 回退，全流程可在无 GPU/ComfyUI 环境下测试。

## 文件结构

```
OilPaintingStudio/
├── oilpainting_studio/
│   ├── common/                 # 两管线共享
│   │   ├── config.py           # video 管线 Settings + styles.yaml 加载
│   │   ├── llm_client.py       # OpenAI-compatible LLM 客户端 (mock 降级)
│   │   ├── comfy/
│   │   │   ├── client.py       # async ComfyClient: 排队/轮询/下载/upload/free_memory
│   │   │   └── workflows.py    # JSON 工作流模板加载 + 参数注入
│   │   └── utils/              # ffmpeg_tool / image / vram
│   ├── video/                  # 管线 1: 剧本驱动短片
│   │   ├── cli.py              # oilpaint-video CLI (generate/render/compose/full)
│   │   ├── screenplay/         # LLM 剧本生成 + Pydantic 校验修复
│   │   ├── pipeline/           # director(编排)/keyframe/animate/edit(ffmpeg)
│   │   ├── audio/              # bgm(按情绪) / tts(占位 TODO)
│   │   └── mesh2video/         # 3D 白模→深度/法线→I2V (独立扩展)
│   ├── revive/                 # 管线 2: Canvas3D 四模块
│   │   ├── cli.py              # oilpaint-revive CLI (health/run)
│   │   ├── config.py           # revive Settings (revive_settings.yaml)
│   │   ├── schemas.py          # Stage1-4Output / ProjectMeta 数据契约
│   │   ├── eval.py             # 评估钩子 (风格一致性/边缘对齐/深度忠实)
│   │   ├── pipeline/           # director(四模块编排) + checkpoint(断点续跑)
│   │   ├── stage1/             # PaintParse: YOLO 分割 + DA-V2 深度 + 控制线稿
│   │   ├── stage2/             # MonoSplat: TripoSplat 3DGS + 2DGS 背景 + 组装
│   │   ├── stage3/             # SketchComp: 线稿解析 + 重定位 + 修复
│   │   ├── stage4/             # 多视角关键帧渲染
│   │   └── stage5/             # ArtiFlow: Wan/LTX + ControlNet 动画 (mock 降级)
│   ├── gui/                    # 三维编辑工作站服务端 (2026-11-04 新增)
│   │   ├── models.py           # ProjectMeta/ObjectMeta/UndoEntry/SceneGraph/KeyframeMeta
│   │   ├── store.py            # 项目仓库: 原子写 (tmp+rename), undo 栈, 项目列表
│   │   ├── tasks.py            # GPU 长任务队列 (后台线程 + 进度 + 取消)
│   │   ├── adapters.py         # GUI ↔ revive 管线适配 (SegmentedObject 组装等)
│   │   ├── imgio.py            # 中文路径安全图像读写 (PIL 回退 cv2)
│   │   ├── server.py           # FastAPI app + 前端静态托管 (端口 8710)
│   │   └── api/routers.py      # 项目/物体/场景/关键帧/任务 REST 端点
│   └── desktop/                # 桌面论文 Demo (2026-11-04 新增)
│       ├── __main__.py         # py -m oilpainting_studio.desktop 入口
│       ├── api.py              # 7 端点: 设备探测/三步演示/基准计时/运行历史
│       ├── device.py           # GPU→CPU→MOCK 三档探测与回退 (DeviceReport/resolve_choice)
│       └── engine.py           # 三步演示引擎 (分割→深度→3D 化身, 每步计时)
├── gui/                        # 工作站前端 (Vite + Vue3 + Three.js)
│   └── src/
│       ├── App.vue             # 五步工作台 + 步骤栏 + Demo 页签
│       ├── three.js            # Three.js 场景封装 (视口+gizmo+PLY 加载)
│       └── components/         # ProjectHome/Segment/Gs/Scene/Keyframe/Compose/Demo 七视图
├── config/                     # settings.yaml(video) / revive_settings.yaml / styles.yaml / mesh2video.yaml
├── workflows/                  # 用户自定义 ComfyUI 工作流覆盖目录
├── projects/                   # 示例项目 (山水风景全流程 + _demo 星月夜)
├── tests/                      # 85 项 pytest (mock 全链路)
├── paper/                      # Canvas3D(IJCAI'26) + survey + InkFlow
├── images/ + assets/           # 名画测试图 + 5 幅 demo 素材
└── scripts/ + tools/           # 辅助脚本
```

## 管线数据流

```
video:  screenplay.schemas → pipeline.director → keyframe → animate → edit → final.mp4
revive: Stage1Output → Stage2Output → Stage3Output → Stage4Output (Pydantic 契约)
        checkpoint.meta.json 记录各阶段完成状态, 支持断点续跑
gui:    前端七视图 → REST(/api/projects...) → store(原子写) → tasks(GPU 队列)
        → adapters → revive 管线真跑 → PLY 版本翻版 (object_XX_label.vN.ply)
desktop: probe_device(三档) → engine 三步(每步计时+档位标注) → 前端 DemoView 展示
```

---

## 逐文件说明（关键模块）

### common/config.py — video 配置

**职责**: `.env`（密钥）+ `settings.yaml`（画幅/模型名/剪辑参数）+ `styles.yaml`（风格预设）合并为 `Settings` dataclass。`comfy_url` 属性、`style()` 查询。

### common/comfy/client.py — ComfyClient

**职责**: 异步 ComfyUI HTTP 客户端：`queue_prompt`（排队）→ `get_history`（轮询）→ `download_view`（下载）；`upload_image`/`upload_video`（上传）、`free_memory`（/free 释放显存，失败仅告警）、`run`（端到端）、`health`（探测）。

### common/llm_client.py — LLM 客户端

**职责**: OpenAI-compatible chat API 封装，失败时降级为本地 mock 剧本生成。

### revive/config.py — revive 配置

**职责**: revive 四模块独立 `Settings`（YOLO/深度/3DGS/重排/动画参数），读 `config/revive_settings.yaml`。`depth_range_for()` 按物体类别返回深度范围。与 video 的 Settings 字段不同名，故独立成模块。

### revive/schemas.py — 数据契约

**职责**: Pydantic v2 模型：`SegmentedObject`、`GSModelRegistry`、`Stage1Output`~`Stage4Output`、`RepositionTransform`、`KeyframeSpec`、`ProjectMeta`（含 `mark_stage` 状态机）。

### revive/pipeline/director.py — 四模块编排器

**职责**: `run_pipeline()` 串联 stage1→5，各阶段后写检查点、释放显存；断点续跑时从检查点反序列化各 Stage 输出（`_load_stage1/2/3`）。完成后跑 `eval.py` 评估钩子（失败不影响主流程）。

### revive/pipeline/checkpoint.py — 检查点

**职责**: `new_project`/`init_meta`/`mark_stage`/`get_completed_stage`，meta.json 持久化。

### revive/stage1/ — PaintParse

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_stage1()` 入口：分割 + 深度 + 背景分离 + 控制线稿解析 |
| `segment.py` | `segment_with_yolo()`（ultralytics 可选）+ `segment_mock()`（颜色聚类连通域）；YOLO 检出 0 物体时降级 mock |
| `depth.py` | Depth Anything V2 深度估计，不可用时 mock 深度 |
| `parse_control.py` | 手绘线稿解析（物体轮廓 + 关键帧指引） |

### revive/stage2/ — MonoSplat

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_stage2()` 入口 |
| `triposplat.py` | 单图→3DGS（TripoSplat 集成，仓库路径可选；缺省 mock PLY） |
| `gs2d_init.py` | 2DGS 背景 surfel 初始化；`surfels_to_ply`/`load_surfels_from_ply` |
| `assemble.py` | 物体 3DGS + 背景 2DGS 场景组装 |

### revive/stage3/ — SketchComp

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_stage3()` 入口 |
| `lineart_parse.py` | 线稿二值化与解析 |
| `reposition.py` | 线稿引导的 3DGS 重定位（边缘对齐迭代优化） |
| `inpaint.py` | 孔洞修复（telea/ns） |

### revive/stage4/ — 关键帧渲染

**职责**: 从编辑后场景渲染多视角关键帧 RGB/深度/边缘三路图。

### revive/stage5/ — ArtiFlow

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_stage5()`：ComfyUI 真实路径（`generate_with_comfyui`）失败降级 `generate_mock`（关键帧插值成视频） |
| `workflow.py` | Wan2.2 / LTX2.3 ControlNet（深度+边缘）工作流构造 |

### video/screenplay/ — LLM 剧本

| 文件 | 职责 |
|------|------|
| `schemas.py` | `Script`/`Scene`/`Shot` Pydantic 模型（时长自动重算） |
| `generator.py` | `generate_script()`：LLM 生成 + JSON 解析重试 + `_repair_shot_numbering` 修复 |
| `prompts.py` | 剧本生成提示词模板 |

### video/pipeline/ — video 编排

| 文件 | 职责 |
|------|------|
| `director.py` | `run_full()` 端到端 + `stage_generate/render/compose` 分步 + 项目目录管理 |
| `keyframe.py` | ComfyUI img2img 油画关键帧工作流构造 |
| `animate.py` | LTX/Wan I2V 视频片段工作流构造 |
| `edit.py` | ffmpeg 剪辑：转场 xfade + BGM + 字幕烧录 |
| `ffmpeg_tool.py` | ffmpeg 解析与调用封装 |

### video/mesh2video/ — 3D 白模风格化扩展

**职责**: `Camera`/`orbit_camera`（相机轨道）、`WhiteMeshRenderer`（深度/法线/RGB 三路渲染）、`MorphDriver`/`StaticDriver`（动画驱动）、`Mesh2VideoPipeline`（深度/法线引导 I2V）。独立于主剧本管线，需 trimesh（extras）。

### gui/ — 三维编辑工作站服务端 (2026-11-04 新增)

| 文件 | 职责 |
|------|------|
| `models.py` | Pydantic v2 全套模型：ProjectMeta（pipeline_state 五阶段状态机）/ ObjectMeta（含 mask_version、gs_version 审校扩展字段）/ UndoEntry / SceneGraph（Transform/CameraRig）/ KeyframeMeta |
| `store.py` | 项目仓库：project.json + objects/*/meta.json + scene.json + keyframes.json；**原子写**（tmp+rename）；undo 栈（JSON 记 before/after、位图记快照路径）；PLY 版本翻版不覆盖旧版 |
| `tasks.py` | GPU 长任务后台队列：单工作线程 + 进度/日志/取消标志，避免阻塞 FastAPI |
| `adapters.py` | GUI 元数据 ↔ revive 管线适配：ObjectMeta → SegmentedObject 组装、场景导出 |
| `imgio.py` | 中文路径安全图像读写（cv2 失败回退 PIL——Windows cv2 不读中文路径，全仓已知坑） |
| `server.py` | FastAPI app：挂 api 路由 + 前端静态托管；PROJECTS_ROOT 指向仓库根 projects/；根路径自动重定向到前端 |
| `api/routers.py` | REST 端点：项目 CRUD/列表、物体查改（rejected/depth_range/color/label）、掩码、场景图、关键帧、任务提交与轮询 |

> 踩坑记录: PUT 物体接口 `model_copy` 不校验——列表 depth_range 需手工转元组，否则 pydantic 序列化警告（2026-11-08 修复）。

### desktop/ — 桌面论文 Demo (2026-11-04 新增)

| 文件 | 职责 |
|------|------|
| `device.py` | `probe_device()` 三档探测（torch+CUDA → GPU；torch → CPU；否则 MOCK），`resolve_choice()` 解析用户偏好并如实上报回退原因；Benchmark 推理计时 |
| `engine.py` | 三步演示引擎：分割（YOLO/K-Means 聚类）→ 深度（DA-V2/梯度）→ 3D 化身（点云着色），每步计时 + 档位标注 |
| `api.py` | 7 端点：system info / 三步演示 / benchmark / 运行历史（GPU 2449ms vs mock 59ms 对照） |
| `__main__.py` | pywebview 窗口（复用 gui 前端 DemoView），端口 8712 |

> 踩坑记录: `resolve_choice` 的 auto 映射、pywebview IAB `evaluate_js` 超时需拆步、api.py 中 app 定义顺序（先定义后引用）。

## 配置文件

| 文件 | 管线 | 内容 |
|------|------|------|
| `config/settings.yaml` | video | 画幅、I2V 模型、时长、风格 key、ComfyUI 模型名 |
| `config/revive_settings.yaml` | revive | YOLO/深度/3DGS/重排/动画参数、物体深度范围 |
| `config/styles.yaml` | video | 风格预设（painters/正负提示词/采样器/步数） |
| `config/mesh2video.yaml` | mesh2video | 渲染与 I2V 参数 |
| `workflows/` | 两管线 | 用户自定义 ComfyUI 工作流，同名覆盖内置模板 |

## CLI

```bash
# video 管线
oilpaint-video generate --theme "星空下的村庄"     # 剧本
oilpaint-video render <project_dir>               # 关键帧+片段
oilpaint-video compose <project_dir>              # 剪辑
oilpaint-video full --theme "..."                 # 一键端到端

# revive 管线
oilpaint-revive health                            # ComfyUI 探测
oilpaint-revive run <油画路径> --no-comfyui        # 一键端到端 (mock)

# GUI 工作站 (端口 8710, 前端已随包构建)
py -m oilpainting_studio.gui.server

# 桌面论文 Demo (pywebview 窗口, 端口 8712)
py -m oilpainting_studio.desktop
```

## 测试

```bash
cd OilPaintingStudio && pip install -e ".[dev]" && pytest -v
# 85 项: test_video_screenplay(7) + test_video_integration(25)
#      + test_video_mesh2video(6) + test_revive_pipeline(20)
#      + test_gui_server(13) + test_desktop_demo(14)
# 全部 mock 模式, 无需 GPU/ComfyUI/LLM Key
```

## 论文

| 论文 | 位置 | 状态 |
|------|------|------|
| Canvas3D (IJCAI'26 主会) | `paper/Canvas3D/` | 10pp 已编译；`figures_preview/` 30 个图表变体待挑选集成 |
| survey | `paper/survey/` | 早期备份 |
| InkFlow (IJCAI 2027) | `paper/InkFlow/` | 框架初稿, experiments 待补 |
