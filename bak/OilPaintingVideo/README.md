# OilPaintingVideo —— 经典油画风格剧情短视频生成器

> LLM 生成剧本 → ComfyUI 生成油画关键帧 → ComfyUI 图生视频（LTX-Video / Wan2.2-I2V）→ ffmpeg 自动剪辑成片。

端到端本地管线，调用本地 ComfyUI 实例出图出视频，OpenAI 兼容 LLM API 写剧本。

---

## ✨ 特性

- **剧本 AI 生成**：OpenAI 兼容 LLM，结构化 JSON 输出，解析失败自动回灌重试
- **油画风格预设库**：印象派 / 巴洛克 / 写实主义 / 浪漫主义，单镜头可指定画家（梵高/莫奈/伦勃朗/透纳…）
- **图生视频双模型**：LTX-Video（快、显存友好）/ Wan2.2-I2V（质量高），逐镜头可切换
- **画幅自适应**：竖屏 9:16（抖音/视频号）/ 横屏 16:9（B 站/YouTube）
- **自动剪辑**：ffmpeg 拼接 + 转场 + BGM 情绪匹配 + 字幕烧录
- **可替换工作流**：内置 ComfyUI 模板，`workflows/` 同名文件即可覆盖

---

## 📦 安装

```bash
cd OilPaintingVideo
pip install -e .            # 主依赖
pip install -e ".[dev]"     # 含 pytest / pytest-asyncio
```

要求 Python ≥ 3.11。本机已验证可安装（anaconda3 解释器）。

## 🔧 配置

```bash
cp .env.example .env
# 编辑 .env，填入：
#   LLM_API_KEY=...        OpenAI 兼容端点的 key
#   LLM_BASE_URL=...       端点
#   LLM_MODEL=...          模型名
#   COMFY_HOST/COMFY_PORT  本地 ComfyUI 地址（默认 127.0.0.1:8188）
#   FFMPEG_PATH=...        可选，留空用系统 PATH
```

创作参数见 `config/settings.yaml`（画幅/时长/模型名/采样参数/剪辑选项）。
风格预设见 `config/styles.yaml`。

### ComfyUI 前置模型

项目假设你的 ComfyUI 实例已安装并加载以下节点与权重（节点名以你实际环境为准，可在 `workflows/` 覆盖模板）：

- **关键帧**：SDXL 基模（如 `sd_xl_base_1.0.safetensors`）+ 可选油画风格 LoRA
- **LTX-Video**：`ltx-video-2b-v0.9.5.safetensors`，需 `LTXVLoader/LTXVSampler/LTXVDecode` 节点
- **Wan2.2-I2V**：`wan2.2_i2v_720p_bf16.safetensors`，需 `WanVideoLoader/WanVideoSampler/WanVideoDecode` 节点
- 视频保存统一用 `VHS_VideoCombine`（ComfyUI-VideoHelperSuite）

> 模板里的 `class_type` 与权重名是占位，请按你的 ComfyUI 实际情况修改 `config/settings.yaml` 中的模型名，或在 `workflows/` 放同名 JSON 整体替换。

### ffmpeg

```bash
python tools/ensure_ffmpeg.py    # 检查可用性
# 缺失时：conda install -c conda-forge ffmpeg
# 或在 .env 设置 FFMPEG_PATH 指向 ffmpeg.exe
```

---

## 🚀 使用

```bash
# 0. 环境自检
oilpaint health

# 1. 仅生成剧本
oilpaint generate "渔夫在晨光中归港" --style impressionism --aspect 9:16 --duration 30

# 2. 渲染关键帧 + 视频片段（需已有剧本）
oilpaint render 20260928_120000

# 3. 剪辑成片
oilpaint compose 20260928_120000

# 4. 一键端到端
oilpaint full "渔夫在晨光中归港" \
  --style impressionism \
  --aspect 9:16 \
  --duration 30 \
  --i2v ltx
```

> 若 `oilpaint` 命令不在 PATH，可用 `python -m oilpaint.cli.main <子命令>`。

### 产物结构

```
output/<project_id>/
├── screenplay.json     # 结构化剧本
├── keyframes/          # 油画关键帧 PNG
├── clips/              # 每镜头视频片段 mp4
├── final.mp4           # 成片
└── meta.json           # 参数与各阶段耗时
```

---

## 🎨 自定义工作流

内置三份 ComfyUI **API 格式**模板（`src/oilpaint/comfy/templates/`）：

| 模板 | 用途 | 关键节点 id |
|---|---|---|
| `img2img_oilpaint.json` | 关键帧油画化 | `ckpt`/`lora`/`latent`/`prompt_pos`/`prompt_neg`/`sampler`/`save` |
| `ltx_i2v.json` | LTX 图生视频 | `ltx_model`/`ltx_pos`/`ltx_neg`/`ltx_sampler`/`ltx_save`/`input_image` |
| `wan_i2v.json` | Wan 图生视频 | `wan_model`/`wan_pos`/`wan_neg`/`wan_sampler`/`wan_save`/`input_image` |

要替换为含 IPAdapter / ControlNet / 更复杂 LoRA 的版本：在项目根 `workflows/` 放同名 JSON（从 ComfyUI 网页端「保存（API 格式）」导出），运行时会优先加载它。只需保持上面约定**节点 id 与字段名**一致，管线就能正确注入参数。

---

## 🧪 开发与测试

```bash
pytest -q     # 剧本 schema / generator 单测（mock LLM，无需真实 API）
```

## 📁 项目结构

```
OilPaintingVideo/
├── config/            # settings.yaml + styles.yaml
├── src/oilpaint/
│   ├── config.py            # 配置加载
│   ├── llm_client.py        # OpenAI 兼容 LLM 客户端
│   ├── screenplay/          # 剧本 schemas / prompts / generator
│   ├── comfy/               # ComfyUI 客户端 + 工作流模板
│   ├── pipeline/            # director / keyframe / animate / edit
│   ├── audio/               # BGM / TTS（预留）
│   └── cli/main.py          # CLI 入口
├── workflows/         # 用户可替换工作流（覆盖内置模板）
├── assets/            # bgm / fonts
├── output/            # 产物
├── tools/             # ensure_ffmpeg 等辅助脚本
└── tests/
```

## 🗺️ 路线图

- [ ] TTS 旁白音轨（GPT-SoVITS / Edge-TTS）
- [ ] IPAdapter 风格一致性（跨镜头人物/画风锁定）
- [ ] 自动 BGM 情绪分段（按场景切换音乐）
- [ ] Web UI 预览剧本与关键帧
