"""voronoi.py — Secord Weighted Voronoi Stippling 核心.

实现 Secord (2002) 的加权质心 Voronoi 图 (WCVT) 迭代点绘算法:

1. 拒绝采样按密度场初始化点集
2. 镜像点 Voronoi 处理无界单元
3. cumsum 加速的密度加权质心计算
4. Lloyd 松弛逼近蓝噪声分布
5. 密度自适应重叠剪枝

**依赖说明**: 本模块优先使用 ``scipy.spatial.Voronoi`` / ``cKDTree``.
若本机 scipy 与 numpy 二进制不兼容 (会抛 ``ImportError`` 或
``ValueError: numpy.dtype size changed``), 调用方可改用
:mod:`stipple_pure` 流派的纯 numpy 路径 (基于 :class:`~dotartkit.ops.grid.GridHash`).

坐标系约定:
- density shape (H, W), 索引 [row, col] = [y, x]
- points 存为 (x, y), x ∈ [0, W], y ∈ [0, H] (图像坐标, y 向下)
"""

from __future__ import annotations

import warnings

import numpy as np

try:
    import scipy.spatial
    from scipy.spatial import Voronoi
    _HAS_SCIPY = True
except Exception:  # pragma: no cover - 本机已知不兼容场景
    scipy = None  # type: ignore
    Voronoi = None  # type: ignore
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
# 密度场
# ---------------------------------------------------------------------------

def compute_density(gray: np.ndarray, gamma: float = 1.0, invert: bool = True) -> np.ndarray:
    """灰度图 → 归一化密度场 ∈ [0,1].

    invert=True (默认) 时暗像素 = 高密度 (更多点), 标准点绘约定.
    """
    g = gray.astype(np.float64) / 255.0
    if invert:
        g = 1.0 - g
    if gamma != 1.0:
        g = np.power(g, gamma)
    g /= max(g.max(), 1e-9)
    return g


# ---------------------------------------------------------------------------
# 拒绝采样初始化
# ---------------------------------------------------------------------------

def rejection_sample(density: np.ndarray, n: int, rng: np.random.Generator,
                     max_batches: int | None = None) -> np.ndarray:
    """按密度场概率采样 n 个点. 返回 (n, 2) (x, y).

    密度全零时立即返回空点集 (0, 2) 并告警 — 调用方 (Lloyd / 剪枝 /
    渲染) 对空点集均能自然处理. ``max_batches`` 为拒绝采样批次上限,
    防止低密度图上凑不齐 n 个点时无限循环; 触达上限时返回已采到的
    部分点集.
    """
    H, W = density.shape
    if density.max() <= 0.0:
        warnings.warn(
            "rejection_sample: 密度场全零 (如全白输入), 返回空点集",
            stacklevel=2)
        return np.empty((0, 2), dtype=np.float64)
    if max_batches is None:
        batch0 = max(n * 3, 4096)
        max_batches = max(50, (n * 20) // batch0 + 10)
    pts = np.empty((n, 2), dtype=np.float64)
    filled = 0
    batches = 0
    while filled < n and batches < max_batches:
        batches += 1
        batch = max((n - filled) * 3, 4096)
        xs = rng.uniform(0, W, batch)
        ys = rng.uniform(0, H, batch)
        ps = rng.uniform(0, 1, batch)
        xi = np.clip(xs.astype(int), 0, W - 1)
        yi = np.clip(ys.astype(int), 0, H - 1)
        accept = ps < density[yi, xi]
        ax, ay = xs[accept], ys[accept]
        take = min(len(ax), n - filled)
        pts[filled:filled + take, 0] = ax[:take]
        pts[filled:filled + take, 1] = ay[:take]
        filled += take
    if filled < n:
        warnings.warn(
            f"rejection_sample: 触达 max_batches={max_batches}, "
            f"仅采到 {filled}/{n} 个点 (密度过低)",
            stacklevel=2)
    return pts[:filled]


# ---------------------------------------------------------------------------
# 镜像点 Voronoi (处理无界单元)
# ---------------------------------------------------------------------------

def voronoi_filtered(points: np.ndarray, W: int, H: int):
    """带镜像点的 Voronoi 图, 消除无界单元.

    返回的 Voronoi 对象附带 ``filtered_regions`` 属性 (顶点索引列表).
    """
    if not _HAS_SCIPY:
        raise ImportError(
            "voronoi_filtered 需要 scipy; 本机 scipy 不可用. "
            "请改用 dotartkit.styles.stipple_pure 流派 (纯 numpy)."
        )
    eps = 0.1
    left = points.copy(); left[:, 0] = -left[:, 0]
    right = points.copy(); right[:, 0] = 2 * W - right[:, 0]
    top = points.copy(); top[:, 1] = -top[:, 1]
    bottom = points.copy(); bottom[:, 1] = 2 * H - bottom[:, 1]
    all_pts = np.concatenate([points, left, right, top, bottom], axis=0)

    vor = Voronoi(all_pts)
    regions = []
    point_indices = []       # 每个 filtered region 对应的原始点索引
    n_orig = len(points)
    for i in range(n_orig):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            continue
        ok = True
        for idx in region:
            x, y = vor.vertices[idx]
            if not (-eps <= x <= W + eps and -eps <= y <= H + eps):
                ok = False
                break
        if ok:
            regions.append(region)
            point_indices.append(i)
    vor.filtered_regions = regions
    vor.filtered_point_indices = point_indices
    return vor


# ---------------------------------------------------------------------------
# cumsum 加速的密度加权质心
# ---------------------------------------------------------------------------

def weighted_centroid_cumsum(vertices: np.ndarray, density: np.ndarray,
                              P: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """用累积和计算多边形内密度加权质心. 返回 (cx, cy)."""
    H, W = density.shape
    xs = vertices[:, 0]
    ys = vertices[:, 1]
    y_min = max(int(np.floor(ys.min())), 0)
    y_max = min(int(np.ceil(ys.max())), H - 1)

    sum_d = 0.0
    sum_xd = 0.0
    sum_yd = 0.0

    for y in range(y_min, y_max + 1):
        xints = []
        for j in range(len(vertices)):
            x1, y1 = vertices[j]
            x2, y2 = vertices[(j + 1) % len(vertices)]
            if (y1 <= y + 0.5 < y2) or (y2 <= y + 0.5 < y1):
                t = (y + 0.5 - y1) / (y2 - y1)
                xints.append(x1 + t * (x2 - x1))
        if len(xints) < 2:
            continue
        xints.sort()
        for k in range(0, len(xints) - 1, 2):
            xa = max(int(np.floor(xints[k])), 0)
            xb = min(int(np.ceil(xints[k + 1])), W - 1)
            if xb < xa:
                continue
            d = P[y, xb] - (P[y, xa - 1] if xa > 0 else 0.0)
            # 恒等式: x·P[x] − Q[x] = Σ_{k≤x}(k−1)·d[k]
            # 故 span [xa, xb] 上 Σ(k−1)·d[k] = A(xb) − A(xa−1),
            # 其中 A(x) = x·P[x] − Q[x], A(−1) = 0.
            xd_a = (xa - 1) * P[y, xa - 1] - Q[y, xa - 1] if xa > 0 else 0.0
            sx = (xb * P[y, xb] - Q[y, xb]) - xd_a   # Σ (k−1)·d[k]
            sum_d += d
            sum_xd += sx + d                          # Σ k·d[k]
            sum_yd += y * d

    if sum_d > 1e-12:
        return np.array([sum_xd / sum_d, sum_yd / sum_d])
    return vertices.mean(axis=0)


# ---------------------------------------------------------------------------
# Lloyd 松弛
# ---------------------------------------------------------------------------

def lloyd_relax(points: np.ndarray, density: np.ndarray, n_iter: int = 10,
                rng: np.random.Generator | None = None) -> np.ndarray:
    """Lloyd 松弛: 每点移动到其 Voronoi 单元的密度加权质心.

    每轮加少量抖动以避免纯 CVT 的正六边形伪影.
    被过滤 (无界/越界) 单元对应的点保留原位, 不从点集中丢弃;
    全部单元被过滤时提前返回当前点集.
    """
    H, W = density.shape
    P = density.cumsum(axis=1)
    Q = P.cumsum(axis=1)
    pts = points.copy()
    for _ in range(n_iter):
        vor = voronoi_filtered(pts, W, H)
        indices = vor.filtered_point_indices
        if not indices:
            break   # 空结果: 保留当前点集, 避免空数组进下一轮 Voronoi
        new_pts = pts.copy()
        for pi, region in zip(indices, vor.filtered_regions):
            verts = vor.vertices[region + [region[0]]]
            new_pts[pi] = weighted_centroid_cumsum(verts, density, P, Q)
        pts = new_pts
        if rng is not None:
            pts += rng.normal(0, 0.3, pts.shape)
        pts[:, 0] = np.clip(pts[:, 0], 0, W - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, H - 1)
    return pts


# ---------------------------------------------------------------------------
# 重叠剪枝
# ---------------------------------------------------------------------------

def prune_overlapping(points: np.ndarray, radii: np.ndarray,
                      gap: float = 0.5,
                      return_mask: bool = False):
    """贪心剪枝: 移除与已保留点圆盘重叠的点.

    两点 i,j 重叠当 ``dist(i,j) < radii[i] + radii[j] + gap``.
    大点优先 (先占据空间), 小点随后填补间隙 — 密度自适应.

    return_mask=True 时返回保留掩码 (n,) bool 而非子集, 供调用方
    对齐逐点元数据 (roles 等), 免去最近邻回查.
    """
    if len(points) == 0:
        return np.ones(0, dtype=bool) if return_mask else (points, radii)
    if not _HAS_SCIPY:
        return _prune_overlapping_pure(points, radii, gap,
                                       return_mask=return_mask)
    tree = scipy.spatial.cKDTree(points)
    kept = np.ones(len(points), dtype=bool)
    order = np.argsort(-radii)
    rng = np.random.default_rng(0)
    order = rng.permutation(order)
    order = order[np.argsort(-radii[order], kind='stable')]
    r_all = radii.max()     # 循环外一次: 原点序内层是 O(n²)
    for i in order:
        if not kept[i]:
            continue
        search_r = radii[i] + r_all + gap
        neighbors = np.asarray(tree.query_ball_point(points[i], search_r),
                               dtype=int)
        neighbors = neighbors[(neighbors != i) & kept[neighbors]]
        if len(neighbors) == 0:
            continue
        dists = np.linalg.norm(points[neighbors] - points[i], axis=1)
        kept[neighbors[dists < radii[i] + radii[neighbors] + gap]] = False
    if return_mask:
        return kept
    return points[kept], radii[kept]


def _prune_overlapping_pure(points: np.ndarray, radii: np.ndarray,
                            gap: float,
                            return_mask: bool = False):
    """scipy 不可用时的纯 numpy O(n²) 剪枝 (仅适合小规模点集)."""
    n = len(points)
    kept = np.ones(n, dtype=bool)
    order = np.argsort(-radii)
    for ii, i in enumerate(order):
        if not kept[i]:
            continue
        js = order[ii + 1:]
        js = js[kept[js]]
        if len(js) == 0:
            continue
        dists = np.linalg.norm(points[js] - points[i], axis=1)
        kept[js[dists < radii[i] + radii[js] + gap]] = False
    if return_mask:
        return kept
    return points[kept], radii[kept]


def prune_min_distance(points: np.ndarray, radii: np.ndarray,
                       min_dist: float,
                       return_mask: bool = False):
    """贪心剪枝: 移除距已保留点小于 min_dist 的点 (纯圆心距判据)."""
    if len(points) == 0:
        return np.ones(0, dtype=bool) if return_mask else (points, radii)
    if not _HAS_SCIPY:
        return _prune_min_distance_pure(points, radii, min_dist,
                                        return_mask=return_mask)
    tree = scipy.spatial.cKDTree(points)
    kept = np.ones(len(points), dtype=bool)
    order = np.random.default_rng(0).permutation(len(points))
    for i in order:
        if not kept[i]:
            continue
        neighbors = np.asarray(tree.query_ball_point(points[i], min_dist),
                               dtype=int)
        kept[neighbors[neighbors != i]] = False
    if return_mask:
        return kept
    return points[kept], radii[kept]


def _prune_min_distance_pure(points: np.ndarray, radii: np.ndarray,
                             min_dist: float,
                             return_mask: bool = False):
    """prune_min_distance 的纯 numpy 回退 — 判据为圆心距 < min_dist
    (与重叠剪枝不同: 不含半径项)."""
    n = len(points)
    kept = np.ones(n, dtype=bool)
    order = np.random.default_rng(0).permutation(n)
    for ii, i in enumerate(order):
        if not kept[i]:
            continue
        js = order[ii + 1:]
        js = js[kept[js]]
        if len(js) == 0:
            continue
        dists = np.linalg.norm(points[js] - points[i], axis=1)
        kept[js[dists < min_dist]] = False
    if return_mask:
        return kept
    return points[kept], radii[kept]


# ---------------------------------------------------------------------------
# 完整点绘 pipeline: density → points → radii
# ---------------------------------------------------------------------------

def stipple(density: np.ndarray, n_points: int = 8000, n_iter: int = 8,
            r_min: float = 1.5, r_max: float = 5.0,
            size_jitter: float = 0.15,
            pos_jitter: float = 0.4, min_dist: float = 0.0,
            overlap_gap: float = 0.5,
            prune_mode: str = "overlap",
            seed: int | None = None):
    """从密度场生成草间风格点绘.

    Parameters
    ----------
    prune_mode : 剪枝模式 — "overlap" 圆盘重叠剪枝 (用 ``overlap_gap``),
        "min_dist" 最小圆心距剪枝 (用 ``min_dist``), "none" 不剪枝.

    返回 (points, radii):
        points : (n, 2) float (x, y) 图像坐标
        radii  : (n,)   float
    """
    rng = np.random.default_rng(seed)
    pts = rejection_sample(density, n_points, rng)
    if _HAS_SCIPY and len(pts) > 0:
        pts = lloyd_relax(pts, density, n_iter=n_iter, rng=rng)

    if len(pts) == 0:
        return pts, np.empty((0,), dtype=np.float64)

    xi = np.clip(pts[:, 0].astype(int), 0, density.shape[1] - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, density.shape[0] - 1)
    local_d = density[yi, xi]
    ld = local_d / max(local_d.max(), 1e-9)
    # 正向映射: 高密度 (暗) → 大点, 草间签名笔法
    radii = r_min + (r_max - r_min) * ld

    if size_jitter > 0:
        radii *= 1.0 + rng.normal(0, size_jitter, radii.shape)
        radii = np.clip(radii, 0.3, r_max * 1.5)
    if pos_jitter > 0:
        pts = pts + rng.normal(0, pos_jitter, pts.shape)

    if prune_mode == "overlap":
        pts, radii = prune_overlapping(pts, radii, gap=overlap_gap)
    elif prune_mode == "min_dist" and min_dist > 0:
        pts, radii = prune_min_distance(pts, radii, min_dist)

    return pts, radii


def has_scipy() -> bool:
    """返回 scipy 是否可用."""
    return _HAS_SCIPY
