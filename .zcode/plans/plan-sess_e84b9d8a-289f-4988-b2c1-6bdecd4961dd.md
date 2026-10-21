# 经典油画风格剧情短视频生成器 — 实施方案

## 项目定位
在 `D:\Code\AIforEducation\OilPaintingVideo\`（新文件夹）下构建一个端到端管线：**LLM 生成剧本 → ComfyUI 生成油画风格关键帧 → ComfyUI 图生视频（LTX-Video / Wan2.2-I2V）→ ffmpeg 自动剪辑成片**。本地调用 ComfyUI HTTP API，剧本走 OpenAI 兼容 LLM API。

## 技术栈
- **语言**：Python 3.12（anaconda3 的 python.exe）
- **LLM 剧本**：OpenAI 兼容端点（httpx 异步客户端，借鉴 story-studio 的重试/流式模式）
- **图像/视频生成**：ComfyUI HTTP API（`http://<host>:8188`，已有运行实例）
- **风格控制**：油画风格预设库（印象派/巴洛克/写实主义/浪漫主义）+ 单镜头可指定画家（梵高/莫奈/伦勃朗/透纳…），提示词驱动
- **剪辑**：ffmpeg（项目内置 `bin/ffmpeg.exe` 或读取系统 PATH；提供 `tools/ensure_ffmpeg.py` 自动从 conda 复制/下载）
- **画幅**：竖屏 9:16（1080×1920）/ 横屏 16:9（1920×1080），配置切换，工作流自适应

## 目录结构
```
OilPaintingVideo/
├── README.md
├── pyproject.toml                 # 依赖：httpx, pyyaml, pillow, python-dotenv, click
├── .env.example                   # LLM_API_KEY / LLM_BASE_URL / COMFY_HOST / COMFY_PORT
├── config/
│   ├── settings.yaml              # 主配置（模型/画幅/时长/风格预设路径）
│   └── styles.yaml                # 油画风格预设库（prompt 片段 + 负面词 + 推荐采样参数）
├── src/oilpaint/
│   ├── __init__.py
│   ├── config.py                  # 加载 .env + settings.yaml + styles.yaml
│   ├── llm_client.py              # OpenAI 兼容客户端（重试/超时，借鉴 story-studio）
│   ├── screenplay/
│   │   ├── __init__.py
│   │   ├── generator.py           # 调 LLM 生成结构化剧本（JSON Schema）
│   │   ├── schemas.py             # Script/Scene/Shot pydantic 模型
│   │   └── prompts.py             # 剧本生成系统提示词（含油画风格约束）
│   ├── comfy/
│   │   ├── __init__.py
│   │   ├── client.py              # ComfyUI HTTP 客户端（/prompt 排队 + /history 轮询 + /view 取图）
│   │   ├── workflows.py           # 工作流模板加载与参数注入
│   │   └── templates/             # ComfyUI 工作流 JSON 模板
│   │       ├── img2img_oilpaint.json    # 关键帧油画化（SDXL + 风格 LoRA / IPAdapter）
│   │       ├── ltx_i2v.json             # LTX-Video 图生视频
│   │       └── wan_i2v.json             # Wan2.2-I2V 图生视频
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── director.py            # 编排：剧本 → 关键帧 → 视频片段 → 剪辑
│   │   ├── keyframe.py            # 镜头首帧生成/油画化
│   │   ├── animate.py             # 图生视频调度（按 shot.i2v_model 选模板）
│   │   └── edit.py                # ffmpeg 拼接 + 转场 + 配乐 + 字幕
│   ├── audio/
│   │   ├── bgm.py                 # 背景音乐选取/混音（按风格情绪匹配）
│   │   └── tts.py                 # 可选旁白 TTS（预留接口，默认关闭）
│   └── cli/
│       ├── __init__.py
│       └── main.py                # click CLI：generate / render / compose / full
├── workflows/                     # 用户可替换的 ComfyUI 工作流（与 templates 同名覆盖）
├── assets/
│   ├── bgm/                       # 按情绪分类的免版权背景乐
│   └── fonts/                     # 字幕字体
├── output/                        # 产物（按 project_id 分目录）
│   └── <id>/
│       ├── screenplay.json        # 结构化剧本
│       ├── keyframes/             # 油画风格关键帧 PNG
│       ├── clips/                 # 每镜头视频片段 mp4
│       ├── final.mp4              # 成片
│       └── meta.json              # 参数与耗时记录
└── tests/
    └── test_screenplay.py         # 剧本 schema 校验 + mock LLM
```

## 数据流（核心管线）
1. **剧本生成**（`screenplay/generator.py`）
   - 输入：主题/关键词（CLI 参数）+ 风格预设 + 画幅 + 目标时长
   - LLM 产出结构化 JSON：`Script{title, synopsis, style, scenes:[Scene{shots:[Shot{prompt, painter, camera_motion, duration_sec, i2v_model, narration}]}]}`
   - 强约束 JSON Schema，解析失败自动重试（最多 3 轮）

2. **关键帧油画化**（`pipeline/keyframe.py`）
   - 每个 Shot 的 prompt + 画家 + 风格预设 → 拼装正向/负向提示词
   - 调 `img2img_oilpaint.json` 工作流（SDXL 基模 + 风格 LoRA，或纯提示词驱动），ComfyUI 出图
   - 按 `settings.aspect` 设定输出分辨率

3. **图生视频**（`pipeline/animate.py`）
   - 按 `shot.i2v_model` 选 `ltx_i2v.json` 或 `wan_i2v.json` 模板
   - 注入：关键帧图像、镜头运动 prompt（pan/zoom/static）、帧数 = duration_sec × fps
   - ComfyUI 出 mp4 片段

4. **自动剪辑**（`pipeline/edit.py`）
   - ffmpeg concat 各片段，镜头间加交叉淡化转场（xfade）
   - 按 Scene 节奏配 BGM（`audio/bgm.py` 按情绪匹配），音量 ducking
   - 烧录字幕（旁白/对白），字体从 `assets/fonts/` 读取
   - 输出 `final.mp4`（H.264 + AAC，适配移动端）

## ComfyUI 集成要点
- **客户端**（`comfy/client.py`）：`POST /prompt` 提交工作流（client_id 随机）→ 轮询 `/history/{prompt_id}` 直至完成 → `/view?filename=...` 拉取产物；支持并发排队（信号量限流，默认 2 路并行）
- **工作流模板**：以 ComfyUI 导出的 **API 格式 JSON** 为基础，运行时用 Python 替换节点参数（seed/prompt/分辨率/帧数/输入图像），而非保存可编辑图——保证可程序化驱动
- **模型假设**：ComfyUI 已安装 LTX-Video 与 Wan2.2-I2V 对应节点/权重；首次运行前 `cli/main.py health` 子命令探测 `/object_info` 校验模型可用性并给出缺模型提示
- **错误处理**：排队失败、历史里出现异常节点、超时（单镜头默认 10 分钟）均捕获并写入 `meta.json`

## 配置文件要点
- `.env`：`LLM_API_KEY`、`LLM_BASE_URL`、`COMFY_HOST`（默认 127.0.0.1）、`COMFY_PORT`（默认 8188）
- `settings.yaml`：`aspect`（9:16/16:9）、`default_i2v_model`（ltx/wan）、`target_duration_sec`（默认 30）、`fps`（默认 24）、`concurrency`、`ffmpeg_path`、模型名（checkpoint/LoRA）
- `styles.yaml`：每个风格预设含 `positive_prefix`、`negative`、`recommended_sampler`、`cfg`、`steps`、`bgm_mood`

## CLI 设计（click）
```
oilpaint --help
oilpaint health                    # 探测 LLM + ComfyUI + ffmpeg 可用性
oilpaint generate "主题"            # 仅生成剧本 → output/<id>/screenplay.json
oilpaint render <project_id>       # 关键帧 + 视频片段
oilpaint compose <project_id>      # 剪辑成片
oilpaint full "主题"                # 一键端到端
  --style impressionism            # 风格预设
  --aspect 9:16                    # 画幅
  --duration 30                    # 目标时长
  --i2v ltx                        # 默认图生视频模型
```

## 默认决策（用户未答的部分）
- LLM 配置：**独立配置**（`.env` + `settings.yaml`），不依赖 story-studio，但 llm_client 借鉴其重试/超时实现
- 油画风格：**风格预设库 + 单镜头可指定画家**，兼顾统一性与灵活性
- 时长：**可配置，默认 30s**（6-10 镜头，每镜头 2-4s）
- ffmpeg：项目 `tools/ensure_ffmpeg.py` 优先用系统 ffmpeg，缺失则提示从 conda 复制

## 实施顺序（分批落地，每步可独立验证）
1. 骨架：目录、`pyproject.toml`、配置加载、CLI 框架、`health` 子命令
2. 剧本模块：schemas + prompts + generator + 单测（mock LLM）
3. ComfyUI 客户端 + 工作流模板占位 + `render` 关键帧部分
4. 图生视频调度（LTX / Wan 模板）
5. ffmpeg 剪辑 + BGM + 字幕
6. 端到端 `full` 命令 + README 使用说明

## 交付物
- 可运行的 Python 项目（`pip install -e .` 后用 `oilpaint` 命令）
- 三份 ComfyUI 工作流模板（关键帧油画化 / LTX-I2V / Wan-I2V），用户可按本机模型替换
- 完整 README：安装、配置、ComfyUI 前置模型、使用示例、自定义工作流替换说明
- 一份示例输出目录结构演示（不强制真实跑模型，避免占用显存）
