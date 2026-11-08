# 更新日志 (CHANGELOG)

本文件记录 AIforEducation monorepo 所有版本的变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.2.1] — 2026-11-08（第二轮：功能完整性验证）

七个子项目**实启动/实跑功能级验证**（不止单测）：Web 后端逐端点实打、studio/调度器实跑、revive mock 全链路出片、桌面回退逻辑、GestureCoach v2 ingest→diagnose 闭环。全部通过。同日覆盖 DotArtKit 波点再编辑 commit（14c3dd3）。

### 新增（入档）

- **DotArtKit 波点再编辑与局部重映射**（commit 14c3dd3）：4 种新尺寸映射（log/cosine/step/inverse）+ 圆形局部选区（Ctrl+拖拽）重映射编辑与撤销（`remap_radii` region 参数）+ 5 套深度感知艺术配色（共 10 套）+ 88 项新测试
- 文档: dotartkit.md 同步（10 激活 / 10 配色 / remap_radii API / 177 测）

### 修复

- DotArtKit `test_activations` 注册表断言未随 14c3dd3 更新（仍断言 6 个旧激活键）→ 更新为 10 键，177 项全绿

### 验证记录（全部实跑通过）

- ArtRealm3D：3 画作 × 全端点（列表/详情/图层 PNG 服务/quiz 满分判分/400/404/答案不下发）
- HistorySandbox：4 剧本 × 24 幕 narrate + ask + simulate 全命令（hypothetical/move/attack/retreat/alliance）+ 409 结构化路径
- OilPaintingPlatform：styles 12 / teaching 6 / gallery 8 / prompts 28 / providers 6 / mock 生成 + SVG 可取回；未知 provider 静默回退 mock 为设计行为（base.py:135 注释明示）
- TechLearnStudio：实跑 compose→publish→list→frames→search→sandbox（声明为 stub）→anim render（SVG）；M7 调度器 run_once：7 源 → 14 课发布，0 错误
- OilPaintingStudio：revive CLI mock 全链路《星月夜》→ 16 物体 + 120 帧 24fps 可播放视频；GUI 服务端 6 端点 + 前端托管（307→index.html）；桌面 Demo gpu 请求在 mock 机器正确回退
- GestureCoach：v2 API health/styles/palette/knowledge + ingest→diagnose 五轴闭环（合成数据）
- 已知声明项（非 bug）：video TTS 为 stub（audio/tts.py TODO）、TechLearn sandbox 为安全 stub、TripoSplat 集成为 mock 占位、GestureCoach 论文 31 处 TBD 待用户研究

---

## [1.2.0] — 2026-11-08

全仓代码审阅 + 运行 bug 修复 + 文档同步。七个子项目测试套件全绿：DotArtKit 80→177、OilPaintingStudio 85、OilPaintingPlatform 21、ArtRealm3D 22、HistorySandbox 27、TechLearnStudio 46、GestureCoach 332。

### 新增（子项目，2026-11-01 ~ 11-04 落地、本次入档）

- **ArtRealm3D（艺境）** — 世界名画三维沉浸式教学平台：程序化分层渲染（零图片依赖）+ 章节式导览 + 测验闭环，FastAPI + Vue3 + Three.js
- **HistorySandbox（读史）** — AI 历史教育三维沙盘推演平台：4 剧本 × 6 幕 + 世界模型交互推演（机动/进攻/结盟/假想）+ AI 讲解员
- **DotArtKit 桌面波点编辑器 GUI**（tkinter）：polka_document 点列表文档模型 + polka_app 画布编辑（选择/添加/擦除/undo），四类算法注册表（2 深度后端 / 激活 6→10 / 4 滤除 / 配色 5→10）
- **DotArtKit 几何感知特征**：ops/geometry.py 平均曲率场，learned 6 通道 + 曲率损失，depth_curv 激活（E_geo 能量目标）
- **OilPaintingStudio GUI 工作站**：gui/ 服务端（models/store 原子写/tasks GPU 队列/adapters/routers，13 测）+ Vite/Vue3/Three.js 前端七视图
- **OilPaintingStudio 桌面论文 Demo**（pywebview）：desktop/ 三步演示（分割→深度→3D 化身），GPU/CPU/MOCK 三档设备自动回退 + 每步计时
- 文档: `docs/modules/artrealm3d.md`、`docs/modules/historysandbox.md`

### 修复

#### ArtRealm3D
- Tour.vue「开始沉浸导览」不启动章节定时器（核心功能：导览永不自动推进、进度条卡 0%）——startTour 补 resumeTour
- 上一章/下一章手动切章后沿用旧章节剩余时长（定时器不重臂）
- 渲染器星夜图层每颗星周围 160×160 黑方块（halo 无 mask 粘贴，透明区转出纯黑盖住天空）；珍珠光晕同型问题一并修复
- Three.js 纹理缺 `SRGBColorSpace` 标记导致画面偏灰发白
- 测验答案随 `GET /api/masterpieces/{id}` 提前泄露（devtools 可见）——详情不再下发 answer/explain，前端改用判分结果的 per_question
- 少女肖像 `_dark_void` 暗角反向（中心变暗、边缘最亮）
- manifest 缓存损坏导致接口持续 500 且无自愈——改为丢弃重渲染
- `_loadLayers` 异步竞态：页面切走后纹理仍追加进 scene（泄漏）

#### HistorySandbox
- 409 结构化错误提示永远不显示（解析 `JSON.parse(m).message` 漏了 FastAPI 的 `detail` 包装层，友好中文引导形同虚设）
- 同幕号切换剧本时旁白面板不刷新（watch 只盯 stepId），且首挂载不拉取旁白
- 假想推演步显示「第 903 幕 / 6 幕」（900+ 哨兵 id 直接当幕号渲染）
- 推演后 3D 兵力强度条不更新（只在建 mesh 时设 scale）
- 机动模式出现无效「执行推演」按钮（无对应 handler，点击无响应）
- `autoRotate = !v && false` 死表达式导致暂停环视功能永久禁用
- 后端 `_in_area` 只检查势力首个疆域多边形（潜在主场加成误判）
- README 后端端口错误（写 8000，实际 8100）

#### TechLearnStudio（测试基建）
- 根目录 `pytest` 只收集 2/46 个测试（pytest.ini testpaths 漏 backend/tests 与 studio/tests）
- 跨模块 mock 泄漏：test_studio / test_m7 导入期保存 `_post`，收集顺序变化后 teardown 把别的模块的 mock 当"原始值"恢复 → e2e 请求被改写到 TestClient 上 401（改为 setup 时保存/恢复）
- backend 测试复用 studio 统一 DB 导致状态污染（published ≠ draft）——setup 时显式指回自己的临时 DB 并 reinit_engine
- e2e 导入期改 `os.environ` 与其它模块的 settings 单例竞争——新增根 conftest.py 统一测试环境，任何收集顺序 46 测全过

#### DotArtKit
- 编辑器 `_on_wheel` 选中点索引越界（擦除/撤销缩短点列表后滚动滚轮 → IndexError 崩溃）

#### OilPaintingStudio
- PUT /objects/{oid} 传列表 depth_range 时 pydantic 序列化警告（model_copy 不校验，列表未转元组）

### 变更

- 根 `README.md`：五个子项目 → 七个（补 ArtRealm3D / HistorySandbox），快速开始补 GUI/桌面端启动命令
- `docs/README.md`：版本 1.2.0，导航与目录树补两个新项目
- `docs/architecture.md`：项目表/关系图/依赖矩阵/GPU 需求表补 ArtRealm3D + HistorySandbox，测试数刷新
- `docs/modules/dotartkit.md`、`docs/modules/oilpaintingstudio.md`：补 GUI 编辑器 / 几何特征 / GUI 工作站 / 桌面 Demo 章节

### 子项目版本

- DotArtKit: v1.2.0（+GUI 编辑器、几何感知特征、再编辑/局部重映射）
- OilPaintingStudio: v1.1.0（+GUI 工作站、桌面 Demo）
- ArtRealm3D: v0.1.0（新项目）
- HistorySandbox: v0.1.0（新项目）
- GestureCoach: v0.4.0（submodule，v4 手势指令管线 + IJCAI'27 论文返修）

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
