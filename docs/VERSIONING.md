# 版本管理策略

> 本文档定义 AIforEducation monorepo 的版本号规范、更新流程和发布检查清单。

## 1. 版本号规范

本项目采用 **语义化版本** (Semantic Versioning 2.0.0) 规范：

```
MAJOR.MINOR.PATCH
```

### 1.1 版本号含义

| 位 | 名称 | 何时递增 | 示例 |
|----|------|---------|------|
| MAJOR | 主版本号 | 不兼容的 API/架构变更 | 1.0.0 → 2.0.0 |
| MINOR | 次版本号 | 向后兼容的新功能 | 1.0.0 → 1.1.0 |
| PATCH | 修订号 | 向后兼容的缺陷修复 | 1.0.0 → 1.0.1 |

### 1.2 初始开发阶段

当前所有子项目处于 `0.x.y` 初始开发阶段：

- `0.x.y` 中的 `x` 为 0 表示核心 API 可能随时变动
- 子项目当前版本：
  - AIforPolkaDotsArt: `1.0.0` (功能已稳定，含深度感知版)
  - GestureCoach: `0.1.0` (原型阶段)
  - OilPaintingRevive: `0.1.0` (管线已建通，mock 模式完整)
  - OilPaintingVideo: `0.1.0` (管线已建通，mock 模式完整)

### 1.3 Monorepo 版本与子项目版本

- **Monorepo 版本** 记录在根目录 `VERSION` 文件中，代表文档套件和整体项目状态
- **子项目版本** 记录在各子项目的 `__init__.py` (`__version__`) 或 `pyproject.toml` (`version`) 中
- 子项目版本独立演进，monorepo 版本在子项目版本变更时同步更新

## 2. 版本号管理规则

### 2.1 何处记录版本号

| 位置 | 文件 | 格式 |
|------|------|------|
| Monorepo | `VERSION` | `1.0.0` (纯版本号，单行) |
| AIforPolkaDotsArt | 无 `__version__`，记录在 `docs/CHANGELOG.md` | — |
| GestureCoach | `gesturecoach/__init__.py` → `__version__` | `"0.1.0"` |
| OilPaintingRevive | `src/oilrev/__init__.py` → `__version__` + `pyproject.toml` → `version` | `"0.1.0"` |
| OilPaintingVideo | `src/oilpaint/__init__.py` → `__version__` + `pyproject.toml` → `version` | `"0.1.0"` |

### 2.2 版本更新流程

每次发布新版本时，按以下步骤操作：

1. **确定版本号**：根据变更内容决定递增 MAJOR/MINOR/PATCH
2. **更新版本号文件**：
   - 更新 `VERSION` 文件中的 monorepo 版本
   - 更新变更子项目的 `__init__.py` 和/或 `pyproject.toml`
3. **更新 CHANGELOG.md**：在 `docs/CHANGELOG.md` 顶部添加新版本条目
4. **更新文档**：如果模块文件有变更，同步更新 `docs/modules/` 下对应文档
5. **运行测试**：执行各子项目测试确保不破坏现有功能
6. **提交**：`git commit -m "release: vX.Y.Z"` (或记录变更)

### 2.3 预发布版本

如需标记预发布版本，使用后缀：

```
1.0.0-alpha.1    # 早期预览
1.0.0-beta.1     # 功能完整但可能有缺陷
1.0.0-rc.1       # 发布候选
```

## 3. 发布检查清单

发布新版本前，逐项确认：

- [ ] 确定版本号 (MAJOR/MINOR/PATCH)
- [ ] 更新 `VERSION` 文件
- [ ] 更新变更子项目的 `__version__` / `pyproject.toml`
- [ ] 在 `docs/CHANGELOG.md` 添加新版本条目 (日期 + 变更分类)
- [ ] 更新 `docs/modules/` 下的模块参考 (如有文件变更)
- [ ] 更新 `docs/architecture.md` (如有架构变更)
- [ ] 更新 `docs/README.md` 中的版本号和最后更新日期
- [ ] 运行子项目测试 (GestureCoach: `pytest tests/`, OilPaintingRevive/Video: `pytest`)
- [ ] 检查依赖版本是否需要更新

## 4. 版本历史摘要

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0.0 | 2026-10-14 | 文档套件初始发布；四个子项目完整文档化 |

详见 [CHANGELOG.md](CHANGELOG.md)。
