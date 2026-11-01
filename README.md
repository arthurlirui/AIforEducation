# AIforEducation

面向**艺术教育 + AI 生成**的 monorepo，包含五个子项目：从波点艺术生成、油画动态化，到绘画手势教练和可交互学习平台。共享名画素材库与 IJCAI 论文 LaTeX 资产。

## 子项目一览

| 目录 | 项目 | 一句话 | 技术栈 |
|------|------|--------|--------|
| [`DotArtKit/`](DotArtKit/) | 统一波点艺术生成器 | 8 种流派波点艺术：点彩/Ben-Day/欧普/点绘/叶序/草间弥生（基础+深度感知）/可学习映射 | Python, numpy/PIL, scipy/ultralytics/torch 可选 |
| [`OilPaintingStudio/`](OilPaintingStudio/) | 经典油画动态艺术生成 | 两条管线：LLM 剧本 → 油画关键帧 → I2V 短片（video）；单画 → YOLO 分割 + 3DGS → 线稿重排 → 动态视频（revive/Canvas3D） | Python, ComfyUI, ControlNet, ffmpeg |
| [`OilPaintingPlatform/`](OilPaintingPlatform/) | 油画教学 + AI 文生图平台 | 前后端分离网站：12 风格 + 28 提示词模板 + 6 视觉大模型（含免费 Pollinations）+ 教学文章 + 画廊 | FastAPI, Vue 3, Pinia |
| [`TechLearnStudio/`](TechLearnStudio/) | 可交互网页 PPT 学习平台 | 文档/讲义 → Composer(LLM+规则) → frames.json → hyperframe 播放；覆盖 Python/Rust/Go/TS 与信号/无线/大模型专业课 | FastAPI, SQLModel, Vue 3, reveal.js, SVG/SMIL |
| [`GestureCoach/`](GestureCoach/) *(submodule)* | 绘画手势教练 | MediaPipe 手部跟踪 + 改进 DTW 诊断 + 规则/LLM 双通道反馈 + Krita 插件 + 课堂管理 | Python, FastAPI, React, Krita Python API |

## 共享资产

```
AIforEducation/
├── images/     18 张经典油画高清扫描（各子项目测试素材）
├── latex/      IJCAI 论文 LaTeX 模板与历史论文源码
├── docs/       统一文档中心（架构总览、模块参考、版本策略）
└── bak/        重组前旧项目存档（已从 git 移除，仅本地保留）
```

## 快速开始

各子项目独立安装、独立运行，详见各自 README：

```bash
# 波点艺术（纯 numpy 模式零依赖）
cd DotArtKit && pip install -e . && dotart demo

# 油画动态化（mock 模式无需 ComfyUI）
cd OilPaintingStudio && pip install -e .[dev] && pytest
python -m oilpainting_studio.revive.cli run <油画路径> --no-comfyui

# 教学平台（内置 Mock Provider，零 Key 可演示）
cd OilPaintingPlatform/backend && pip install -r requirements.txt && uvicorn app.main:app
cd OilPaintingPlatform/frontend && npm install && npm run dev

# 学习平台
cd TechLearnStudio && pip install -r backend/requirements.txt && pytest

# 手势教练（先 git submodule update --init）
cd GestureCoach && pip install -r requirements.txt && pytest
```

## 学术产出

| 论文 | 状态 | 位置 |
|------|------|------|
| Spatially-Aware Stippling（深度感知草间弥生波点） | IJCAI'26 Arts 方向 | `DotArtKit/paper/` |
| Canvas3D（油画 4 模块动态化框架） | IJCAI'26 主会 10pp | `OilPaintingStudio/paper/Canvas3D/` |
| GestureCoach（实时绘画反馈） | IJCAI 2027 准备中（待用户研究） | `GestureCoach/latex/IJCAI2027/` |
| InkFlow（水墨视频扩散） | 早期框架稿 | `OilPaintingStudio/paper/InkFlow/` + `latex/InkFlow/` |

投稿状态与时间表见 [`docs/IJCAI2027_submission_status.md`](docs/IJCAI2027_submission_status.md)。

## 文档

- [架构总览](docs/architecture.md) — 全局架构与子项目关系
- [模块参考](docs/README.md) — 逐文件功能说明
- [版本管理策略](docs/VERSIONING.md) / [更新日志](docs/CHANGELOG.md) / [贡献指南](docs/CONTRIBUTING.md)
