# AIforPolkaDotsArt — 模块与文件参考

> **路径**: `AIforPolkaDotsArt/` ｜ **版本**: 1.0.0 ｜ **依赖**: Python ≥ 3.11, NumPy, SciPy, OpenCV, PyTorch + ultralytics (深度版)

## 项目简介

将输入图片转化为草间弥生 (Yayoi Kusama) 风格的波点艺术。包含两个系统：

1. **基础版** — Voronoi stippling + 亮度密度调制，纯 CPU 运行
2. **深度感知版** — 集成 YOLO26 单目深度估计与语义分割，点大小编码场景深度，前景/背景双染色

## 文件结构

```
AIforPolkaDotsArt/
├── stippling.py            # 共享计算核心: Weighted Voronoi Stippling
├── kusama.py               # 基础版 Kusama 渲染器
├── depth_kusama.py         # 深度感知版 Kusama 渲染器 (论文核心)
├── gen_test_images.py      # 合成测试图片生成器
├── run_demo.py             # 基础版批量 demo 运行器
├── run_depth_demo.py       # 深度感知版批量 demo 运行器
├── run_param_test.py       # 参数扫描 + 消融实验
├── README.md               # 中文项目说明
├── 调研报告_草间弥生风格波点艺术生成.md  # 技术调研报告
├── inputs/                 # 输入图片目录
├── outputs/                # 输出图片目录
├── paper/                  # IJCAI'26 论文 LaTeX 源码
├── yolo26x-depth.pt        # YOLO26 深度估计模型权重
└── yolo26x-sem.pt          # YOLO26 语义分割模型权重
```

## 依赖关系图

```
stippling.py  (核心: Voronoi stippling, NumPy + SciPy)
   ├── kusama.py  (基础渲染器, OpenCV)
   │     └── run_demo.py
   │     └── gen_test_images.py  (独立, 生成输入图片)
   └── depth_kusama.py  (深度感知渲染器, OpenCV + ultralytics)
         └── run_depth_demo.py
         └── run_param_test.py
```

---

## 逐文件说明

### stippling.py — 共享计算核心

**职责**: 实现 Secord (2002) Weighted Voronoi Stippling 算法。将灰度图转化为蓝噪点分布并附带每点半径，是基础版和深度感知版共享的点放置计算引擎。

| 函数 | 说明 |
|------|------|
| `compute_density(gray, gamma, invert)` | 灰度图 → 归一化 [0,1] 密度场 |
| `rejection_sample(density, n, rng)` | 向量化密度加权拒绝采样，初始点放置 |
| `voronoi_filtered(points, W, H)` | 带镜像点技巧的 Voronoi 图，消除无界胞元 |
| `weighted_centroid_cumsum(...)` | 累积和扫描线快速密度加权质心 |
| `lloyd_relax(points, density, n_iter, rng)` | Lloyd 松弛 (CVT)，带抖动避免六角格伪影 |
| `prune_overlapping(points, radii, gap)` | 贪心密度自适应重叠剪枝 (大点优先) |
| `prune_min_distance(points, radii, min_dist)` | 固定距离剪枝替代方案 |
| `stipple(...)` | 完整管线: 拒绝采样 → Lloyd 松弛 → 半径 → 抖动 → 剪枝 |

**依赖**: `numpy`, `scipy.spatial` (`Voronoi`, `cKDTree`)

**被调用方**: `kusama.py` (使用 `compute_density`, `stipple`), `depth_kusama.py` (使用 `compute_density`, `rejection_sample`, `lloyd_relax`, `prune_overlapping`)

---

### kusama.py — 基础版 Kusama 渲染器

**职责**: 接收输入图片，运行 Voronoi stippling 生成点分布，然后施加草间弥生的标志性视觉特征：高色度双色调色板、恐惧真空背景填充、多尺度点阵、Canny 边缘增强、硬边实心圆。

| 组件 | 说明 |
|------|------|
| `PALETTES` | 6 套双色调色板 (black_red, yellow_black, white_red, red_white, magenta_black, yellow_red) |
| `canny_edges(gray, low, high)` | 二值 Canny 边缘掩码 |
| `edge_points(edges, step, jitter, rng, r)` | 沿边缘采样小点用于轮廓强调 |
| `background_fill_points(W, H, spacing, r, jitter, seed)` | 稀疏抖动网格小点用于恐惧真空背景 |
| `draw_dots(canvas, points, radii, color_bgr)` | 硬边实心圆绘制 (无抗锯齿, LINE_4) |
| `kusama_polka(...)` | 完整管线: 缩放 → 密度 → 主点阵 → 可选多尺度层 → 边缘点 → 背景填充 → 按序渲染 |
| CLI | argparse 命令行入口 |

**依赖**: `cv2`, `numpy`, `stippling`

**被调用方**: `run_demo.py`

---

### depth_kusama.py — 深度感知版 Kusama 渲染器 (论文核心)

**职责**: 集成 YOLO26 单目深度估计与语义分割，使点大小编码场景深度 (近=大, 远=小)，并实现语义感知的前景/背景双色渲染。这是 IJCAI'26 论文的核心贡献。

| 组件 | 说明 |
|------|------|
| `DepthEstimator` | 封装 YOLO26 深度模型 (`yolo26x-depth.pt`)，`predict(image)` 返回度量深度图 (米) |
| `SemanticSegmentor` | 封装 YOLO26 语义分割 (`yolo26x-sem.pt`)，19 类 Cityscapes，`predict(image)` 返回逐像素类别 |
| `normalize_depth(depth, d_min, d_max, percentile_clip)` | 深度归一化到 [0,1]，带百分位裁剪 |
| `normalize_depth_foreground(depth, fg_mask, ...)` | 仅用前景深度范围归一化，背景赋 1.0 (最远/最小点) |
| `depth_to_radius(d_norm, r_min, r_max, alpha, sigma, rng)` | 半径 = r_min + (r_max-r_min)·(1-d̂)^α · (1+noise) |
| `depth_to_density(d_norm, gray, gamma, beta, ...)` | 复合密度 = (1-d̂)^β · 亮度密度 |
| `depth_aware_stipple(...)` | 深度感知点阵: 拒绝采样 → Lloyd → 深度半径 → 抖动 → 剪枝 |
| `analyze_semantic_regions(seg)` | 按类别的连通区域分析 |
| `get_foreground_mask(seg, min_area_ratio)` | 前景 = 非背景类别 (排除 road/sidewalk/building/wall/sky/vegetation/terrain) |
| `DEPTH_PALETTES` | 5 套调色板，每套含 bg/fg_dot/bg_dot 三色 |
| `draw_dots_dualcolor(...)` | 语义感知双色绘制 |
| `depth_kusama_polka(...)` | 完整三层管线: (1) 精细点层 (1-5px), (2) 深度强调层 (前景大点), (3) 边缘增强层; 绘制顺序 bg→fine→edge→depth |
| `_save_intermediates(...)` | 保存深度/分割/密度/前景掩码可视化 |
| CLI | argparse 命令行入口 (大量可调参数) |

**依赖**: `numpy`, `cv2`, `ultralytics.YOLO`, `stippling`, `scipy.spatial.cKDTree`

**被调用方**: `run_depth_demo.py`, `run_param_test.py`

---

### gen_test_images.py — 合成测试图片生成器

**职责**: 生成四张合成测试图片到 `inputs/` 目录，用于测试基础版管线。每张测试不同的密度/对比度场景。

| 函数 | 说明 |
|------|------|
| `make_sphere()` | 径向渐变球体 (测试密度梯度、边缘变暗) |
| `make_still_life()` | 重叠几何体 + 阴影 (南瓜形圆、三角、矩形)，高斯模糊 |
| `make_portrait()` | 高对比面部剪影 + 颧骨高光 |
| `make_pumpkin()` | 草间弥生标志性南瓜 (分瓣椭圆体 + 茎) |

**依赖**: `cv2`, `numpy`, `os`

**注意**: 深度感知版 demo 使用 `.jpg` 真实照片 (`pumpkin.jpg`, `cat.jpg`, `pepper.jpg`)，不由本脚本生成。

---

### run_demo.py — 基础版批量 Demo

**职责**: 为基础版管线批量渲染 6 个任务 (输入图片 × 调色板组合)，使用调优参数，输出到 `outputs/`。

- 6 个任务: 每个配置 n_points=20000, n_iter=10, r_min=1.0, r_max=5.0, gamma=1.2, seed=42
- 调用 `kusama.kusama_polcha()` 逐任务执行并计时

**依赖**: `time`, `kusama.kusama_polka`

---

### run_depth_demo.py — 深度感知版批量 Demo

**职责**: 为深度感知管线批量处理 6 个任务 (pumpkin, cat, pepper × 2 调色板)，使用优化参数，首个任务保存中间可视化，输出统计 JSON。

- 优化参数: r_max=12-14, alpha=1.3-1.8, sigma=0.12-0.18, overlap_gap=4.0
- 统计写入 `outputs/depth_demo/pipeline_stats.json`

**依赖**: `os`, `time`, `json`, `depth_kusama.depth_kusama_polka`

---

### run_param_test.py — 参数扫描 + 消融实验

**职责**: 系统性变化关键参数 (alpha, sigma, r_max, beta, n_points, overlap_gap, palette, 消融开关)，运行管线，分析输出质量，生成 JSON + CSV 汇总及联系表蒙太奇。为论文提供定量评估 (参数敏感性 + 消融研究)。

| 组件 | 说明 |
|------|------|
| `BASE` | 默认配置字典 (n_points=25000, r_max=14.0, alpha=1.5, beta=0.6, sigma=0.15 等) |
| `TEST_GROUPS` | 8 个测试组: alpha, sigma, r_max, beta, n_points, overlap_gap, palette, ablation |
| `QUICK_VALUES` | `--quick` 模式缩减值集 |
| `analyze_output(image_path)` | 质量指标: 连通组件数、最大色块占比、覆盖率、半径统计 |
| `make_contact_sheet(...)` | 标注蒙太奇网格 |
| `run_group(group_name, input_path, output_dir, quick, palette)` | 单组扫描 |
| `main()` | argparse CLI (`--input`, `--output-dir`, `--quick`, `--group`, `--palette`) |

**依赖**: `os`, `sys`, `json`, `time`, `csv`, `argparse`, `itertools`, `cv2`, `numpy`, `depth_kusama`

---

## 运行方式

```bash
# 基础版
python gen_test_images.py          # 生成测试图片
python run_demo.py                 # 运行基础版 demo

# 深度感知版 (需要 GPU + YOLO26 权重)
python run_depth_demo.py           # 运行深度感知版 demo
python run_param_test.py --quick   # 快速参数扫描
```

## 论文

`paper/` 目录包含 IJCAI'26 Arts track 论文 "Spatially-Aware Stippling" 的完整 LaTeX 源码，使用 xelatex 编译。
