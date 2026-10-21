# DotArtKit — 统一波点艺术生成器

把原 `AIforPolkaDotsArt` (草间弥生专攻 + 深度感知) 与 `AIforDotArt` (多流派纯数学) 两个项目整合为单一 Python 包, 提供 8 种波点艺术生成模式.

## 8 种模式一览

| 模式 | 流派 | 依赖 | 简述 |
|------|------|------|------|
| `seurat` | 点彩派 | 纯 numpy | Chevreul 互补色面积混合 + Bayer 抖动 |
| `benday` | Ben-Day 半调 | 纯 numpy | Lichtenstein 四色波普, `r = λ·sqrt((1-g)/π)` |
| `warp` | Vasarely 欧普 | 纯 numpy | Vega 凸起, 径向变形场 |
| `stipple` | Secord 点绘 | 纯 numpy | 密度拒绝采样 + GridHash, `r ∝ ρ^(-1/2)` |
| `vogel` | 黄金角叶序 | 纯 numpy | Vogel 螺线 `r_n=c√n, θ_n=n·137.508°` |
| `kusama_basic` | 草间弥生 (基础) | numpy + scipy (退化) | Voronoi Lloyd + 多层 + horror vacui |
| `kusama_depth` | 草间弥生 (深度) | ultralytics + GPU | YOLO26 深度 + 三层架构 + 语义双色 |
| `learned` (扩展) | 可学习映射 | + torch | CNN 替代固定幂律 (IJCAI 论文) |

## 快速开始

### 安装

```bash
cd DotArtKit
pip install -e .                  # 核心依赖 (numpy + Pillow + opencv)
pip install -e ".[scipy]"         # + Voronoi Lloyd 松弛
pip install -e ".[all]"           # + 深度感知 + 可学习 + 实验图表
```

### Python API

```python
from dotartkit import generate
from PIL import Image

img = Image.open("inputs/pumpkin.jpg").convert("RGB")

# 纯 numpy 流派 (任意环境)
generate("seurat", img).save("out_seurat.png")
generate("benday", img, use_pop_palette=True).save("out_benday.png")
generate("kusama_basic", img, palette="yellow_black", n_points=20000).save("out_kusama.png")

# 深度感知 (需 conda activate polkadot-art)
generate("kusama_depth", img, palette="black_red",
         depth_model_path="models/yolo26x-depth.pt",
         sem_model_path="models/yolo26x-sem.pt",
         alpha=1.5, sigma=0.15, r_max=14.0).save("out_depth.png")
```

### 命令行

```bash
# 列出所有模式
python -m dotartkit list

# 单张生成
python -m dotartkit generate kusama_basic inputs/pumpkin.jpg -o outputs/out.png --palette yellow_black
python -m dotartkit generate seurat inputs/cat.jpg -o outputs/seurat.png --seed 42

# 批量 demo (默认全部纯 numpy 模式)
python -m dotartkit demo --input-dir inputs --output-dir outputs/demo

# 深度感知 (需激活 polkadot-art)
conda activate polkadot-art
python -m dotartkit generate kusama_depth inputs/pumpkin.jpg -o outputs/depth.png \
    --palette black_red --r-max 14 --alpha 1.5 --sigma 0.15 --device 0
```

## 目录结构

```
DotArtKit/
├── dotartkit/                 # 主包
│   ├── api.py                 # 统一 generate() + 模式注册表
│   ├── cli.py                 # CLI: list / generate / demo
│   ├── learned.py             # 可学习深度→半径映射 (可选 torch)
│   ├── ops/                   # 底层算子
│   │   ├── color.py           # RGB/HSV、亮度、采样、绘制、调色板
│   │   ├── grid.py            # GridHash O(1) 近邻查询
│   │   ├── voronoi.py         # Secord WCVT stippling (scipy 可选)
│   │   └── depth.py           # YOLO26 深度/语义 (ultralytics 可选) + 纯 numpy 算法
│   └── styles/                # 流派渲染器 (7 个)
├── docs/
│   ├── 设计文档.md             # 整合项目设计文档 (核心)
│   ├── 调研报告_草间弥生风格波点艺术生成.md
│   ├── 调研报告_波点艺术流派与数学原理.md
│   └── references.bib
├── scripts/                   # demo / 实验 / 论文图
├── inputs/                    # 共享测试图 (cat / pumpkin / pepper)
├── outputs/                   # 生成结果
├── models/                    # YOLO26 权重 (yolo26x-depth.pt / yolo26x-sem.pt)
├── paper/                     # IJCAI'26 论文
├── pyproject.toml
└── requirements.txt
```

## 依赖分级

| 层级 | 依赖 | 缺失时行为 |
|------|------|-----------|
| 核心 | numpy, Pillow, opencv-python | 必需 |
| scipy | scipy.spatial | `has_scipy()=False`; kusama_basic 跳过 Lloyd, 退化到 O(n²) 剪枝 |
| ultralytics | YOLO26 深度 + 语义 | `has_ultralytics()=False`; kusama_depth 抛 ImportError |
| torch | DepthRadiusNet | `has_torch()=False`; learned 抛 ImportError; 其余流派不受影响 |

查询运行时能力:
```python
import dotartkit
print(dotartkit.has_scipy(), dotartkit.has_ultralytics(), dotartkit.has_torch())
```

## 环境说明

**深度感知模式 (kusama_depth)** 需要单独的 conda 环境:

```bash
conda activate polkadot-art
# Python 3.11, PyTorch 2.5.1+cu121, ultralytics 8.4.175
```

YOLO26 权重已位于 `models/` 目录 (yolo26x-depth.pt 114MB, yolo26x-sem.pt 80MB), 无需下载.

## 文档

- **整合设计文档**: [`docs/设计文档.md`](docs/设计文档.md) — 架构、模块边界、依赖策略、扩展指南
- **草间弥生风格调研**: [`docs/调研报告_草间弥生风格波点艺术生成.md`](docs/调研报告_草间弥生风格波点艺术生成.md)
- **多流派数学原理调研**: [`docs/调研报告_波点艺术流派与数学原理.md`](docs/调研报告_波点艺术流派与数学原理.md)
- **IJCAI'26 论文**: [`paper/main.pdf`](paper/main.pdf) — *Spatially-Aware Stippling: Encoding Scene Depth in Kusama-Style Polka Dot Generation*

## 来源

整合自两个前身项目:
- `AIforPolkaDotsArt/` (2026-10-07 → 10-12) — 草间弥生专攻 + 深度感知 + IJCAI 论文
- `AIforDotArt/` (2026-10-14) — 6 流派纯数学 + 数学原理调研

详细映射见 [设计文档 §6](docs/设计文档.md#6-从原项目到整合包的映射).
