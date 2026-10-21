# AIforPolkaDotsArt — 草间弥生风格波点艺术生成器

从输入图像生成 Yayoi Kusama（草间弥生）风格的波点艺术。包含两套生成系统：

1. **基础版**（`stippling.py` + `kusama.py`）：基于 Secord Weighted Voronoi Stippling，通过亮度密度调制点大小
2. **深度感知版**（`depth_kusama.py`）：集成 YOLO26 单目深度估计 + 语义分割，用场景深度调制波点大小（近=大点，远=小点），实现三维深度感知的波点艺术

## 快速开始

### 基础版

```bash
python gen_test_images.py          # 生成合成测试图像
python run_demo.py                 # 跑完整 demo（6 张图 × 不同配色）
python kusama.py inputs/pumpkin.png -o outputs/my_pumpkin.png --palette yellow_black
```

### 深度感知版

```bash
# 激活 conda 环境
conda activate polkadot-art

# 单张处理
python depth_kusama.py inputs/pumpkin.jpg -o outputs/depth_pumpkin.png \
    --palette black_red --r-max 14 --alpha 1.5 --sigma 0.15 --save-intermediates

# 批量 demo（6 种配色）
python run_depth_demo.py
```

## 深度感知版核心算法

### 数学公式

**深度→半径映射**（核心创新）：

```
r(x,y) = r_min + (r_max - r_min) · (1 - d̂(x,y))^α · (1 + ε)
```

- `d̂(x,y) ∈ [0,1]`：归一化深度（0=最近，1=最远）
- `α`：深度衰减指数（>1 强深度强调，<1 温和渐变）
- `ε ~ N(0, σ²)`：高斯噪声，模拟手绘有机变化

**复合密度场**：

```
ρ(x,y) = (1 - d̂)^β · γ(I_gray)
```

深度密度 × 亮度密度的乘积，驱动 Voronoi 点分布。

### 三层架构

| 层 | 半径范围 | 功能 |
|---|---|---|
| Fine stipple | 1-5 px | 密集小点，深度调制密度，基础纹理 |
| Depth-emphasis | 7-15 px | 仅近景区域的大点，承载深度信号 |
| Edge + Background | 1-1.3 px | Canny 边缘增强 + horror vacui 背景填充 |

**跨层重叠剪枝**：移除落入大点范围内的细点，防止粘连成块。

### 语义感知双色渲染

- YOLO26x-sem 语义分割 → 前景/背景分类
- 前景点用 `fg_dot` 颜色，背景点用 `bg_dot` 颜色
- 6 种高饱和草间配色方案

### CLI 参数

```bash
python depth_kusama.py <input> [-o output] [options]

主要参数：
  --depth-model     YOLO26 深度模型路径（默认 yolo26x-depth.pt）
  --sem-model       YOLO26 语义分割模型路径（默认 yolo26x-sem.pt）
  --device          GPU 编号（默认 0）或 cpu
  --palette         配色方案（black_red / yellow_black / white_red / magenta_cyan / red_yellow）
  --n-points        初始采样点数（默认 20000）
  --r-max           最大点半径（默认 18，推荐 14）
  --alpha           深度衰减指数（默认 1.5）
  --beta            深度密度指数（默认 0.6）
  --sigma           半径随机噪声标准差（默认 0.15）
  --overlap-gap     点间距（默认 2.5，推荐 4.0）
  --no-multi-scale  关闭深度强调层
  --no-semantic     关闭语义感知双色
  --save-intermediates  保存深度图/分割图/密度场可视化
```

## 文件结构

```
AIforPolkaDotsArt/
├── stippling.py           # Voronoi stippling 核心算法
├── kusama.py              # 基础版草间风格化 pipeline
├── depth_kusama.py        # 深度感知版 pipeline（YOLO26 + 三层架构）
├── gen_test_images.py     # 合成测试图像生成
├── run_demo.py            # 基础版批量 demo
├── run_depth_demo.py      # 深度感知版批量 demo
├── yolo26x-depth.pt       # YOLO26 深度估计模型
├── yolo26x-sem.pt         # YOLO26 语义分割模型
├── inputs/                # 测试输入图像
├── outputs/               # 生成结果
│   └── depth_demo/        # 深度感知版输出 + 中间可视化
├── paper/                 # IJCAI'26 论文初稿
│   ├── main.tex           # 主文件
│   ├── sec/               # 各章节
│   ├── references.bib     # 参考文献
│   ├── figures/           # 论文插图
│   └── main.pdf           # 编译输出（10 页）
├── 调研报告_草间弥生风格波点艺术生成.md  # 技术调研报告
└── references.bib         # 原始参考文献
```

## 质量指标（深度感知版）

| 图像 | 配色 | 连通域 | 最大块占比 | 覆盖率 | 半径范围 | 前景比 |
|---|---|---|---|---|---|---|
| Pumpkin | yellow_black | 3037 | 0.20% | 22.2% | 0.5-15.4 | 66.1% |
| Pumpkin | black_red | 3037 | 0.20% | 22.2% | 0.5-15.4 | 66.1% |
| Cat | black_red | 2385 | 0.32% | 27.8% | 0.7-15.4 | 6.9% |
| Cat | magenta_cyan | 2500 | 0.23% | 27.3% | 0.7-15.4 | 6.9% |
| Pepper | white_red | 1142 | 0.36% | 16.9% | 0.7-13.2 | 59.4% |
| Pepper | red_yellow | 1142 | 0.36% | 16.9% | 0.7-13.2 | 59.4% |

## 依赖

### 基础版
```
Python >= 3.9, numpy, scipy, opencv-python, pillow
```

### 深度感知版
```bash
conda create -n polkadot-art python=3.11
conda activate polkadot-art
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install ultralytics scipy opencv-python matplotlib
```

## 论文

`paper/` 文件夹包含 IJCAI'26 艺术论文板块投稿初稿：

- **标题**: Depth-Aware Polka Dot Art Generation: Integrating Monocular Depth Estimation with Weighted Voronoi Stippling for Yayoi Kusama–Style Non-Photorealistic Rendering
- **编译**: `cd paper && xelatex main.tex && bibtex main && xelatex main.tex && xelatex main.tex`
- **输出**: 10 页 PDF，含公式、算法、表格、插图
