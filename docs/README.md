# AIforEducation — 项目文档

> **版本**: 1.2.0 ｜ **最后更新**: 2026-11-08 ｜ **文档状态**: 活跃维护

本目录是 AIforEducation monorepo 的统一文档中心，涵盖七个子项目的架构说明、模块与文件级参考、版本管理策略和更新日志。

## 文档导航

| 文档 | 说明 |
|------|------|
| [架构总览](architecture.md) | Monorepo 全局架构、子项目关系图、技术栈总览 |
| [DotArtKit 模块参考](modules/dotartkit.md) | 统一波点艺术生成器（8 流派 + 桌面编辑器 GUI）— 逐文件功能说明 |
| [OilPaintingStudio 模块参考](modules/oilpaintingstudio.md) | 油画动态生成统一包（video + revive/Canvas3D + GUI 工作站 + 桌面 Demo）— 逐文件功能说明 |
| [OilPaintingPlatform 模块参考](modules/oilpaintingplatform.md) | 油画教学 + AI 文生图网站 — 逐文件功能说明 |
| [ArtRealm3D 模块参考](modules/artrealm3d.md) | 艺境 — 世界名画三维沉浸式教学平台 — 逐文件功能说明 |
| [HistorySandbox 模块参考](modules/historysandbox.md) | 读史 — AI 历史教育三维沙盘推演平台 — 逐文件功能说明 |
| [TechLearnStudio 模块参考](modules/techlearnstudio.md) | 可交互网页 PPT 学习平台 — 设计与实现说明 |
| [GestureCoach 模块参考](modules/gesturecoach.md) | 绘画手势教练系统 — 逐文件功能说明 |
| [版本管理策略](VERSIONING.md) | 语义化版本号规范、更新流程、发布检查清单 |
| [更新日志](CHANGELOG.md) | 所有版本的变更记录 |
| [贡献与维护指南](CONTRIBUTING.md) | 文档更新规范、代码提交约定、维护检查清单 |
| [IJCAI 2027 投稿状态](IJCAI2027_submission_status.md) | 三篇在投论文的进度与时间表 |

## 子项目概览

```
AIforEducation/
├── DotArtKit/            统一波点艺术生成器（8 流派 + 桌面编辑器，原 AIforPolkaDotsArt + AIforDotArt）
├── OilPaintingStudio/    油画动态生成统一包（video + revive/Canvas3D + GUI 工作站，原 OilPaintingVideo + OilPaintingRevive）
├── OilPaintingPlatform/  油画教学 + AI 文生图网站（FastAPI + Vue3）
├── ArtRealm3D/           艺境 — 世界名画三维沉浸式教学平台（FastAPI + Vue3 + Three.js）
├── HistorySandbox/       读史 — AI 历史教育三维沙盘推演平台（FastAPI + Vue3 + Three.js）
├── TechLearnStudio/      可交互网页 PPT 学习平台（hyperframes）
├── GestureCoach/         绘画手势教练（submodule，独立仓库）
├── images/               共享名画素材库 (18 张经典油画高清扫描)
├── models/               共享模型权重（YOLO 深度/分割等）
├── latex/                共享 IJCAI 论文 LaTeX 模板与历史论文源码
├── bak/                  重组前旧项目存档（已从 git 移除，仅本地保留）
└── docs/                 本文档目录
```

## 快速定位

- **想了解整个项目？** → 先读 [架构总览](architecture.md)
- **想找某个文件的作用？** → 在对应子项目的模块参考中查找
- **要发布新版本？** → 读 [版本管理策略](VERSIONING.md)，然后更新 [更新日志](CHANGELOG.md)
- **要贡献代码或文档？** → 读 [贡献与维护指南](CONTRIBUTING.md)
