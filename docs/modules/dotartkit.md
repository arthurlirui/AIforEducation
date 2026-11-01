# DotArtKit — 模块与文件参考

> **路径**: `DotArtKit/` ｜ **版本**: 1.0.0 ｜ **依赖**: Python ≥ 3.11, NumPy, Pillow（必需）；SciPy / ultralytics / PyTorch（可选分级）

## 项目简介

统一波点艺术生成器，把原 `AIforPolkaDotsArt`（草间弥生专攻 + 深度感知）与 `AIforDotArt`（多流派纯数学）整合为单一 Python 包，提供 8 种波点艺术生成模式。分层架构：底层算子 (`ops`) → 流派渲染器 (`styles`) → 统一 API (`api`) → CLI。

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
| `learned` | 可学习映射 | + torch | CNN 替代固定幂律 (IJCAI 论文) |

> 注意：`learned` 尚未注册进 `api.py` 的 MODES 表，当前只能作为库使用（`dotartkit/learned.py`），CLI 调用会 KeyError——待办项。

## 文件结构

```
DotArtKit/
├── dotartkit/
│   ├── __init__.py         # 包入口: 导出 + has_scipy/has_ultralytics/has_torch 探测
│   ├── __main__.py         # python -m dotartkit 入口
│   ├── api.py              # MODES 注册表 + generate() 统一入口
│   ├── cli.py              # dotart list / generate / demo 三命令
│   ├── learned.py          # 可学习点大小映射 (torch 可选)
│   ├── ops/                # 底层算子
│   │   ├── voronoi.py      # Voronoi + Lloyd 松弛 (scipy 可选, 缺省退化)
│   │   ├── depth.py        # YOLO26 深度+语义 (ultralytics 可选)
│   │   ├── color.py        # 互补色/调色板
│   │   └── grid.py         # 网格哈希
│   └── styles/             # 8 个流派渲染器
│       ├── seurat.py / benday.py / warp.py / vogel.py      # 纯 numpy 四流派
│       ├── stipple_pure.py # 纯 numpy 点绘
│       └── kusama_basic.py / kusama_depth.py               # 草间弥生两版
├── scripts/                # demo 与实验脚本
│   ├── run_demos.py        # 冒烟测试式批量 demo
│   ├── gen_test_images.py  # 合成测试图
│   ├── run_param_test.py   # 参数扫描
│   ├── run_ijcai_experiments.py  # 论文实验
│   └── exp_figures.py      # 论文图表
├── inputs/                 # 测试输入图 (cat.jpg 等)
├── models/                 # YOLO26 权重 (yolo26x-depth.pt / yolo26x-sem.pt)
├── outputs/                # 生成产物
├── paper/                  # IJCAI'26 论文 "Spatially-Aware Stippling"
└── docs/设计文档.md         # 设计文档 (含测试策略)
```

## 依赖关系图

```
ops/voronoi.py (核心点放置)
ops/depth.py (YOLO26 深度/语义)
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
learned.py (独立可选扩展, 未入 MODES)
```

---

## 逐文件说明

### api.py — 统一入口

**职责**: `MODES` 字典注册各流派渲染器，`generate(mode, image, **params)` 分发调用并保存产物。

| 组件/函数 | 说明 |
|-----------|------|
| `MODES` | 模式名 → 渲染函数 的注册表 |
| `generate()` | 统一生成入口：校验模式、调渲染器、落盘输出 |

**依赖**: ops, styles ｜ **被调用方**: cli.py

### cli.py — 命令行接口

**职责**: click 三命令 `list`（列模式）/ `generate`（单图生成）/ `demo`（批量演示）。pyproject 注册 `dotart` 脚本入口。

### ops/voronoi.py — Voronoi 点放置核心

**职责**: Secord Weighted Voronoi Stippling + Lloyd 松弛。scipy 缺失或二进制不兼容时退化（无 Lloyd），通过 `has_scipy` 探测。

> 已知问题: 本机 scipy 2.x 与 numpy 二进制不兼容，kusama_basic 长期走退化分支且无显式报警——待办项。

### ops/depth.py — YOLO26 深度与语义

**职责**: 调 ultralytics YOLO26 做单目深度估计 + 语义分割，供 kusama_depth 三层架构使用。ultralytics 缺失时抛清晰 ImportError。

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

**职责**: 用小型 CNN 替代固定幂律的深度→半径映射（IJCAI 论文扩展）。torch 缺失时定义占位类，实例化抛 ImportError。

## 测试

- **正式 pytest 测试**: 暂无（待办：`tests/` 目录）
- **冒烟**: `python scripts/run_demos.py`（纯 numpy 模式全覆盖；kusama_depth 需 conda GPU 环境）
- **CLI 冒烟**: `python -m dotartkit list` / `python -m dotartkit generate seurat inputs/cat.jpg`

## 论文

`paper/` — "Spatially-Aware Stippling"（IJCAI'26 Arts 方向，10pp 已编译，`main.pdf`）。
