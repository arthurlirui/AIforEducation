# 贡献与维护指南

> 本文档定义 AIforEducation 项目的代码提交约定、文档更新规范和维护检查清单。

## 1. 项目结构约定

```
AIforEducation/
├── AIforPolkaDotsArt/     子项目: 草间弥生波点艺术生成
├── GestureCoach/          子项目: 绘画手势教练
├── OilPaintingRevive/     子项目: 油画复活 (3DGS)
├── OilPaintingVideo/      子项目: 油画风格叙事视频
├── images/                共享名画素材
├── latex/                 共享 LaTeX 论文模板
├── docs/                  项目文档 (本目录)
│   ├── README.md          文档导航
│   ├── architecture.md    架构总览
│   ├── modules/           各子项目模块参考
│   ├── VERSIONING.md      版本管理策略
│   ├── CHANGELOG.md       更新日志
│   └── CONTRIBUTING.md    本文件
└── VERSION                Monorepo 版本号
```

## 2. 代码提交约定

### 2.1 提交信息格式

使用中文或英文，格式为 `类型: 简述`：

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 添加深度感知版 Kusama 渲染器` |
| `fix` | 缺陷修复 | `fix: 修复 DTW 路径越界问题` |
| `docs` | 文档变更 | `docs: 更新 GestureCoach 模块参考` |
| `refactor` | 重构 (无功能变化) | `refactor: 提取 ComfyClient 公共基类` |
| `test` | 测试相关 | `test: 添加 stage2 3DGS 生成测试` |
| `chore` | 构建/工具变更 | `chore: 更新 pyproject.toml 依赖` |
| `release` | 版本发布 | `release: v1.1.0` |

### 2.2 提交范围

- 每次提交应聚焦单一逻辑变更
- 跨子项目的变更应拆分为多次提交
- 文档变更单独提交

## 3. 文档更新规范

### 3.1 何时更新文档

| 触发条件 | 需要更新的文档 |
|---------|---------------|
| 新增/删除/重命名源文件 | 对应子项目的 `docs/modules/*.md` |
| 新增/删除/修改模块间依赖 | `docs/architecture.md` 的依赖关系图 |
| 新增/删除子项目 | `docs/README.md` + `docs/architecture.md` |
| 新增/删除/修改配置项 | 对应子项目的模块参考文档 |
| 新增/删除测试文件 | 对应子项目的模块参考文档 (测试小节) |
| 任何版本号变更 | `VERSION` + `docs/CHANGELOG.md` + `docs/README.md` |
| 新增/删除外部依赖 | `docs/architecture.md` 的技术栈矩阵 |

### 3.2 模块参考文档格式

`docs/modules/*.md` 中的逐文件说明应保持以下结构：

```markdown
#### 文件名 — 一句话职责

**职责**: 详细说明 (1-2 句)

| 组件/函数 | 说明 |
|-----------|------|
| `function_name()` | 功能描述 |

**依赖**: 外部依赖列表
**被调用方**: 哪些文件依赖此文件
```

### 3.3 新增子项目时的检查清单

- [ ] 在 `docs/modules/` 创建新子项目的模块参考文档
- [ ] 在 `docs/README.md` 添加文档导航条目
- [ ] 在 `docs/architecture.md` 添加子项目概览和架构要点
- [ ] 在 `docs/architecture.md` 更新技术栈矩阵和依赖矩阵
- [ ] 在 `docs/CHANGELOG.md` 记录新增

## 4. 测试维护

### 4.1 各子项目测试命令

```bash
# GestureCoach
cd GestureCoach && PYTHONPATH=. pytest tests/ -v

# OilPaintingRevive
cd OilPaintingRevive && pip install -e ".[dev]" && pytest -v

# OilPaintingVideo
cd OilPaintingVideo && pip install -e ".[dev]" && pytest -v

# AIforPolkaDotsArt (无正式测试，使用 demo 验证)
cd AIforPolkaDotsArt && python run_demo.py && python run_depth_demo.py
```

### 4.2 测试维护原则

- 新增功能必须附带测试
- Mock 模式测试优先 (不依赖 GPU/外部服务)
- 测试文件命名: `test_<模块名>.py` (单元) 或 `test_integration_<场景>.py` (集成)
- 文档变更不需要测试，但应确保文档中的命令可执行

## 5. 版本发布流程

详细流程见 [VERSIONING.md](VERSIONING.md)。简要步骤：

1. 确定版本号
2. 更新版本号文件 (`VERSION`, 子项目 `__version__`/`pyproject.toml`)
3. 更新 `docs/CHANGELOG.md`
4. 更新 `docs/README.md` 中的版本号和日期
5. 运行测试
6. 提交: `release: vX.Y.Z`

## 6. 维护检查清单 (定期执行)

每月或重大变更后执行：

- [ ] 所有子项目测试通过
- [ ] `docs/modules/*.md` 中的文件列表与实际目录一致
- [ ] `docs/architecture.md` 中的技术栈矩阵与实际依赖一致
- [ ] `VERSION` 文件与 `docs/CHANGELOG.md` 最新条目一致
- [ ] `docs/README.md` 中的版本号和日期已更新
- [ ] 各子项目的 `__version__` / `pyproject.toml` 版本号一致
- [ ] 无遗留的 `__pycache__` / `.egg-info` 被意外追踪

## 7. 常见维护场景

### 场景: 新增一个 Python 文件到 GestureCoach

1. 在 `docs/modules/gesturecoach.md` 的对应分类下添加逐文件说明
2. 如果新文件引入新的外部依赖，更新 `docs/architecture.md` 技术栈矩阵
3. 如果新文件改变了模块依赖关系，更新 `docs/modules/gesturecoach.md` 的依赖关系图
4. 在 `docs/CHANGELOG.md` 记录变更
5. 视变更范围递增版本号

### 场景: 修改 OilPaintingRevive 的配置项

1. 更新 `docs/modules/oilpaintingrevive.md` 中的配置文件说明表格
2. 如果是新增配置项，说明其用途和默认值
3. 在 `docs/CHANGELOG.md` 记录变更

### 场景: 子项目发布新版本

1. 更新子项目的 `__version__` / `pyproject.toml`
2. 更新根目录 `VERSION`
3. 在 `docs/CHANGELOG.md` 添加新版本条目
4. 更新 `docs/README.md` 和 `docs/VERSIONING.md` 中的版本号引用
5. 运行测试确认
