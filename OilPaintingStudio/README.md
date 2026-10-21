# OilPaintingStudio — 经典油画动态艺术生成统一项目

整合两个互补的油画动态生成管线 + 三份论文初稿.

## 两条管线

### video — 剧本驱动多镜头短片 (原 OilPaintingVideo)

```
LLM 剧本 → ComfyUI 油画关键帧 → I2V 视频 (LTX/Wan2.2) → ffmpeg 自动剪辑
```

- OpenAI 兼容 LLM 写剧本, 结构化 JSON 输出, 解析失败自动回灌重试 (≤3 轮)
- 4 种风格预设 (印象派/巴洛克/现实主义/浪漫主义), 逐镜头可指定画家
- 双 I2V 模型: LTX-Video (快) / Wan2.2-I2V (高质量), 逐镜头切换
- 9:16 与 16:9 双画幅, ffmpeg 拼接 + BGM 情绪匹配 + 字幕烧录

### revive — 单画物体级 3D 重排动画 (原 OilPaintingRevive, Canvas3D)

```
单幅油画 + 手绘线稿 → PaintParse → MonoSplat → SketchComp → ArtiFlow
```

- **PaintParse** (stage1): YOLO 分割 + Depth Anything V2 单目深度
- **MonoSplat** (stage2): TripoSplat 单图→3DGS + 度量重缩放
- **SketchComp** (stage3): 线稿解析 + 轮廓配准 (IoU+Chamfer) + SD 修复
- **ArtiFlow** (stage5): 双 ControlNet (depth 0.85 + HED edge 0.6) + Wan2.2/LTX2.3 视频合成

## 论文初稿 (paper/)

| 目录 | 论文 | 投稿 | 状态 |
|------|------|------|------|
| `paper/Canvas3D/` | Canvas3D: Object-Level 3DGS + Line-Art Composition | IJCAI'26 | 主稿 10 页, 82 refs, 5 TikZ 图, 编译通过 |
| `paper/survey/` | A Survey on Dynamic Video-Style Generation for World-Famous Paintings | (备份) | 早期综述 |
| `paper/InkFlow/` | InkFlow: Dual-Conditioned Video Diffusion for Chinese Ink-Wash | IJCAI'27 | 初稿 |

## 安装

```bash
cd OilPaintingStudio
pip install -e .                  # 核心依赖
pip install -e ".[dev]"           # + pytest (测试)
pip install -e ".[mesh2video]"    # + trimesh/imageio (mesh2video)
pip install -e ".[torch,gs]"      # + torch/plyfile (revive 真实推理)
pip install -e ".[all]"           # 全部
```

## 配置

```bash
cp .env.example .env                  # Video: COMFY_HOST/PORT, LLM_API_KEY, FFMPEG_PATH
cp .env.revive.example .env.revive    # Revive: COMFY_HOST/PORT, YOLO_MODEL_PATH, ...
```

## 使用

### Python API

```python
# Video 管线
from oilpainting_studio.video.cli import cli as video_cli
from oilpainting_studio.video.screenplay.generator import generate_screenplay
from oilpainting_studio.video.pipeline.director import run_pipeline

# Revive 管线
from oilpainting_studio.revive.cli import cli as revive_cli
from oilpainting_studio.revive.stage1 import run_segmentation, run_depth_estimation
from oilpainting_studio.revive.stage2 import assemble_scene
from oilpainting_studio.revive.stage3 import parse_lineart, reposition_objects

# 共享
from oilpainting_studio.common.config import load_settings
from oilpainting_studio.common.llm_client import LLMClient
from oilpainting_studio.common.comfy.client import ComfyClient
```

### 测试

```bash
pytest tests/ -v                              # 全部 (52 项)
pytest tests/test_video_integration.py -v     # Video 集成
pytest tests/test_revive_pipeline.py -v       # Revive 全链路 (mock)
```

## 目录结构

```
OilPaintingStudio/
├── oilpainting_studio/          # 主包
│   ├── common/                  # 共享: config / llm_client / comfy / utils
│   ├── video/                   # 剧本→关键帧→I2V→剪辑
│   └── revive/                  # 单画→Canvas3D 4 模块
├── docs/
│   ├── 设计文档.md               # 整合项目设计文档 (核心)
│   ├── comfyui_http_api.md
│   ├── revive_design.md
│   └── mesh2video/
├── paper/                       # 三份论文初稿
│   ├── Canvas3D/  survey/  InkFlow/
├── tests/                       # 52 项测试 (video 32 + revive 20)
├── config/  workflows/  assets/  images/  output/
├── scripts/                     # 迁移脚本 (migrate_imports / fix_nested_imports)
├── README.md  pyproject.toml  requirements.txt
```

## 来源

整合自两个前身项目:
- `OilPaintingVideo/` (2026-10-08) — LLM 剧本 + ComfyUI + I2V + ffmpeg, 32 测试
- `OilPaintingRevive/` (2026-10-11) — 4 模块 Canvas3D (PaintParse/MonoSplat/SketchComp/ArtiFlow), 20 测试

详细映射见 [设计文档 §6](docs/设计文档.md).

## 文档

- **项目文档** (基于代码与论文实际内容编写, 含已知问题): [`docs/项目文档.md`](docs/项目文档.md)
- **整合设计文档** (架构与迁移记录): [`docs/设计文档.md`](docs/设计文档.md)
- **ComfyUI HTTP API**: [`docs/comfyui_http_api.md`](docs/comfyui_http_api.md)
- **Revive 原始设计**: [`docs/revive_design.md`](docs/revive_design.md)
- **Canvas3D 论文**: [`paper/Canvas3D/main.pdf`](paper/Canvas3D/main.pdf)
