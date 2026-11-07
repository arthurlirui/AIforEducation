# DotArtKit — 模块与文件参考

> **路径**: `DotArtKit/` ｜ **版本**: 1.1.0 ｜ **依赖**: Python ≥ 3.11, NumPy, Pillow, OpenCV（必需）；SciPy / ultralytics / PyTorch（可选分级）｜ **测试**: pytest 80 项全绿

## 项目简介

统一波点艺术生成器，把原 `AIforPolkaDotsArt`（草间弥生专攻 + 深度感知）与 `AIforDotArt`（多流派纯数学）整合为单一 Python 包，提供 8 种波点艺术生成模式 + 桌面波点编辑器 GUI。分层架构：底层算子 (`ops`) → 流派渲染器 (`styles`) → 统一 API (`api`) → CLI / GUI 编辑器。

## 8 种模式

| 模式 | 流派 | 依赖 | 简述 |
|------|------|------|------|
| `seurat` | 点彩派 | 纯 numpy | Chevreul 互补色面积混合 + Bayer 抖动 |
| `benday` | Ben-Day 半调 | 纯 numpy | Lichtenstein 四色波普 |
| `warp` | Vasarely 欧普 | 纯 numpy | Vega 凸起径向变形场 |
| `stipple` | Secord 点绘 | 纯 numpy | 密度拒绝采样 + GridHash |
| `vogel` | 黄金角叶序 | 纯 numpy | Vogel 螺线 |
| `kusama_basic` | 草间弥生 (基础) | numpy + scipy(退化) | Voronoi Lloyd + 多层 + horror vacui |
| `kusama_depth` | 草间弥生 (深度) | ultralytics + GPU | YOLO26 深度 + 三层架构 + 语义双色 |
| `learned` | 可学习映射 | + torch(可回退) | CNN 替代固定幂律 (IJCAI 论文)；已注册进 MODES，torch 缺省回退固定幂律 |

## 文件结构

```
DotArtKit/
├── dotartkit/
│   ├── __init__.py         # 包入口: 导出 + has_scipy/has_ultralytics/has_torch 探测
│   ├── __main__.py         # python -m dotartkit 入口
│   ├── api.py              # MODES 注册表 + generate() 统一入口
│   ├── cli.py              # dotart list / generate / demo 三命令
│   ├── learned.py          # 可学习点大小映射 (torch 可选, 6通道输入含曲率)
│   ├── ops/                # 底层算子
│   │   ├── voronoi.py      # Voronoi + Lloyd 松弛 (scipy 可选, 缺省退化)
│   │   ├── depth.py        # YOLO26 深度+语义 (ultralytics 可选)
│   │   ├── geometry.py     # 平均曲率场 (几何感知特征, 2026-11-04 新增)
│   │   ├── color.py        # 互补色/调色板
│   │   └── grid.py         # 网格哈希
│   ├── styles/             # 8 个流派渲染器
│   │   ├── seurat.py / benday.py / warp.py / vogel.py      # 纯 numpy 四流派
│   │   ├── stipple_pure.py # 纯 numpy 点绘
│   │   └── kusama_basic.py / kusama_depth.py               # 草间弥生两版
│   └── gui/                # 桌面波点编辑器 (tkinter, 2026-11-04 新增)
│       ├── __main__.py     # py -m dotartkit.gui 入口
│       ├── polka_document.py  # 核心文档模型 (不依赖 tkinter, 可独立测试)
│       └── polka_app.py    # 主窗口 + CanvasView 画布交互
├── scripts/                # demo 与实验脚本
│   ├── run_demos.py        # 冒烟测试式批量 demo
│   ├── gen_test_images.py  # 合成测试图
│   ├── run_param_test.py   # 参数扫描
│   ├── run_ijcai_experiments.py  # 论文实验
│   ├── run_gui_e2e.py      # GUI 无头端到端脚本 (E2E 验证用)
│   └── exp_figures.py      # 论文图表
├── tests/                  # pytest 测试套件 (80 项)
│   ├── test_smoke.py       # 8 模式冒烟 + API/CLI
│   ├── test_geometry.py    # 曲率场算子 (263 行)
│   └── test_gui_polka.py   # 文档模型 + GUI 逻辑 (317 行)
├── inputs/                 # 测试输入图 (cat.jpg 等)
├── models/                 # YOLO26 权重 (yolo26x-depth.pt / yolo26x-sem.pt)
├── outputs/                # 生成产物
├── paper/                  # IJCAI'26 论文 "Spatially-Aware Stippling"
└── docs/设计文档.md + 波点编辑器设计文档.md
```

## 依赖关系图

```
ops/voronoi.py (核心点放置)
ops/depth.py (YOLO26 深度/语义)
ops/geometry.py (平均曲率场)
ops/color.py (调色)
      │
      ▼
styles/seurat|benday|warp|stipple|vogel|kusama_basic|kusama_depth
      │
      ▼
api.py (MODES 注册表 → generate())
      │
      ▼
cli.py / __main__.py  →  dotart CLI
learned.py (已入 MODES; torch 可选, 6 通道输入含曲率)

gui/polka_document.py (点列表文档模型: 图像+中间场+点+undo)
      │
      ▼
gui/polka_app.py (tkinter: 画布缩放平移 + 选择/添加/擦除)
```

---

## 逐文件说明

### api.py — 统一入口

**职责**: `MODES` 字典注册各流派渲染器（含 `learned`），`generate(mode, image, **params)` 分发调用并保存产物。

### cli.py — 命令行接口

**职责**: click 三命令 `list`（列模式）/ `generate`（单图生成）/ `demo`（批量演示）。pyproject 注册 `dotart` 脚本入口。

### ops/voronoi.py — Voronoi 点放置核心

**职责**: Secord Weighted Voronoi Stippling + Lloyd 松弛。scipy 缺失或二进制不兼容时退化（无 Lloyd），通过 `has_scipy` 探测。

> 已知问题: 本机 scipy 2.x 与 numpy 二进制不兼容，kusama_basic 长期走退化分支且无显式报警——待办项。

### ops/depth.py — YOLO26 深度与语义

**职责**: 调 ultralytics YOLO26 做单目深度估计 + 语义分割，供 kusama_depth 三层架构与 GUI 编辑器深度后端使用。ultralytics 缺失时抛清晰 ImportError。含 `DEPTH_PALETTES`（5 套配色）、`normalize_depth_foreground`（前景感知归一化）。

### ops/geometry.py — 几何感知特征 (2026-11-04 新增)

**职责**: `mean_curvature(d_norm)` 从深度图估计**符号化平均曲率场** κ，为可学习映射提供几何特征。learned 模型 6 通道输入（深度/亮度/密度/前景 + κ + |∇κ|），训练加曲率一致性损失；GUI 编辑器新增 `curvature`（纯曲率对照）与 `depth_curv`（E_geo 能量目标：深度 × 凸面增益 × 凹面抑制）两个激活函数。相关性验证：corr(r, κ) 从 0.009 提升到 0.062。

### ops/color.py — 调色

**职责**: 互补色对构造（Chevreul）、流派调色板定义。

### ops/grid.py — 网格哈希

**职责**: 空间网格哈希，加速近邻查询（stipple 拒绝采样用）。

### styles/seurat.py — 点彩派

**职责**: 亮度→点密度，互补色对按面积混合模拟光学调色，Bayer 抖动处理过渡。

### styles/benday.py — Ben-Day 半调

**职责**: 四色波普网点，灰度→网点半径 `r = λ·sqrt((1-g)/π)`。

### styles/warp.py — Vasarely 欧普

**职责**: Vega 凸起效果的径向变形场扭曲规则点阵。

### styles/vogel.py — 黄金角叶序

**职责**: Vogel 螺线 `r_n=c√n, θ_n=n·137.508°` 的向日葵籽排布。

### styles/stipple_pure.py — 纯 numpy 点绘

**职责**: 密度拒绝采样 + GridHash 的 Secord 风格点绘，无 scipy 依赖。

### styles/kusama_basic.py — 草间弥生基础版

**职责**: Voronoi Lloyd + 亮度密度调制 + 多层波点 + Canny 边缘 + horror vacui 背景填充。

### styles/kusama_depth.py — 草间弥生深度版（论文核心）

**职责**: 深度→点半径映射、三层架构（精细点层+深度强调层+边缘层）、前景感知深度归一化、语义双染色。

### learned.py — 可学习点映射

**职责**: 用小型 CNN 替代固定幂律的深度→半径映射（IJCAI 论文扩展）。torch 缺失时回退固定幂律。**已注册进 MODES**，CLI 可直接 `dotart generate learned`。

### gui/polka_document.py — 波点文档模型 (核心层)

**职责**: 不依赖 tkinter 的文档模型，可独立使用与测试。维护：输入图像 → 中间产物（深度图 d_norm / 密度场 density / 前景掩码 fg_mask / 曲率场 κ）→ **点列表（唯一事实来源）** → undo/redo 编辑历史。

| 组件 | 说明 |
|------|------|
| `DEPTH_BACKENDS` | 2 个深度后端: yolo26 (GPU) / luminance (亮度伪深度, 零模型) |
| `ACTIVATIONS` | 6 个深度→半径激活: power / linear / sigmoid / sqrt / curvature / depth_curv |
| `FILTERS` | 4 个滤除算法: none / overlap / min_dist / density |
| `PolkaDocument` | load_image → ensure_depth → generate → 编辑操作 → render |
| 编辑 API | add_dot / delete_dot / delete_dots_in_circle / move_dot / resize_dot / begin_edit+end_edit（拖拽合并一次历史） |
| 生成管线 | 深度估计与采样解耦——换激活函数不重跑深度；曲率场缓存复用 |

### gui/polka_app.py — 桌面编辑器 (tkinter)

**职责**: 主窗口（工具栏 + 左参数面板 + 右画布 + 状态栏）。CanvasView 提供缩放/平移/滚轮改半径/右键平移；三工具：选择/移动（V）、添加（A，Shift=背景色）、擦除（E，拖动连续擦除）。

**关键实现**: 生成在后台线程（tkinter 变量非线程安全——UI 线程一次性抓参数快照，worker 不触碰 tkinter，UI 轮询结果）；渲染缓存 `_render_dirty` 标记避免每次编辑全量重绘。

> 踩坑记录: tkinter 变量线程不安全（参数快照+轮询）；`winfo_width` 未布局时返回 1（fit_image 兜底+延迟重试）；Combobox 无 command 事件（用 textvariable trace）。

## 测试

```bash
cd DotArtKit && py -m pytest tests -q          # 80 项全绿
py -m dotartkit list                            # CLI 冒烟
py -m dotartkit.gui                             # 启动桌面编辑器
py scripts/run_gui_e2e.py                       # GUI 无头 E2E
```

## 论文

`paper/` — "Spatially-Aware Stippling"（IJCAI'26 Arts 方向，9pp；2026-11-03 Crossref 逐条核验 bib，2026-11-04 abstract/intro/related 压缩重写去 AI 腔）。
