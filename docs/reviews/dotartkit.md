# DotArtKit 代码审阅报告（2026-11-09）

以下所有问题均为逐行阅读源码后确认，关键算法结论（cumsum 质心偏差）已用独立数值实验复核。已知历史修复（pydantic model_copy 属其他项目、177 测全绿、remap_radii 不重采样）已单独验证，不在问题列表中重复。

---

## 一、模块结构（每模块一行职责）

| 模块 | 职责 |
|---|---|
| `dotartkit/ops/color.py` | 像素原语：float01 转换、Rec.709 亮度、向量化 RGB↔HSV、双线性采样、PIL 圆盘绘制、Kusama 调色板（BGR） |
| `dotartkit/ops/grid.py` | 固定 cell 网格哈希 `GridHash`，O(1) 近邻最小距离约束（替代 cKDTree） |
| `dotartkit/ops/voronoi.py` | Secord WCVT 点绘核心：密度场、拒绝采样、镜像点 Voronoi、cumsum 加速加权质心、Lloyd 松弛、重叠/最小间距剪枝 |
| `dotartkit/ops/geometry.py` | 深度图几何场（纯 numpy）：梯度模、平均曲率 κ（符号化）、高斯曲率符号，供 E_geo 与 6 通道网络使用 |
| `dotartkit/ops/depth.py` | YOLO26 深度/语义封装（可选 ultralytics）+ 纯 numpy 的深度归一化、深度→半径/密度、前景掩码 |
| `dotartkit/styles/seurat.py` | 点彩派：网格 cell 均值色 → 主色/互补色分解 + Bayer 4×4 有序抖动 |
| `dotartkit/styles/benday.py` | Ben-Day 半调：旋转网格、r=λ√(a/π) 覆盖率、Lichtenstein 四色量化 |
| `dotartkit/styles/warp.py` | Vasarely Vega 欧普：径向衰减位移场的变形网格 + 亮度调制 |
| `dotartkit/styles/stipple_pure.py` | 纯 numpy Secord 点绘：密度拒绝采样 + GridHash 密度自适应最小间距，r∝ρ^(-1/2) |
| `dotartkit/styles/vogel.py` | 黄金角叶序：r=c√n、θ=n·137.508°，亮度调制半径与颜色 |
| `dotartkit/styles/kusama_basic.py` | 草间基础版：亮度密度 Voronoi 点绘 + 多尺度层 + Canny 边缘 + horror vacui 背景 + cv2 硬边绘制 |
| `dotartkit/styles/kusama_depth.py` | 草间深度版：YOLO26 深度/语义 + 三层架构（fine/depth-emphasis/edge+bg）+ 跨层剪枝 + 语义双色 |
| `dotartkit/learned.py` | 可学习深度→半径映射：6 通道轻量 CNN、几何感知感知损失（6 项）、训练循环、PIL 渲染入口（torch 可选，回退幂律） |
| `dotartkit/api.py` | 统一分派入口：MODES 注册表（pure/DL/torch 三级）、list/info 辅助函数 |
| `dotartkit/cli.py` | argparse CLI：list / generate（inspect 签名过滤 kwargs）/ demo |
| `dotartkit/gui/polka_document.py` | 核心文档模型（无 tkinter）：图像 + 中间场 + 点列表 + 10 映射×6 特征注册表 + 滤除 + undo/redo + remap_radii 再编辑 + 渲染 |
| `dotartkit/gui/polka_app.py` | tkinter 桌面编辑器：画布缩放平移、选择/添加/擦除工具、后台线程生成 + 轮询、参数面板、圆形选区重映射 |
| `tests/` | test_smoke（8 模式冒烟）、test_geometry（曲率解析验证+learned）、test_gui_polka（文档层 33 用例）、test_remap_editing（10×6 组合 + remap） |

---

## 二、ops/voronoi.py — WCVT 点绘核心

**V1. `rejection_sample` 在全零密度场上无限死循环**
- `dotartkit/ops/voronoi.py:57-75`（配合 `compute_density` :39-50）
- 严重程度：**high**（触发窄但后果是不可中断的挂起）
- 问题：`compute_density` 对全白图（luminance 全 255）输出全零场（`g /= max(g.max(), 1e-9)` 除以 1e-9 仍为 0）。`rejection_sample` 中 `accept = ps < density[yi, xi]` 永假，`filled` 永不增长，且没有批次数上限（对比 `stipple_pure.py:60` 有 `max_batches` 防护）。全白输入会挂死 `kusama_basic` CLI 进程；GUI 中 `generate` 在 worker 线程永久运行，状态栏停留在"生成中…"且无取消机制。`polka_document.generate`（经 `depth_to_density`，亮度项为 0）同样触发。
- 建议：`rejection_sample` 加 `max_batches` 上限（照抄 stipple_pure 的写法），或在入口断言 `density.max() > 0` 并给密度加小 epsilon（如 stipple_pure 的 `+0.02`）。补一张全白图的回归测试。

**V2. `weighted_centroid_cumsum` 的 x 质心系统性向左偏移 ≥1px（数学错误，已数值复核）**
- `dotartkit/ops/voronoi.py:151-157`（核心在 :153）
- 严重程度：**medium**
- 问题：由恒等式 `x·P[x] − Q[x] = Σ_{k≤x}(k−1)·d[k]`（数值验证成立），代码的
  `xd = xa * P[y, xa-1] − Q[y, xa-1]`（:153）比正确形式 `((xa−1)·P[y,xa−1] − Q[y,xa−1])` 多减了 `P[y,xa−1]`；同时 `sx` 本身等于 Σk·d − Σd（又差一个行质量）。合计 `sum_xd` 每行少计 `d_row + P[y,xa−1]`，即 **cx 被系统性低估 1 +（左侧累积质量/总质量）像素**。实测：矩形多边形上 code cx=4.569 vs 真值 5.988（偏 −1.42px）；第二组 6.497 vs 5.328（偏 −1.17px）。y 方向（`sum_yd += y*d`）无偏。每次 Lloyd 迭代所有点被整体向左拖 ≥1px。
- 建议：`xd = ((xa - 1) * P[y, xa - 1] - xd_a) if xa > 0 else 0.0`，并且 `sum_xd += sx + d`（或等价地在最终 cx 上加回 sum_d）。补一个"合成多边形质心 vs 逐像素真值"的单元测试（现有测试完全没覆盖此函数）。

**V3. `prune_overlapping` 在循环内反复计算 `radii.max()`，O(n²)**
- `dotartkit/ops/voronoi.py:216`
- 严重程度：**medium**（性能）
- 问题：`search_r = radii[i] + radii.max() + gap` 位于 n 次循环体内，仅此一项就是 O(n²)；n=20000 时约 4×10⁸ 次浮点比较，纯浪费。内层邻居循环也是纯 Python（每点 `np.linalg.norm` 一次），可先向量化。
- 建议：循环外 `r_all = radii.max()` 一次；内层改为 `d = np.linalg.norm(points[neighbors] - points[i], axis=1)` 后用布尔掩码批量判 `kept`。

**V4. `prune_min_distance` 的无 scipy 回退语义错误**
- `dotartkit/ops/voronoi.py:251-252` → `_prune_overlapping_pure` :227-243
- 严重程度：**medium**（仅 no-scipy 路径）
- 问题：回退直接把 `min_dist` 当 `gap` 传给 `_prune_overlapping_pure`，判据变成 `d < r_i + r_j + min_dist`（圆盘重叠+间距）而非语义要求的 `d < min_dist`（纯圆心距）。no-scipy 时 `prune="min_dist"` 会剪掉多得多的点。
- 建议：为 min_dist 写独立的纯 numpy 回退（判据 `d < min_dist`），或在 `_prune_overlapping_pure` 加语义参数。

**V5. `lloyd_relax` 会静默丢失点**
- `dotartkit/ops/voronoi.py:179-184`
- 严重程度：**low**
- 问题：`filtered_regions` 只收全部顶点落在界内的单元；任何被过滤/为空的单元（重合点、Qhull 数值抖动使顶点越出 `W+0.1`）对应的点直接从点集消失，`pts` 变短且调用方不知情。另外若 `filtered_regions` 为空，`np.array([])` 下一轮 Voronoi 会崩。
- 建议：按 `point_region` 索引对齐，被过滤的点保留原位置而不是丢弃；空结果提前返回。

**V6. `stipple` 的 `gamma` 是死参数；`min_dist` 仅在 `overlap_gap < 0` 时可达**
- `dotartkit/ops/voronoi.py:272`（gamma 全函数未用）、:300-303（`elif` 链）
- 严重程度：**low**（API 设计）
- 问题：`kusama_basic.py:138` 还在传 `gamma=1.0`，纯误导。默认 `overlap_gap=0.5 >= 0` 意味着 `min_dist` 分支永远走不到，除非调用方显式传负 `overlap_gap` —— 隐晦的开关约定。
- 建议：删除 `gamma`；把 `min_dist`/`overlap_gap` 改成显式模式参数（如 `prune_mode`），与 `polka_document.FILTERS` 的设计对齐。

---

## 三、ops/grid.py — 网格哈希

**G1. `far_enough` 只查 3×3 邻桶，仅当 r ≤ cell 时正确；两个调用方都违反该前提**
- `dotartkit/ops/grid.py:27-36`；违反处：`styles/stipple_pure.py:72`（`local_min` 最大 1.5×cell）、`learned.py:434`（`local_min = min_dist_px + r_here*0.6` 最大约 **3.6×cell**）
- 严重程度：**medium**
- 问题：`GridHash` 构造时 `cell = min_dist_px`，但查询半径可大于 cell。r=1.5·cell 时违反点可能在 2 桶之外（查询点在桶边缘时），3×3 邻域查不到 → 最小间距约束在稀疏区（ρ<0.5）被系统性漏检；learned 模式漏检更严重（间距约束形同虚设的部分区域）。
- 建议：`far_enough` 按 `n = ceil(r / cell)` 扩展搜索环（`range(-n, n+1)`）；或构造时用"最大查询半径"做 cell。补一个对抗性单测（在大 cell 网格中密集插入后验证任意两点距 ≥ r）。

---

## 四、ops/geometry.py — 曲率场

数学核对：平均曲率公式（:105-106）、高斯曲率公式（:135）、中心/二阶差分边界处理均正确；符号约定（h=1−d̂，凸=κ>0）与测试一致。两处小问题：

**GE1. `geometry_fields` 重复计算平滑与全部导数**
- `dotartkit/ops/geometry.py:143-164`（`mean_curvature` :84-113 与 `gaussian_curvature_sign` :119-140 各自做一次高斯平滑 + 5 个导数场）
- 严重程度：**low**（性能，~2× 冗余）
- 建议：抽公共 `_smooth_and_derivs(d_norm, sigma)` 返回 hx,hy,hxx,hyy,hxy，两个函数与 `geometry_fields` 共用。

**GE2. 曲率按全图 max|H| 归一，平坦场景放大噪声**
- `dotartkit/ops/geometry.py:109-113`
- 严重程度：**low**
- 问题：`H / |H|max` 对近似平坦的深度图会把噪声当曲率拉满到 ±1（σ=1.5 平滑只能部分抑制）。
- 建议：`hi < 某阈值` 时直接返回 0 场，或用稳健分位数（如 p99.5）替代 max。

---

## 五、ops/color.py / ops/depth.py

color.py 整体干净：HSV 往返、双线性采样（`w-1.001` 防越界）、draw_disks 均正确；调色板 BGR 约定有文档。无 blocking 问题。

**D1. ultralytics 结果接口无法在无权重组件下验证，存在 API 断裂风险**
- `dotartkit/ops/depth.py:51`（`results[0].depth.data`）、:81（`results[0].semantic_mask.data`）
- 严重程度：**low**（无法在本环境实证，仅提示）
- 问题：ultralytics 公开 API 中分割结果惯常是 `results[0].masks.data`；`semantic_mask`/`depth` 是否存在于所装版本需实测。当前测试对 kusama_depth 全部 skipif，这两行是整个仓库唯一零覆盖的真实推理路径。
- 建议：在有 ultralytics 的环境加一个最小真图冒烟测试；或用 `getattr(results[0], "depth", None)` 防御 + 明确报错。

**D2. `DepthEstimator`/`SemanticSegmentor` 每次 `depth_kusama_polka` 调用都从磁盘重载模型**
- `dotartkit/styles/kusama_depth.py:173,179`（对照 `polka_document.ensure_depth` :343-353 有实例缓存）
- 严重程度：**low**（API 路径性能/设计不一致）
- 建议：模块级 `_MODEL_CACHE: dict[str, YOLO]` 或允许调用方注入 estimator，使 api.generate 路径与 GUI 路径行为一致。

---

## 六、styles/*（七个流派）

**S1. `polka_document` 的 `luminance` 特征通道方向与文档相反：暗处得到小点**
- `dotartkit/gui/polka_document.py:381-383`（`return 1.0 - g`），对照激活函数族 `ACTIVATIONS`（:193-204，全部是 `(1-f)^α` 型低值→大点）与文档 `docs/波点编辑器.md:70`（"暗=1 — 暗处大点"）、`FEATURES` docstring :247
- 严重程度：**high**（用户可选通道，输出与声明相反）
- 问题：映射函数的输入语义是"低值=近=大点"（depth 通道 d̂=0 为近）。`luminance` 通道返回 `1-g`（暗=1），经 power/linear/sigmoid/... 作用后**暗处半径趋近 r_min**——与文档"暗处大点（经典点绘）"和行内注释"暗 = 1 → 大点"完全相反。`test_remap_editing.py:109-112` 只断言了特征场方向（暗>亮），把这个 bug 固化进了测试。注：深度后端的 luminance（暗=近）行为是正确的，两者形成矛盾。
- 建议：`return g`（暗=0 → 大点），同步修测试为"暗区点半径均值 > 亮区"。

**S2. `hybrid` 特征通道同样反向：近景+凸面得到最小点**
- `dotartkit/gui/polka_document.py:395-398`（`h = 0.6*(1-d̂) + 0.4*κ₊`）
- 严重程度：**high**
- 问题：hybrid 值在"近 + 凸"处最高（≈1），经 `(1-f)^α` 后恰好得到 **r_min** —— 与该通道命名的意图（深度+凸面增益，见 `_act_depth_curv` 的 E_geo 同向设计）完全相反；远/凹处反而得到大点。
- 建议：改为 `h = 0.6*d_norm + 0.4*(1-k_pos)`，使低值=近+凸=大点；或把 hybrid 语义改为"配 inverse 激活使用"并在 GUI 描述里写明（不推荐，破坏 10×6 自由组合的直觉）。

**S3. `curvature` / `gaussian_curv` 通道在标准激活下方向同样存疑**
- `dotartkit/gui/polka_document.py:389-394`（凸=1 / 球顶=1）
- 严重程度：**medium**
- 问题：与 S1 同根。`geometry.py` 的设计意图是"凸面（球顶）应给予大点"，但 feature=curvature + activation=power 组合给出凸面→小点。FEATURES docstring 未声明方向，故判为设计意图歧义而非确定性 bug，但与 S1/S2 属同一符号约定错乱家族。
- 建议：统一约定（建议"低值=大点"），4 个通道一起修，并为每个通道补"方向性半径测试"（类似 `test_gui_polka.py:114-118` 对 depth 的测法）。

**S4. `generate_kusama_basic` 经临时文件往返（PIL→PNG→cv2→PNG→PIL）**
- `dotartkit/styles/kusama_basic.py:208-225`（kusama_depth.py:366-388 同样）
- 严重程度：**low-medium**（性能 + Windows tempfile 脆弱性）
- 问题：api.generate 的统一 PIL 接口靠两次全图 PNG 编解码 + 磁盘 I/O 适配 cv2 路径；`tmp_in_path.replace(".png", "_out.png")` 依赖后缀恰好出现一次。1024² 图一次往返约数百 ms 纯开销。
- 建议：把 `kusama_polka` 的核心改为接受 ndarray（路径仅做薄包装），消除 I/O 往返；也顺带消掉 `stipple(gamma=1.0)` 这类死参数传递。

**S5. `seurat` 的 cell 均值是纯 Python 双重循环；`dot_spacing=1` 产生 NaN 颜色**
- `dotartkit/styles/seurat.py:51-58`（循环）、:49-57（spacing=1 时 `y0==y1`、空切片 `.mean(0)` → NaN，无输入校验）
- 严重程度：**low-medium**
- 建议：用 `reshape`/`skimage-style` 平均池化或 `cv2.boxFilter` 向量化；入口校验 `dot_spacing >= 2`。

**S6. `kusama_depth` 跨层剪枝为 Python 双重循环**
- `dotartkit/styles/kusama_depth.py:223-235`
- 严重程度：**medium**（性能；且此路径被 ultralytics skipif 完全无测试覆盖）
- 问题：对每个 fine 点做一次 `query_ball_point` + Python 内层循环。20000 fine × 若干邻居 ≈ 10⁵–10⁶ 次 Python 级运算，秒级开销。
- 建议：`tree.query_ball_point(pts_fine, search_r)` 一次性取回（返回 object 数组）后用 `np.concatenate` + `np.linalg.norm` 向量化判距；或直接 `cKDTree.query(..., distance_upper_bound)` 的双树批量写法。同时把该函数抽成纯 numpy 可测的独立函数（输入两层点集），摆脱 ultralytics 依赖后可直接单测。

**S7. 杂项（low）**
- `styles/vogel.py:20` `scale: float = None` 类型注解应为 `float | None`；:25 `radius_power` 未使用（已有文档说明，可接受）。
- `styles/benday.py:42-47` 旋转网格生成 `4·diag²` 面积（约 8× 过采样）后才 mask，大图小间距时浪费内存/时间；可先算旋转后的包围盒再生成。
- `styles/kusama_depth.py:87-89` `_save_intermediates` 的 `depth`、`class_names` 参数未使用；:98-100 `colors[cls_id]` 假设类别 id < 20，越界会 IndexError（可 `colors[cls_id % 20]` 或按需生成）。

---

## 七、learned.py — 可学习映射

**L1. 推理路径未把模型搬到 device，GPU 推理必然崩溃**
- `dotartkit/learned.py:110-114`（`x = ...to(device)` 但模型原地不动）、:397-399（`generate_learned` 构造/加载模型后无 `.to(device)`）
- 严重程度：**medium**
- 问题：`predict_numpy` 把输入张量放到 device，但 `self.forward(x)` 用的是 CPU 参数 → `device="cuda"` 时直接 RuntimeError。训练路径 :239 有 `.to(device)`，唯独推理漏了。
- 建议：`predict_numpy` 开头 `self.to(device)`（幂等），或 `generate_learned` 加载后统一 `.to(device).eval()`。

**L2. `torch.histc` 不可微，histogram 损失项对训练无梯度贡献**
- `dotartkit/learned.py:194-196`
- 严重程度：**medium**
- 问题：`torch.histc` 不支持 autograd，`losses['histogram']` 反传梯度为 0 —— 模块 docstring 宣称的"半径直方图"训练信号实际未生效，只剩日志价值。`test_loss_with_curvature` 只断言 total 可反传，检测不到。
- 建议：用 soft-histogram（如对 bin 中心的 RBF/三角核加权求和）替代 histc；或删掉该项并在文档中如实说明。

**L3. `generate_learned` 的 GridHash 查询半径远超 cell（G1 的最重案例）+ 杂项**
- `dotartkit/learned.py:434`（`local_min` 最大 ≈3.6×cell，见 G1）；:115（`radius.squeeze()` 在 H 或 W 为 1 时会错误降维，应 `squeeze(0).squeeze(0)`）；:171（损失签名里的 `d_grad` 参数从未使用，docstring 的"蓝噪声频谱"项未实现）
- 严重程度：**medium**（G1 部分）/ low（其余）
- 建议：同 G1；`predict_numpy` 返回时用显式维度索引；未实现的损失项要么实现要么从 docstring/签名中移除。

---

## 八、api.py / cli.py / __init__.py

整体设计良好：三级依赖注册表、mode_info 元信息、`generate` 的 ValueError/ImportError 语义清晰。小问题：

**A1. `dotartkit.__init__` 漏导出 `list_torch_modes`**
- `dotartkit/__init__.py:36-43,51-64`（import 与 `__all__` 均缺）
- 严重程度：**low**
- 问题：`from dotartkit import list_torch_modes` 抛 ImportError；cli 是从 `.api` 直接拿才没暴露。
- 建议：加入 import 与 `__all__`。

**C1. cli 死代码 + `--device` 默认值强推 GPU"0"**
- `dotartkit/cli.py:71-78`（`accepted` 计算两次，第一份即废）、:88,156（`--device` default "0"，candidate 过滤 `v is not None` 恒真 → 无 GPU 机器上 `kusama_depth` 被迫 device="0" 失败）
- 严重程度：**low-medium**
- 建议：删除 :72-73；`--device` default 改 `None`（缺席时让流派自身默认决定）。另：`_cmd_generate` 对 ImportError 无友好捕获（kusama_depth 无 ultralytics 时用户看到裸 traceback）。

**C2. requirements.txt 把 scipy 列为默认安装，与 pyproject 的 optional 定位矛盾**
- `requirements.txt:9` vs `pyproject.toml:27-29`
- 严重程度：**low**
- 建议：注释掉或拆分 requirements-optional.txt，与"scipy 可选、退化到纯 numpy"的分层叙事一致。

---

## 九、gui/polka_document.py — 文档模型

除 S1/S2/S3（特征通道符号）外：

**P1. `ensure_depth` 不感知 `semantic_aware` 开关，前景掩码滞留旧值**
- `dotartkit/gui/polka_document.py:331-335`
- 严重程度：**medium**
- 问题：`need_recompute` 只看 `depth_raw / backend / fg_mask is None`。用 yolo26 + semantic_aware=False 生成过一次后（fg_mask=全 1），再勾选"语义感知"重新生成：条件全 False → 直接 return，`fg_mask` 永远是全 1，双色渲染与前景感知归一化静默失效，直到用户切换一次深度后端。`_semantic_aware` 在 :364 被赋值却从不参与判断。
- 建议：把 `semantic_aware != self._semantic_aware` 纳入 `need_recompute`；补一条"切 semantic_aware 后 fg_mask 更新"的回归测试。

**P2. 交互热点路径是纯 Python O(n) 循环，2 万点时拖拽/擦除明显卡顿**
- `dotartkit/gui/polka_document.py:587-600`（`find_dot` 每次点击全列表 hypot）、:607-616（`delete_dots_in_circle` 每次拖拽事件全列表扫描 + 逐个 `del`）、:754-768（`render` 3 遍角色 × 每点一次 `cv2.circle` Python 调用；拖拽移动时每次 mousemove 都 `invalidate_render` → 全量重绘）
- 严重程度：**medium**（体验）
- 建议：`find_dot`/`delete_dots_in_circle` 用 `np.asarray` 缓存坐标数组（在 dots 变更时失效）向量化；`render` 可按半径排序后批量调用，或对拖拽预览使用"仅重画受影响区域 + 顶层叠加"的策略（当前 overlay 机制已具备一半）。

**P3. `_snapshot_roles` 的无 scipy 回退是 O(n²)**
- `dotartkit/gui/polka_document.py:580-584`
- 严重程度：**low-medium**（仅 no-scipy）
- 问题：每点一次 `np.sum((pts_before - p)**2, axis=1)` 全量距离；20000 点 ≈ 8×10⁸ flop，数秒到数十秒。
- 建议：既然 `prune_*` 保证输出是输入的行子集，可用保留掩码直接索引 roles（让 `prune_overlapping` 返回 keep 掩码或让 `_apply_filter` 记录原索引），完全免掉最近邻查询——顺带 scipy 路径的 cKDTree 查询也省了。

**P4. `render` 的 `semantic_aware` 参数是死参数**
- `dotartkit/gui/polka_document.py:737-739`（函数体从未引用）
- 严重程度：**low**
- 建议：删除参数（GUI 调用处 `polka_app.py:643-645` 同步），或实现"关掉语义感知时 fg/bg 同色"的真实语义。

**P5. 杂项（low）**
- `polka_document.py:499-501`：`exs[::step]` 切了三次（eys 同），可先切片一次再复用。
- `polka_document.py:705`：`begin_edit` 里才创建 `_edit_changed`，`__init__` 未声明该属性；建议 `__init__` 初始化为 False。
- `generate` 的边缘点半径硬编码 1.3、背景点半径 ~1.0·U(0.7,1.3)，不可调 —— 功能性局限而非 bug，建议提为参数。

---

## 十、gui/polka_app.py — tkinter 编辑器

已知修复确认到位：参数快照在 UI 线程一次性抓取（:562-577）、worker 不触碰 tkinter（:598-620）、`after(100)` 轮询（:585-596）、`fit_image` 的 winfo 兜底 + 延迟重试（:108-116）、palette Combobox 绑 `<<ComboboxSelected>>`（:404）、activation/feature 用 textvariable+trace 联动描述（:453-467）、kappa 只传曲率类激活（polka_document :471-476, :668-676）。剩余问题：

**U1. 后台生成期间文档模型并发访问无保护，用户编辑会被静默覆盖**
- `dotartkit/gui/polka_app.py:555-620`（生成线程）+ :210-292（画布全程可交互）+ `polka_document.py:518-519`（`self.dots = dots` 整体替换）
- 严重程度：**medium**
- 问题：tkinter 变量的线程问题已修，但 **PolkaDocument 本身**仍被两线程共享：生成进行中用户可以拖点/删点/撤销——`generate` 结束时 `self.dots = dots` 直接覆盖期间所有手动编辑；`_push_history`（deepcopy + 栈操作）与 UI 线程的 `undo/redo` 并发可能交叉污染撤销栈。深度估计（YOLO26）耗时数秒，窗口期不小。
- 建议：生成期间禁用画布编辑（`self.canvas.unbind` 或状态旗标拦截 `_on_left/_on_drag`），或把 `doc` 的生成结果经 UI 线程提交（worker 只返回点集，由 `_generate_done` 应用）。

**U2. 擦除拖拽每 6px 产生一条撤销记录（且每次 deepcopy 全部点）**
- `dotartkit/gui/polka_app.py:258-267` → `polka_document.py:607-616`（`delete_dots_in_circle` 每次调用 `_push_history`）
- 严重程度：**medium**（undo 粒度 + 内存抖动）
- 问题：一次连续擦除手势产生几十条历史，Ctrl+Z 一次只退一小步；每步 deepcopy 2 万+ Dot 对象。
- 建议：擦除手势用 `begin_edit/end_edit` 包裹（按下时快照、松开时一次提交），与拖拽移动的既有模式一致。

**U3. 滚轮改半径绕过历史系统**
- `dotartkit/gui/polka_app.py:181-193`
- 严重程度：**low-medium**
- 问题：`_on_wheel` 直接 `d.r = max(0.3, ...)`，没有 `begin_edit/end_edit`——该修改不可撤销，且之后一次 Ctrl+Z 会"跳过"它回退到更早状态，历史语义不一致。
- 建议：选中后首次滚轮时 `begin_edit`，`<ButtonRelease>`/切换选中时 `end_edit(changed=True)`；最低限度在状态栏提示不可撤销。

**U4. 杂项（low）**
- `polka_app.py:108-116`：`fit_image` 在未布局分支既安排了 `after(80)` 重试又立即用兜底尺寸算一遍（双重计算；若用户在 80ms 内手动缩放会被重试覆盖）——建议未布局时 `return` 只保留重试。
- `polka_app.py:233,576`：`brush_radius.get()` / `self.seed.get()` 在 Spinbox 被清空时抛 `TclError`，未捕获 → 点击画布/生成即崩；包 try 或用 `validatecommand`。
- `polka_app.py:427-428`：`trace_add("write", lambda *_: None)` 是无操作死代码。
- `polka_app.py:559-560`：生成进行中再点"重新生成"静默 return，无任何反馈（按钮看似失灵）；建议状态栏提示"生成中…"。
- `polka_app.py:585-596`：worker 若被硬杀（`_gen_result` 保持 None 且线程死亡），轮询静默退出，状态栏永远"生成中…"；可加"线程已死且无结果"分支报错。

---

## 十一、测试盲区（tests/）

1. **ops 层零直接单测**：`voronoi.py`（质心、Lloyd、prune）、`grid.py`、`color.py` 完全没有对应测试文件——V2（质心偏差）、V4（min_dist 回退语义）、G1（GridHash 半径）都因此漏网。`test_smoke` 只做端到端尺寸断言。
2. **特征通道只测"场方向"不测"半径方向"**：`test_remap_editing.py:109-112` 把 luminance 反向 bug 固化进测试；建议照 `test_gui_polka.py:114-118`（depth 的暗侧大点断言）给全部 6 通道各加一条半径方向断言。
3. **退化输入无覆盖**：全白图（V1 死循环）、`n_points=0`（scipy QhullError）、1×1 图、`dot_spacing=1`（NaN）。
4. **polka_app 零测试**：线程提交、历史交互、擦除手势粒度（U1-U3）全部靠人工；`run_gui_e2e.py` 的"GUI 冒烟"只验证模块可导入。
5. **kusama_depth 跨层剪枝（S6）被 ultralytics skipif 完全屏蔽**——建议抽成纯函数后直接单测。
6. **CLI 无测试**（C1 的死代码、device 默认值问题因此未被发现）。
7. 177 用例的数量口径与参数化展开一致（80 个测试函数 + parametrize），未发现虚报；但按上述盲区看，覆盖广度集中在 styles/GUI 文档层，深度不足。

---

## 十二、已知历史修复的验证结论（不重复报告）

- **remap_radii 不重采样**：确认已修——`polka_document.py:632-690` 只改 `d.r`，位置不动；`test_remap_keeps_positions` / `test_remap_manual_edits_survive` / 选区外点不变均有覆盖。✅ 彻底。
- **tkinter 线程安全（变量快照+轮询 / winfo 未布局 / Combobox / kappa kwarg）**：四处修复全部在位且写法正确（见第十节开头）。✅ 彻底——但注意 U1：快照解决了 *tkinter 变量* 的线程安全，*文档模型* 的并发访问是另一个仍未解决的问题，属新发现。
- **pydantic model_copy**：DotArtKit 无 pydantic 依赖（全仓 grep 确认），不适用。
- **177 测全绿**：与测试文件结构一致，未发现异常。

---

## 十三、总体评价 + 优先改进 Top 3

**总体评价**：这是一个结构清晰、分层纪律执行得很好的研究/教学型代码库。ops→styles→api→cli 的算子分层和三级可选依赖（scipy/ultralytics/torch）的 import 守卫做得干净且一致；GUI 文档模型与 tkinter 分离使核心层可无头测试，是同类项目里少见的良好实践；几何模块（曲率、E_geo）的数学与解析测试质量高；再编辑（remap_radii）的历史修复干净彻底。主要短板集中在三处：**(a)** 特征通道与激活函数之间缺一个统一的符号约定，导致 6 通道里 4 个方向存疑、2 个明确反了——这是当前最大的正确性问题；**(b)** 数值算法的边界防御不足（零密度死循环、GridHash 半径越界、质心 cumsum 的 off-by-one），且这些恰是测试盲区；**(c)** 热点路径的 Python 循环性能（prune O(n²)、render/find_dot、跨层剪枝）在 2 万点规模下开始影响可用性。

**Top 3 优先改进**：

1. **统一特征通道的符号约定并修复 luminance/hybrid 反向（S1/S2/S3）**——这是用户一眼能看错的艺术结果，且现有测试把 bug 固化了。约定"低值=大点"后，`get_feature` 的 4 个通道翻转 + 为每个通道加半径方向断言，半天工作量，收益最大。
2. **给采样/剪枝管线加退化输入防护（V1 死循环 + G1 GridHash 半径 + V2 质心修正）**——补 `ops/voronoi.py`、`ops/grid.py` 的直接单元测试；全白图挂死是唯一可能让用户进程无响应的问题，`max_batches` + 密度下限 + GridHash 搜索环扩展三处小改即可全部关闭。
3. **GUI 生成期间的文档并发保护 + 擦除手势历史粒度（U1/U2）**——U1 会静默丢失用户编辑（深度后端数秒窗口期），U2 让撤销几乎不可用；用"worker 只返回结果、UI 线程提交"+ 擦除手势包 `begin_edit/end_edit` 两个模式化改动即可，顺带把 `_snapshot_roles` 改为掩码索引（P3）消除一处 O(n²)。
