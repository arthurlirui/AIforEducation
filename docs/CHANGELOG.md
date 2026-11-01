# 更新日志 (CHANGELOG)

本文件记录 AIforEducation monorepo 所有版本的变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.1.0] — 2026-10-29

### 新增

- 根目录 `README.md` — monorepo 入口文档：子项目一览、快速开始、学术产出
- `docs/modules/dotartkit.md` — DotArtKit 模块参考（替代 aiforpolkadotsart.md）
- `docs/modules/oilpaintingstudio.md` — OilPaintingStudio 模块参考（替代 oilpaintingrevive.md + oilpaintingvideo.md）
- `docs/modules/oilpaintingplatform.md` — OilPaintingPlatform 模块参考
- `.gitmodules` — GestureCoach 正式注册为 git submodule
- `.gitignore` 新增 LaTeX 编译中间产物规则（*.aux/*.bbl/*.blg/*.out/*.toc 等）与 *_backup.pdf

### 变更

- **目录重组**（沿用 2026-10-18 的整合成果，本次同步文档）：
  - `AIforPolkaDotsArt` + `AIforDotArt` → `DotArtKit`（8 流派统一包）
  - `OilPaintingVideo` + `OilPaintingRevive` → `OilPaintingStudio`（common + video + revive）
- `docs/README.md`、`docs/architecture.md`、`docs/CONTRIBUTING.md`、`docs/VERSIONING.md` 全面更新为新目录结构，补入 OilPaintingPlatform / TechLearnStudio
- OilPaintingStudio 修复迁移遗留缺陷（详见下）

### 修复

#### OilPaintingStudio（58 项测试由全部收集失败恢复为全绿）
- 修复 `video/pipeline/` 4 处错误相对导入（`.screenplay` → `..screenplay`、`.audio` → `..audio`）
- 修复 `revive/` 跨 stage 相对导入（stage3→stage2、stage4→stage3、stage5→stage4）
- 重建 `revive/pipeline/`（director + checkpoint）与 `revive/config.py`、`revive/eval.py`（迁移时遗漏）
- 恢复 `config/settings.yaml` 为 video 管线配置（曾被 revive 配置覆盖，revive 配置归位至 `revive_settings.yaml`）
- `ComfyClient` 补齐 `free_memory()`（/free 端点）与 `upload_video()`，修复 stage5 ComfyUI 真实路径崩溃
- stage1 分割：YOLO 检出 0 物体时降级 mock（生产合理降级路径）
- `pyproject.toml` CLI 入口改为真实存在的 `oilpaint-video` / `oilpaint-revive`
- tests/ 全部旧导入（oilpaint/oilrev → oilpainting_studio.video/revive）与 patch 目标迁移

### 移除

- `bak/` 目录 291 个文件从 git 索引移除（约 423MB 旧项目存档，本地保留）
- 13 个 LaTeX 编译中间产物从 git 索引移除

### 子项目版本

- DotArtKit: v1.0.0
- OilPaintingStudio: v1.0.0
- GestureCoach: v0.1.0 (submodule @ ecfda82)

---

## [1.0.0] — 2026-10-14

### 新增

#### 文档套件
- 创建 `docs/` 文档目录，包含完整的 monorepo 文档体系
- `docs/README.md` — 文档导航索引
- `docs/architecture.md` — 架构总览：子项目关系图、技术栈矩阵、各项目架构要点、学术产出汇总
- `docs/VERSIONING.md` — 语义化版本号规范、版本更新流程、发布检查清单
- `docs/CHANGELOG.md` — 本文件，版本变更记录
- `docs/CONTRIBUTING.md` — 贡献与维护指南
- 根目录 `VERSION` 文件 — monorepo 版本号

#### 模块参考文档
- `docs/modules/aiforpolkadotsart.md` — AIforPolkaDotsArt 逐文件功能说明
  - stippling.py (Voronoi stippling 核心)、kusama.py (基础渲染器)、depth_kusama.py (深度感知渲染器)
  - gen_test_images.py、run_demo.py、run_depth_demo.py、run_param_test.py
- `docs/modules/gesturecoach.md` — GestureCoach 逐文件功能说明
  - 核心管线 (types/config/tracking/features/dtw/diagnosis/feedback/template/pipeline/api)
  - 并行视觉路径 (detection_types/detection/segmentation/toolhand)
  - 阶段识别 (stages)、合成数据 (synth/synth_frame/synth_stages)
  - data_collection/ 目录、前端、测试
- `docs/modules/oilpaintingrevive.md` — OilPaintingRevive 逐文件功能说明
  - 四模块管线 (stage1-stage5)、config/schemas、cli、comfy、pipeline、utils
- `docs/modules/oilpaintingvideo.md` — OilPaintingVideo 逐文件功能说明
  - 三阶段管线 (screenplay/pipeline)、config/llm_client、audio、cli、comfy
  - mesh2video 扩展模块 (camera/renderer/animation/pipeline)

### 变更

- 无代码变更，本次为纯文档发布

---

## 版本历史模板

后续版本请按以下模板添加条目：

```markdown
## [X.Y.Z] — YYYY-MM-DD

### 新增
- 新功能、新文件、新模块

### 变更
- 对现有功能的修改

### 修复
- 缺陷修复

### 移除
- 已移除的功能或文件

### 子项目版本
- DotArtKit: vX.Y.Z
- OilPaintingStudio: vX.Y.Z
- OilPaintingPlatform: vX.Y.Z
- TechLearnStudio: vX.Y.Z
- GestureCoach: vX.Y.Z
```

### 变更分类说明

| 分类 | 说明 |
|------|------|
| **新增** | 新增的功能、文件、模块或文档 |
| **变更** | 对现有功能的修改、重构或优化 |
| **修复** | 缺陷修复 |
| **移除** | 已移除的功能、文件或模块 |

### 子项目变更速记

当子项目有版本变更时，在对应版本条目下添加"子项目版本"小节，列出各子项目的当前版本号。

---

## 链接

- [版本管理策略](VERSIONING.md)
- [贡献与维护指南](CONTRIBUTING.md)
- [架构总览](architecture.md)
