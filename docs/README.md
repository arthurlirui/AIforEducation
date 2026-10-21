# AIforEducation — 项目文档

> **版本**: 1.0.0 ｜ **最后更新**: 2026-10-14 ｜ **文档状态**: 活跃维护

本目录是 AIforEducation monorepo 的统一文档中心，涵盖四个子项目的架构说明、模块与文件级参考、版本管理策略和更新日志。

## 文档导航

| 文档 | 说明 |
|------|------|
| [架构总览](architecture.md) | Monorepo 全局架构、子项目关系图、技术栈总览 |
| [AIforPolkaDotsArt 模块参考](modules/aiforpolkadotsart.md) | 草间弥生风格波点艺术生成 — 逐文件功能说明 |
| [GestureCoach 模块参考](modules/gesturecoach.md) | 绘画手势教练系统 — 逐文件功能说明 |
| [OilPaintingRevive 模块参考](modules/oilpaintingrevive.md) | 油画复活 — 静态油画 → 3DGS → 动态视频 — 逐文件功能说明 |
| [OilPaintingVideo 模块参考](modules/oilpaintingvideo.md) | 油画风格叙事短片生成 — 逐文件功能说明 |
| [版本管理策略](VERSIONING.md) | 语义化版本号规范、更新流程、发布检查清单 |
| [更新日志](CHANGELOG.md) | 所有版本的变更记录 |
| [贡献与维护指南](CONTRIBUTING.md) | 文档更新规范、代码提交约定、维护检查清单 |

## 子项目概览

```
AIforEducation/
├── AIforPolkaDotsArt/     草间弥生波点艺术生成 (stippling + depth-aware)
├── GestureCoach/          绘画过程手势诊断与反馈系统
├── OilPaintingRevive/     静态油画 → 3D 高斯泼溅 → 线稿引导重排 → 动态视频
├── OilPaintingVideo/      LLM 剧本 → ComfyUI 油画关键帧 → I2V 视频 → ffmpeg 剪辑
├── images/                共享名画素材库 (18 张经典油画高清扫描)
├── latex/                 共享 IJCAI'26 论文 LaTeX 模板与论文源码
└── docs/                  本文档目录
```

## 快速定位

- **想了解整个项目？** → 先读 [架构总览](architecture.md)
- **想找某个文件的作用？** → 在对应子项目的模块参考中查找
- **要发布新版本？** → 读 [版本管理策略](VERSIONING.md)，然后更新 [更新日志](CHANGELOG.md)
- **要贡献代码或文档？** → 读 [贡献与维护指南](CONTRIBUTING.md)
