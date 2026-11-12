# 傅里叶纹样算法设计（fcp 包 v0.2）

> 模块: `src/fcp/` · 日期: 2026-11-11 · 状态: 已实现, 49 测全绿, Demo 视觉验收通过

## 1. 核心思想

用**椭圆傅里叶描述子 (Elliptic Fourier Descriptor, EFD)** 表达一条封闭曲线，
再由"多条不同位置的傅里叶曲线"装配成一幅传统纹样：

```
一条封闭曲线 C  →  一组紧凑谐波系数 (K×4) + 中心 (2)
一幅纹样       →  母题库 {name: 曲线} + 摆放列表 [Placement...]
```

数学形式（Kuhl & Giardina 1982 的三角级数形式）：

```
x(t) = A₀ + Σ_{k=1..K} [ a_k·cos(kt) + b_k·sin(kt) ]
y(t) = C₀ + Σ_{k=1..K} [ c_k·cos(kt) + d_k·sin(kt) ]
```

每一阶谐波 (a_k, b_k, c_k, d_k) 描述一个椭圆分量；K 越大细节越丰富。
纹样中的回纹、云纹、花瓣等母题通常 **5–20 阶**即可抓住主要形态。

## 2. 模块结构

```
src/fcp/
  fourier_curve.py   FourierCurve —— 曲线 ↔ 系数核心类
  contour.py         掩膜 → 有序边界（Moore 追踪）+ 弧长重采样
  pattern.py         Placement/Pattern/PatternSpec + CurveLibrary 母题库
  render.py          PIL 渲染（超采样抗锯齿）
  decompose.py       掩膜部件分解 + 自动阶数选择（真实素材入口）
```

### 2.1 FourierCurve（fourier_curve.py）

- `from_contour(points, order)`: 正变换。内部先按**弧长重参数化**到
  t∈[0,2π)（输入点距不均匀也不影响），插值到均匀网格后用离散积分
  求系数。去均值分解，`center` 单独保存。
- `to_contour(n)`: 逆变换，t 均匀采样。
- `approximate(k)`: 截断到 k 阶（低阶近似，调"简化度"的旋钮）。
- `harmonic_amplitudes() / energy / complexity`: 谐波振幅、总能量
  （Parseval）、复杂度（去掉前 3 阶后的能量占比——圆≈0，尖角密纹>0.15）。
- `normalized()`: 平移/旋转（PCA 主轴对齐）/尺度归一，只留"纯形状"，
  用于形状比较与检索。
- `transformed(scale, rotation_deg, mirror_x, offset)`: **摆放语义**的
  系数域复合变换：
  ```
  new_p(t) = offset + R(θ)·M·( s·(p(t) − center) )
  ```
  形状绕自身中心变换、中心平移到绝对坐标 offset。形状与位置解耦——
  调形状不动位置，调位置不动形状。旋转/镜像直接作用于谐波系数
  （旋转 = x/y 谐波分量的线性组合；镜像 = x 分量变号），无需重采样。
- `to_json / from_json`: 紧凑序列化（系数保留 6 位小数，一条曲线
  通常 <1KB）。

### 2.2 contour.py

- `extract_contours(mask, min_area)`: BFS 连通域 + **Moore 8 邻域边界
  追踪**，输出各区域顺时针有序边界点列（像素中心坐标）。首版约定：
  只走外边界，洞（如回字中心孔）不单独成轮廓。
- `resample_contour(points, n)`: 弧长均匀重采样（作为 EFD 输入的
  标准预处理，也是"重建 vs 原轮廓"逐点对比的基准）。

### 2.3 pattern.py

- `Placement`: 单条曲线实例的摆放参数。三种模式：
  - `single`: 单个实例；
  - `rosette`: n 重旋转对称（团花），副本中心均匀分布在半径
    ring_radius 的圆上并各自旋转 360°·i/n；
  - `tile`: 平移格点（四方连续骨架），tile_dx/dy/nx/ny 控制。
- `Pattern`: 母题库 + 摆放列表。`instances()` 展开所有摆放（含对称
  复制）为 (FourierCurve, Placement) 列表。
- `PatternSpec`: 纹样的完整 JSON 可序列化描述——即调研报告中
  "Pattern Spec"中间表示的第一版。体积小、结构化（27 个曲线实例的
  团花仅 ~6.5KB），**适合作为 LLM 的直接生成目标**。
- `CurveLibrary`: 参数化基础母题（圆、n 瓣花、如意云头骨架、圆角方形）。

### 2.4 render.py

`render_pattern(pattern, size)`: 内容自适应缩放居中、4× 超采样绘制
后 LANCZOS 缩回（抗锯齿）。支持填充/描边、传统配色（土红/石青/
石绿/赭黄/宣纸底）。

### 2.5 decompose.py（真实素材入口，v0.2 新增）

把一幅纹样二值掩膜分解为部件并逐部件 EFD 编码，实现
"掩膜 → 部件 → 系数 → PatternSpec → 重建"的完整往返：

- `decompose_mask(mask, max_order, tol, min_area)`: BFS 连通域 →
  Moore 轮廓 → 每部件**自动选阶**。选阶策略：以 max_order 拟合为
  可达下界，从 K=3 起找第一个满足弧长重采样逐点 RMS ≤ tol 的阶数
  （避免参数相位错位的假误差）；极端尖角达不到 tol 时退回 max_order。
- `Decomposition.report()`: 每部件的面积/阶数/RMS/max 误差 +
  总压缩率（轮廓点数 → 系数个数）。
- `Decomposition.to_pattern()` / `pattern_from_decomposition()`:
  每部件一个 single 摆放组装回 Pattern → PatternSpec。
- 部件按面积降序排列（主体在前）。

实测（宝相花 21 部件掩膜，320px，tol=0.8px）：中心圆 K=3、
椭圆花瓣 K=3–23、像素化圆点 K=24（栅格锯齿需高阶），全部
RMS ≤ 0.42px；2116 轮廓点 → 1458 系数。注意：**像素圆点的
锯齿边界需要很高阶**，真实扫描素材建议先做形态学平滑。

## 3. 已验证的性质

| 性质 | 测试 | 结果 |
|---|---|---|
| 圆 = 纯一阶谐波，往返精确 | test_circle_round_trip | 误差 <1e-6 |
| 高阶重建收敛（尖角星形） | test_high_order_reconstruction | K=32 时逐点误差 <2e-2（Gibbs 固有） |
| 非均匀采样鲁棒（弧长重参数化） | test_nonuniform_sampling_ok | 椭圆半径误差 ~4%（插值固有） |
| 系数域复合变换 = 点列仿射矩阵 | test_composed_transform_matches_matrix | 误差 <1e-9 |
| 形状归一化的不变性 | test_normalized_invariant | 半径分布差 <5e-3 |
| rosette 副本中心角度/半径精确 | test_rosette_expansion | 45.0°±1e-6 |
| 掩膜→轮廓→EFD 往返 | test_contour_to_fourier_round_trip | 边界贴合 ±0.15px（Gibbs 振铃内） |
| Spec JSON 往返 | test_spec_round_trip | 实例几何一致（6 位小数容差） |
| 复合掩膜分解（宝相花 21 部件） | test_baoxiang_part_count | 21 个部件，面积降序 |
| 自动选阶 | test_auto_order_within_budget / test_reconstruction_fidelity | K∈[3,max]，圆 K≤6，全部 RMS ≤ tol |
| 分解→Spec→Pattern 往返 | test_pattern_spec_round_trip | 实例几何一致（1e-4 容差） |
| 部件空间对齐 | test_reassembled_covers_original | 中心部件 r<2，外围 20 部件半径带 40–110 |

Demo 视觉验收（代理像素级核验通过）：
- `harmonic_convergence.png`: K=1→20 逐格收敛，err 0.337→0.021 单调降；
- `rosette_pattern.png`: 五层团花（8 蓝云头/16 金点/红八瓣/绿六瓣/红心），
  45° 旋转 IoU 0.956，内容占画布 80.5%；
- `raster_roundtrip.png`: 复合外轮廓（大圆+四角凸缘）的 EFD 重建与
  原轮廓角向相关 0.995；
- `decomposition.png`: 宝相花 21 部件三联对比（掩膜/分解着色/EFD 重建），
  三格布局质心偏差 ≤0.02，重建 IoU 0.91，无内容越界（含裁切修复复验）。

## 4. 实现中踩过的坑（记录备用）

1. **numpy 视图别名**：旋转系数时 `a = c[:,0]` 是视图，先写 `c[:,0]`
   再用 `a` 算 `c[:,2]` 会读到被污染的值 → 必须 `.copy()`。
2. **变换语义**：EFD 的 center 隐含位置，若让 offset 也参与旋转，
   "放哪里"与"转多少"会互相纠缠 → 采用摆放语义（形状绕自身中心
   变换 + 中心平移到绝对坐标）。
3. **渲染超采样**：缩放系数必须乘 supersample，否则内容只占画布
   1/supersample（视觉验收抓到的 bug）。
4. **尖角 Gibbs 现象**：方形/星形尖角处截断傅里叶有 ~10% 振铃，
   属固有特性；如需锐利角点应提高该部件阶数或拆分子部件。
5. `np.interp` 的 xp/fp 必须等长（弧长表 N+1 点要补回起点的坐标）。
6. 六瓣花的能量集中在第 5/6/7 阶（n 瓣调制的主边带），不是想当然
   的单独第 6 阶。
7. **测试掩膜的部件间距要显式计算**：部件"看起来分开"不够——
   花瓣内缘 52−22=30 恰与中心圆 r=30 相切（4 连通下粘连成一个
   区域）；参数化掩膜还要按画布尺寸等比缩放（小画布下部件越界
   被裁，21 部件只剩 9）。
8. 像素圆的锯齿边界对 EFD 是"高频细节"，自动选阶会顶到 max_order；
   这是正确的行为（误差确实需要高阶才能压下去），真实素材应先平滑。

## 5. 与项目整体的关系

fcp 是三层管线中 **L2 结构层**的几何内核：

- L1（LLM）将来直接生成 `PatternSpec` JSON（母题引用 + 摆放规则），
  系数可来自母题库或由 LLM 从语义参数（瓣数/内径/阶数）选择；
- L2 用本包的求解/校验能力检查 spec 合法性（未知母题、非法模式、
  退化曲线均有明确报错），并可直接渲染预览；
- L3（diffusion）侧：`PatternSpec` 展开后的骨架图可作为 ControlNet
  的条件输入；`complexity`/`harmonic_amplitudes` 可作为骨架复杂度
  的可控特征；对称模式（rosette/tile）天然对应 wallpaper group 的
  旋转/平移子群，是后续接入对称群理论的接口。

## 6. 后续方向

- ~~真实纹样图像的部件分解实验~~ **已完成**（decompose.py，2026-11-11）；
  下一轮选题建议：真实扫描的团花/藻井/蜡染图（需先做形态学平滑）；
- 洞轮廓（回字内孔）追踪：目前只有外边界，需轮廓树（类似 OpenCV
  RETR_TREE）补全；
- 曲线间拓扑（相切/包含/相交）检查，供 LLM 校验器使用；
- 与 pyefd 对拍系数，确认实现兼容；
- SVG 导出（每条曲线一个 path，天然分层可编辑——对接"再创作"出口）；
- 对称检测：对分解出的部件做旋转对称聚类（同形部件归并为一个母题
  + rosette 摆放，把 21 部件 spec 进一步压缩——demo4 的 21 个 single
  摆放可归并为 ~4 个母题 + 对称摆放）。
