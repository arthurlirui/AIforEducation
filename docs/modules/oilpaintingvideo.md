# OilPaintingVideo — 模块与文件参考

> **路径**: `OilPaintingVideo/` ｜ **包名**: `oilpaint-video` (导入名 `oilpaint`) ｜ **版本**: 0.1.0 ｜ **Python**: ≥ 3.11

## 项目简介

端到端的本地管线，用于生成古典油画风格叙事短片。管线: **LLM 生成剧本 → ComfyUI 生成油画关键帧 → ComfyUI 图生视频 (LTX-Video 或 Wan2.2-I2V) → ffmpeg 自动剪辑成片**。

包含可选的 `mesh2video` 扩展模块，支持 3D 白模 → 深度/法线引导 → I2V 风格化。

## 文件结构

```
OilPaintingVideo/
├── src/oilpaint/                    # 源码包 (src-layout)
│   ├── __init__.py                  # 包标记 + 版本号
│   ├── config.py                    # 配置加载 (.env + settings.yaml + styles.yaml)
│   ├── llm_client.py                # 异步 LLM 客户端 (OpenAI 兼容)
│   ├── audio/                       # 音频模块
│   │   ├── __init__.py
│   │   ├── bgm.py                   # BGM 选择
│   │   └── tts.py                   # TTS 旁白 (占位符)
│   ├── cli/                         # Click CLI
│   │   ├── __init__.py
│   │   └── main.py                  # health/generate/render/compose/full
│   ├── comfy/                       # ComfyUI 客户端
│   │   ├── __init__.py
│   │   ├── client.py                # 异步 ComfyUI REST API 封装
│   │   ├── workflows.py             # 工作流模板加载 + 参数注入
│   │   └── templates/               # 内置 ComfyUI JSON 模板
│   │       ├── img2img_oilpaint.json
│   │       ├── ltx_i2v.json
│   │       ├── ltx_i2v_3d_guide.json
│   │       ├── wan_i2v.json
│   │       └── wan_i2v_3d_depth.json
│   ├── screenplay/                  # 剧本模块
│   │   ├── __init__.py
│   │   ├── schemas.py               # Pydantic 剧本模型 (Script/Scene/Shot)
│   │   ├── generator.py             # LLM 剧本生成 + 重试修复
│   │   └── prompts.py               # LLM 提示构建
│   ├── pipeline/                    # 管线编排
│   │   ├── __init__.py
│   │   ├── director.py              # 导演级编排
│   │   ├── keyframe.py              # 关键帧生成 (img2img)
│   │   ├── animate.py               # 图生视频 (LTX/Wan)
│   │   ├── edit.py                  # ffmpeg 自动剪辑
│   │   └── ffmpeg_tool.py           # ffmpeg 底层工具
│   └── mesh2video/                  # 3D 白模扩展模块
│       ├── __init__.py              # 公共 API 再导出
│       ├── camera.py                # 针孔相机 + 轨道相机
│       ├── renderer.py              # CPU 软件光栅化器
│       ├── animation.py             # 动画驱动器
│       ├── pipeline.py              # 端到端编排
│       └── example.py               # CLI demo
├── config/                          # 配置文件
│   ├── settings.yaml                # 全局配置
│   ├── styles.yaml                  # 风格预设
│   └── mesh2video.yaml              # mesh2video 配置
├── tests/                           # pytest 测试
│   ├── test_integration.py          # 集成测试 (全 mock)
│   ├── test_screenplay.py           # 剧本测试
│   └── test_mesh2video.py           # mesh2video 测试
├── tools/ensure_ffmpeg.py           # ffmpeg 定位工具
├── workflows/                       # 用户工作流覆盖目录
├── docs/                            # 项目文档
│   ├── comfyui_http_api.md          # ComfyUI HTTP API 参考
│   └── mesh2video/README.md         # mesh2video 说明
├── latex/                           # IJCAI'26 论文 LaTeX
├── pyproject.toml                   # 项目元数据与依赖
├── .env.example                     # 环境变量模板
└── README.md                        # 项目说明
```

## 依赖关系图

```
.config (.env + settings.yaml + styles.yaml)
    │  load_settings()
    ▼
config.Settings
    │
    ├──► screenplay.generator ──► screenplay.schemas (Script/Scene/Shot)
    │         │                   screenplay.prompts
    │         └── llm_client.LLMClient
    │
    ├──► pipeline.director
    │         ├── stage_generate (LLM → screenplay.json)
    │         ├── stage_render
    │         │     ├── pipeline.keyframe (img2img_oilpaint 模板)
    │         │     └── pipeline.animate (LTX/Wan I2V 模板)
    │         │           └── comfy.client + comfy.workflows
    │         └── stage_compose
    │               └── pipeline.edit (ffmpeg + audio.bgm)
    │
    └──► [扩展] mesh2video.pipeline
              ├── mesh2video.camera + renderer + animation
              └── comfy.client + comfy.workflows
```

---

## 逐文件说明

### 顶层模块

#### __init__.py — 包标记

**职责**: 包初始化，声明版本号 `__version__ = "0.1.0"`。

#### config.py — 配置加载

**职责**: 从 `.env` (密钥/端点)、`settings.yaml` (创意参数) 和 `styles.yaml` (风格预设) 合并到单一 `Settings` 对象。优先级: CLI 参数 > 环境变量 > settings.yaml > 代码默认值。

| 组件 | 说明 |
|------|------|
| `StylePreset` (dataclass) | key, name, painters, positive_prefix, negative, sampler, scheduler, cfg, steps, bgm_mood |
| `Settings` (dataclass) | 全部可调参数: 宽高、I2V 模型、视频参数、ComfyUI 模型名、路径、剪辑选项; `comfy_url` 属性, `style(key)` 预设查找 |
| `load_settings(path=None)` | 加载 .env → settings.yaml → 映射宽高 → 环境变量覆盖 → styles.yaml |
| `_load_styles(path)` | 解析 styles.yaml → dict[str, StylePreset] |

#### llm_client.py — 异步 LLM 客户端

**职责**: OpenAI 兼容的异步 LLM 客户端，带重试/退避和 JSON 模式解析。用于剧本生成。

| 方法 | 说明 |
|------|------|
| `chat(messages, ...)` | POST /chat/completions; 429/5xx 指数退避 (最多 6 次); 失败返回 `LLM_ERROR_PREFIX` 前缀字符串 |
| `chat_json(messages, ...)` | chat + json_mode=True, 去除 ```json 代码围栏, 解析为 dict |
| `aclose()` | 关闭 HTTP 客户端 |

**常量**: `MAX_RETRIES=6`, `BASE_DELAY=3.0`, `MAX_DELAY=60.0`, `DEFAULT_TIMEOUT=300.0`

---

### 音频模块 (audio/)

#### audio/bgm.py — BGM 选择

**职责**: 根据 mood 从 `assets/bgm/` 选择背景音乐 (文件名如 `<mood>.mp3`)，回退到任意可用音频，无匹配返回 None。

| 函数 | 说明 |
|------|------|
| `pick_bgm(assets_dir, mood)` | → Path \| None |

**被调用方**: `pipeline/edit.py`

#### audio/tts.py — TTS 旁白 (占位符)

**职责**: TTS 旁白接口占位符，当前始终返回 None。计划后续接入 GPT-SoVITS / Edge-TTS / Volcano TTS。

| 函数 | 说明 |
|------|------|
| `synthesize_narration(text, out_path)` | → Path \| None (当前为 None) |

---

### CLI 模块 (cli/)

#### cli/main.py — Click CLI 入口

**职责**: 暴露 `health`, `generate`, `render`, `compose`, `full` (端到端) 子命令。

| 命令 | 说明 |
|------|------|
| `health` | 探测 ComfyUI / LLM / ffmpeg 可用性 |
| `generate(topic)` | LLM 生成剧本 |
| `render(project_id)` | 渲染关键帧 + 视频片段 |
| `compose(project_id)` | ffmpeg 剪辑 |
| `full(topic)` | 一键端到端 |

**入口**: `oilpaint = "oilpaint.cli.main:cli"`

---

### ComfyUI 客户端 (comfy/)

#### comfy/client.py — 异步 ComfyUI REST 客户端

**职责**: 封装 ComfyUI API 的完整提交-轮询-下载生命周期 (上传图片, 排队, 轮询 /history, 从 /view 拉取产物)，带 asyncio.Semaphore 并发限制。

| 方法 | 说明 |
|------|------|
| `health()` | 健康检查 |
| `object_info(node_id)` | 节点信息 |
| `upload_image(path)` | 上传图片 |
| `queue_prompt(workflow)` | 提交工作流 |
| `get_history(prompt_id)` | 轮询历史 |
| `download_view(filename, ...)` | 下载输出 |
| `run(workflow, ...)` | 端到端: 提交 → 轮询 → 收集 |
| `aclose()` | 关闭客户端 |

#### comfy/workflows.py — 工作流模板管理

**职责**: 加载 ComfyUI API 格式工作流 JSON 模板 (内置 `comfy/templates/` 或用户覆盖 `workflows_dir/`)，按节点 ID/字段路径注入参数，设置采样器随机种子。

| 函数 | 说明 |
|------|------|
| `load_template(name, workflows_dir)` | 加载模板 (内置 → 用户覆盖) |
| `apply_params(template, params)` | 按节点 ID/字段路径注入参数 |
| `set_seed(wf, node_id, seed)` | 设置采样器种子 |
| `list_templates()` | 列出可用模板 |

**内置模板**:
- `img2img_oilpaint.json` — 油画风格 img2img 关键帧
- `ltx_i2v.json` — LTX 图生视频
- `ltx_i2v_3d_guide.json` — LTX 带 3D 引导
- `wan_i2v.json` — Wan2.2 图生视频
- `wan_i2v_3d_depth.json` — Wan 带 3D 深度

---

### 剧本模块 (screenplay/)

#### screenplay/schemas.py — Pydantic 剧本模型

**职责**: 剧本的 Pydantic v2 数据模型。

| 模型 | 说明 |
|------|------|
| `Shot` | 一个关键帧 + 一个视频片段; camera_motion 验证器 (排除 "spin"), i2v_model 验证器 (排除 "sora"); 默认 motion="static", model="ltx", duration=3.0s |
| `Scene` | 叙事单元 (含多个 Shot) |
| `Script` | 完整剧本; `shots` 属性 (扁平化), `recompute_duration()` |
| `SCRIPT_JSON_SCHEMA_HINT` | LLM 提示用的 JSON schema 字典 |

#### screenplay/generator.py — LLM 剧本生成

**职责**: 调用 LLM 生成结构化剧本 JSON，带自动重试/修复 (最多 3 轮，将解析/验证错误反馈给 LLM)。解析后修复 shot 编号为全局连续。

| 函数 | 说明 |
|------|------|
| `generate_script(client, settings, topic)` | → (Script \| None, info) |
| `_repair_shot_numbering(script)` | 重新索引 shot/scene 编号 |

#### screenplay/prompts.py — LLM 提示构建

**职责**: 构建 LLM 系统和用户提示，指导"导演/编剧"角色输出符合 schema 的单一 JSON 剧本对象，附带美学约束 (油画风格、镜头设计、运镜、I2V 模型选择)。

| 函数 | 说明 |
|------|------|
| `system_prompt(style_key, style_name, painters)` | 系统提示 |
| `user_prompt(topic, target_duration_sec, ...)` | 用户提示 |

---

### 管线模块 (pipeline/)

#### pipeline/director.py — 导演级编排

**职责**: 项目目录管理、剧本持久化 (`screenplay.json`) 和三阶段执行 (LLM 生成剧本、ComfyUI 渲染关键帧+片段、ffmpeg 剪辑)。

| 函数 | 说明 |
|------|------|
| `new_project_dir(settings)` | 创建项目目录 |
| `save_script(...)` / `load_script(...)` | 剧本持久化 |
| `stage_generate(client, settings, topic)` | LLM 生成剧本 |
| `stage_render(client, settings, script, project_dir)` | ComfyUI 渲染 |
| `stage_compose(settings, script, clips, project_dir)` | ffmpeg 剪辑 |
| `run_full(client, settings, topic)` | 一键端到端 (含计时) |
| `write_meta(...)` | 写元数据 |

#### pipeline/keyframe.py — 关键帧生成

**职责**: 通过 ComfyUI 使用 `img2img_oilpaint` 模板为每个 shot 生成油画风格关键帧 (第一帧)。

| 函数 | 说明 |
|------|------|
| `build_positive(shot, style)` | 正向提示 (风格前缀 + 画家 + shot 提示 + 质量标签) |
| `build_keyframe_workflow(settings, shot, style, out_prefix)` | 构建工作流 JSON |
| `render_keyframe(client, settings, shot, style, save_dir, out_prefix)` | 执行生成 → 关键帧路径 |

#### pipeline/animate.py — 图生视频

**职责**: 逐 shot 调度 I2V 生成: 根据 `shot.i2v_model` 选择 LTX 或 Wan 模板，注入上传的关键帧、运动文本提示、分辨率/帧率/步数，提交 ComfyUI。

| 函数 | 说明 |
|------|------|
| `render_clip(client, settings, shot, keyframe_path, save_dir, out_prefix)` | → 视频片段路径 |
| `_build_ltx(...)` | 构建 LTX 工作流 |
| `_build_wan(...)` | 构建 Wan 工作流 |
| `_num_frames(duration, fps)` | 帧数计算 |
| `_motion_text(motion)` | 运镜文本 (从 `_MOTION_TEXT` 字典) |

#### pipeline/edit.py — ffmpeg 自动剪辑

**职责**: 使用 ffmpeg 自动剪辑: 统一片段分辨率/帧率/编码 → 拼接 (xfade/重编码回退) → 叠加 BGM (循环, 0.35 音量) → drawtext 烧录字幕。

| 函数 | 说明 |
|------|------|
| `compose_video(settings, script, clips, project_dir)` | → 最终视频路径 |
| `_norm_clip(...)` | 统一片段格式 |
| `_concat(...)` | 拼接 |
| `_build_subtitle_filter(...)` | 字幕 drawtext 滤镜 |
| `_add_bgm_and_subtitle(...)` | BGM + 字幕叠加 |

#### pipeline/ffmpeg_tool.py — ffmpeg 底层工具

**职责**: ffmpeg/ffprobe 底层封装: 定位可执行文件 (配置路径 → PATH → conda 回退)，运行命令并捕获 stderr，探测视频时长。

| 函数 | 说明 |
|------|------|
| `resolve_ffmpeg(ffmpeg_path)` | 定位 ffmpeg |
| `run_ffmpeg(args, ffmpeg_path)` | 运行 ffmpeg → (成功, stderr) |
| `probe_duration(ffprobe_path, video)` | 探测时长 |

---

### mesh2video 扩展模块 (mesh2video/)

3D 动态白模 → 深度/法线引导 → I2V 风格化的独立管线，拥有自己的配置 (`config/mesh2video.yaml`)。

#### mesh2video/__init__.py — 公共 API

**职责**: 包文档字符串 + 再导出核心类: `Camera`, `orbit_camera`, `WhiteMeshRenderer`, `RenderPass`, `AnimationDriver`, `StaticDriver`, `Mesh2VideoPipeline`, `Mesh2VideoConfig`。

#### mesh2video/camera.py — 针孔相机模型

**职责**: 最小针孔相机模型 (内参, OpenGL 风格视图/投影矩阵) 和轨道轨迹生成器。仅依赖 numpy，离线渲染无需 GPU/OpenGL。

| 组件 | 说明 |
|------|------|
| `Camera` | `from_fov(...)`, `view_matrix`, `projection_matrix` |
| `orbit_camera(target, radius, num_frames, ...)` | → list[Camera] |

#### mesh2video/renderer.py — CPU 软件光栅化器

**职责**: 将动画三角网格软件光栅化为三组图像序列: `clay` (Lambert 着色灰模), `depth` (线性深度图), `normal` (视图空间法线 RGB)。输出 uint8 HxWx3。

| 组件 | 说明 |
|------|------|
| `RenderPass` (枚举) | CLAY / DEPTH / NORMAL |
| `WhiteMeshRenderer` | `render(mesh, cam, passes)`, `render_sequence(...)` |
| `save_frames(frames, out_dir, prefix)` | 保存帧序列 |

#### mesh2video/animation.py — 动画驱动器

**职责**: 通过驱动接口抽象 "时间 t → 一帧网格"。提供静态驱动、关键网格线性插值 morph 驱动和可调用自定义驱动。

| 类 | 说明 |
|------|------|
| `AnimationDriver` | 基类 |
| `StaticDriver(mesh, num_frames)` | 静态 (仅相机移动) |
| `MorphDriver(key_meshes, num_frames)` | 关键网格线性插值 |
| `CallableDriver(func)` | 自定义可调用 |

#### mesh2video/pipeline.py — 端到端编排

**职责**: 渲染 3D 白模序列 (clay/depth/normal) → 写 mp4+png → 上传风格图和控制视频到 ComfyUI → 构建 Wan (depth ControlNet) 或 LTX (LTXVAddGuide) 工作流 → 提交 → 下载风格化视频。

| 组件 | 说明 |
|------|------|
| `Mesh2VideoConfig` | dataclass: base_url, workflow_name 等 |
| `Mesh2VideoPipeline` | `run(...)`, `_build_wan_workflow(...)`, `_build_ltx_workflow(...)` |

#### mesh2video/example.py — CLI Demo

**职责**: CLI demo (`python -m oilpaint.mesh2video.example`)，加载 GLB/OBJ、归一化、构建轨道相机，可选 `--render-only` (离线渲染) 或完整风格化管线 (Wan/LTX)。

---

## 配置文件

### config/settings.yaml

| 分区 | 关键字段 |
|------|---------|
| 宽高 | `aspect` ("9:16" / "16:9") |
| I2V 模型 | `default_i2v_model` ("ltx" / "wan") |
| 视频参数 | `target_duration_sec`, `fps`, `shot_duration_sec`, `concurrency` |
| 风格 | `default_style` (指向 styles.yaml 键) |
| ComfyUI 模型 | `sdxl_checkpoint`, `oilpaint_lora`, `ltx_model`, `wan_model` 等 |
| 路径 | `output_dir`, `workflows_dir`, `assets_dir`, `ffmpeg_path` |
| 剪辑 | `transition` ("xfade"/"cut"), `transition_duration_sec`, `burn_subtitle`, `subtitle_font` |

### config/styles.yaml

4 套风格预设: `impressionism`, `baroque`, `realism`, `romanticism`。每套含: name, painters, positive_prefix, negative, sampler, scheduler, cfg, steps, bgm_mood。

### config/mesh2video.yaml

mesh2video 专用配置: ComfyUI 连接、后端 (wan/ltx)、视频参数 (帧数/宽高/帧率/种子)、风格锚定图、控制强度、采样参数、渲染/相机默认值。

### .env.example

`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `COMFY_HOST`, `COMFY_PORT`, `FFMPEG_PATH`

---

## pyproject.toml 依赖

| 分类 | 依赖 |
|------|------|
| 核心 | httpx, pyyaml, pillow, python-dotenv, click, pydantic≥2.6 |
| dev (可选) | pytest, pytest-asyncio |
| mesh2video (可选) | trimesh, numpy, imageio, imageio-ffmpeg |

---

## 测试

| 文件 | 说明 |
|------|------|
| `test_integration.py` | 集成测试 (全 mock): 配置加载、工作流模板结构、ComfyUI client、关键帧/动画工作流构建、导演全链路、ffmpeg 剪辑命令、LLM 客户端 |
| `test_screenplay.py | 剧本 schema + 生成器单元测试 (mock LLM): shot 验证、编号修复、生成重试 |
| `test_mesh2video.py` | mesh2video 冒烟测试: 相机轨道、渲染器三通道、静态/morph 驱动、工作流注入 |

**运行**: `pip install -e ".[dev]" && pytest`

---

## 工具

### tools/ensure_ffmpeg.py

**职责**: 定位或提示安装 ffmpeg。检查系统 PATH，然后 Windows 硬编码候选路径；缺失时打印安装指引。

| 函数 | 说明 |
|------|------|
| `main()` | → 0 (找到) / 1 (未找到) |
