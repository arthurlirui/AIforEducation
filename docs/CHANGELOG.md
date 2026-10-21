# 更新日志 (CHANGELOG)

本文件记录 AIforEducation monorepo 所有版本的变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
- AIforPolkaDotsArt: vX.Y.Z
- GestureCoach: vX.Y.Z
- OilPaintingRevive: vX.Y.Z
- OilPaintingVideo: vX.Y.Z
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
