"""test_voronoi.py — ops/voronoi.py 直接单元测试.

覆盖审阅报告的数值算法问题:
- V2: cumsum 加权质心 vs 逐像素真值 (x 方向曾系统性左偏 ≥1px)
- V1: 全零密度场 (全白图) 不再死循环
- V3/V4: 重叠剪枝与最小间距剪枝的语义 (含纯 numpy 回退)
- V5: Lloyd 松弛不丢点
"""

import os
import sys
import warnings
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.ops.voronoi import (  # noqa: E402
    compute_density,
    rejection_sample,
    weighted_centroid_cumsum,
    lloyd_relax,
    prune_overlapping,
    prune_min_distance,
    _prune_min_distance_pure,
    _prune_overlapping_pure,
    stipple,
    has_scipy,
)


# ---------------------------------------------------------------------------
# V2: cumsum 加权质心 vs 逐像素真值
# ---------------------------------------------------------------------------

def _centroid_ground_truth(density: np.ndarray,
                           rows: range, x_lo: int, x_hi: int) -> tuple:
    """逐像素求和真值: 行 rows × 列 [x_lo, x_hi] 的密度加权质心.

    span 规则与 weighted_centroid_cumsum 的采样约定一致:
    - 行: 扫描线在像素中心 y+0.5, 覆盖中心落在 [y0, y1) 内的行
    - 列: 交点 floor(x0) .. min(ceil(x1), W-1) (含端点)
    """
    s = sx = sy = 0.0
    for y in rows:
        for x in range(x_lo, x_hi + 1):
            d = density[y, x]
            s += d
            sx += x * d
            sy += y * d
    return sx / s, sy / s


def _rect_polygon(x0, y0, x1, y1) -> np.ndarray:
    """矩形多边形顶点 (闭合, 无重复首尾)."""
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)


class TestWeightedCentroidCumsum:
    def test_full_image_uniform(self):
        """均匀密度 + 全图矩形: 质心 = 像素索引均值."""
        H, W = 20, 30
        density = np.ones((H, W))
        P = density.cumsum(axis=1)
        Q = P.cumsum(axis=1)
        verts = _rect_polygon(0, 0, W, H)
        cx, cy = weighted_centroid_cumsum(verts, density, P, Q)
        assert cx == pytest.approx((W - 1) / 2, abs=1e-9)
        assert cy == pytest.approx((H - 1) / 2, abs=1e-9)

    def test_rectangle_asymmetric_density(self):
        """非对称密度 + 内部矩形: 与逐像素真值一致 (x 方向曾偏 ≥1px)."""
        H, W = 14, 12
        rng = np.random.default_rng(7)
        density = rng.uniform(0.1, 1.0, (H, W))
        P = density.cumsum(axis=1)
        Q = P.cumsum(axis=1)
        # 矩形 [2, 8] × [3, 9]: 列 2..8 (含), 行 3..8 (中心 ∈ [3, 9))
        verts = _rect_polygon(2, 3, 8, 9)
        cx, cy = weighted_centroid_cumsum(verts, density, P, Q)
        gx, gy = _centroid_ground_truth(density, range(3, 9), 2, 8)
        assert cx == pytest.approx(gx, abs=1e-9), \
            f"x 质心偏差 {cx - gx:+.3f}px (V2 回归: 曾系统性左偏)"
        assert cy == pytest.approx(gy, abs=1e-9)

    def test_rectangle_x_dependent_density(self):
        """纯 x 依赖密度: 专测 x 方向 (旧 bug 在 x 偏, y 无偏)."""
        H, W = 10, 16
        xs = np.arange(W)
        density = np.tile((0.2 + xs / W) ** 2, (H, 1))
        P = density.cumsum(axis=1)
        Q = P.cumsum(axis=1)
        verts = _rect_polygon(1, 2, 12, 8)
        cx, cy = weighted_centroid_cumsum(verts, density, P, Q)
        gx, gy = _centroid_ground_truth(density, range(2, 8), 1, 12)
        assert cx == pytest.approx(gx, abs=1e-9)
        assert cy == pytest.approx(gy, abs=1e-9)

    def test_zero_density_fallback(self):
        """零密度 span: 回退到顶点均值 (不 NaN)."""
        H, W = 8, 8
        density = np.zeros((H, W))
        P = density.cumsum(axis=1)
        Q = P.cumsum(axis=1)
        verts = _rect_polygon(2, 2, 6, 6)
        c = weighted_centroid_cumsum(verts, density, P, Q)
        assert np.all(np.isfinite(c))


# ---------------------------------------------------------------------------
# V1: 拒绝采样退化输入
# ---------------------------------------------------------------------------

class TestRejectionSample:
    def test_zero_density_returns_empty_with_warning(self):
        """全零密度 (全白图经 compute_density): 立即返回空点集, 不死循环."""
        white = np.full((20, 30), 255, np.uint8)
        density = compute_density(white, invert=True)
        assert density.max() == 0.0
        rng = np.random.default_rng(0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pts = rejection_sample(density, 100, rng)
        assert pts.shape == (0, 2)

    def test_white_image_stipple_pipeline(self):
        """全白图端到端: stipple 返回空点集而非挂死."""
        white = np.full((20, 30), 255, np.uint8)
        density = compute_density(white, invert=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pts, radii = stipple(density, n_points=50, seed=0)
        assert len(pts) == 0 and len(radii) == 0

    def test_low_density_respects_max_batches(self):
        """极低密度: 触达批次上限返回部分点集 (带告警), 不无限循环."""
        density = np.zeros((10, 10))
        density[5, 5] = 1e-9   # 非零但几乎不可能采到
        rng = np.random.default_rng(0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pts = rejection_sample(density, 100, rng, max_batches=3)
        assert len(pts) < 100   # 未凑齐, 但已返回

    def test_normal_sampling(self):
        density = np.linspace(0.1, 1.0, 25).reshape(5, 5)
        rng = np.random.default_rng(0)
        pts = rejection_sample(density, 200, rng)
        assert pts.shape == (200, 2)
        assert pts[:, 0].min() >= 0 and pts[:, 0].max() < 5
        assert pts[:, 1].min() >= 0 and pts[:, 1].max() < 5


# ---------------------------------------------------------------------------
# V3/V4: 剪枝语义 (scipy 路径 + 纯 numpy 回退)
# ---------------------------------------------------------------------------

class TestPrune:
    def test_overlap_criterion(self):
        """重叠判据: d < r1 + r2 + gap 才删; 间距足够时保留."""
        pts = np.array([[0.0, 0.0], [10.0, 0.0]])
        radii = np.array([2.0, 2.0])
        p, r = prune_overlapping(pts, radii, gap=1.0)
        assert len(p) == 2            # 10 > 2+2+1, 都保留
        p, r = prune_overlapping(pts, radii, gap=100.0)
        assert len(p) == 1            # 大 gap 下必删其一

    def test_min_dist_criterion_scipy_and_pure(self):
        """min_dist 判据是纯圆心距 (V4): 半径不参与."""
        pts = np.array([[0.0, 0.0], [6.0, 0.0]])
        radii = np.array([5.0, 5.0])   # 半径大但圆心距 6 > min_dist
        if has_scipy():
            p, r = prune_min_distance(pts, radii, min_dist=5.0)
            assert len(p) == 2, "min_dist 不应含半径项 (V4)"
        p, r = _prune_min_distance_pure(pts, radii, min_dist=5.0)
        assert len(p) == 2, "纯 numpy 回退判据应为 d < min_dist (V4)"
        # 圆心距 < min_dist → 删其一
        p, r = _prune_min_distance_pure(pts, radii, min_dist=7.0)
        assert len(p) == 1

    def test_min_dist_pure_matches_scipy(self):
        if not has_scipy():
            pytest.skip("scipy 不可用")
        rng = np.random.default_rng(3)
        pts = rng.uniform(0, 50, (60, 2))
        radii = rng.uniform(1, 4, 60)
        p1, r1 = prune_min_distance(pts, radii, min_dist=5.0)
        p2, r2 = _prune_min_distance_pure(pts, radii, min_dist=5.0)
        assert len(p1) == len(p2), "纯 numpy 回退与 scipy 路径点数应一致"

    def test_overlap_pure_matches_scipy(self):
        if not has_scipy():
            pytest.skip("scipy 不可用")
        rng = np.random.default_rng(5)
        pts = rng.uniform(0, 50, (80, 2))
        radii = rng.uniform(1, 5, 80)
        p1, _ = prune_overlapping(pts, radii, gap=1.5)
        p2, _ = _prune_overlapping_pure(pts, radii, gap=1.5)
        assert len(p1) == len(p2), "纯 numpy 回退与 scipy 路径点数应一致"

    def test_return_mask_aligns_metadata(self):
        """return_mask=True: 掩码可直接对齐逐点元数据 (P3)."""
        rng = np.random.default_rng(9)
        pts = rng.uniform(0, 30, (40, 2))
        radii = rng.uniform(1, 4, 40)
        roles = np.array([f"role{i}" for i in range(40)])
        mask = prune_overlapping(pts, radii, gap=2.0, return_mask=True)
        assert mask.dtype == bool and mask.shape == (40,)
        p, r = prune_overlapping(pts, radii, gap=2.0)
        # 掩码索引的 roles 与保留点一一对应
        assert (roles[mask] == np.array([f"role{i}" for i in
                                         np.nonzero(mask)[0]])).all()
        assert len(p) == int(mask.sum())


# ---------------------------------------------------------------------------
# V5: Lloyd 松弛不丢点
# ---------------------------------------------------------------------------

class TestLloydRelax:
    @pytest.mark.skipif(not has_scipy(), reason="scipy 不可用")
    def test_lloyd_keeps_point_count(self):
        """松弛后点数不变 (被过滤单元的点保留原位, 不静默丢弃)."""
        H = W = 40
        rng = np.random.default_rng(1)
        density = np.ones((H, W))
        pts = rng.uniform(0, W, (50, 2))
        pts[0] = pts[1]    # 制造重合点 (其单元必被过滤)
        out = lloyd_relax(pts, density, n_iter=3, rng=None)
        assert len(out) == len(pts), "Lloyd 松弛不得丢点 (V5)"

    @pytest.mark.skipif(not has_scipy(), reason="scipy 不可用")
    def test_lloyd_relaxes_toward_density(self):
        """密度集中在一侧时, 点应向该侧移动."""
        H = W = 40
        rng = np.random.default_rng(2)
        density = np.zeros((H, W))
        density[:, :10] = 1.0       # 密度全在左侧
        pts = rng.uniform(0, W, (30, 2))
        out = lloyd_relax(pts, density, n_iter=5, rng=None)
        assert out[:, 0].mean() < pts[:, 0].mean()


# ---------------------------------------------------------------------------
# stipple: prune_mode 显式参数 (V6)
# ---------------------------------------------------------------------------

class TestStipplePruneMode:
    def test_prune_mode_min_dist_branch_reachable(self):
        """prune_mode="min_dist" 显式可达 (旧版需负 overlap_gap 才能触发)."""
        rng = np.random.default_rng(0)
        density = np.abs(np.add.outer(np.linspace(0, 1, 40),
                                      np.linspace(0, 1, 40)))
        pts, radii = stipple(density, n_points=200, n_iter=0,
                             min_dist=8.0, prune_mode="min_dist", seed=0)
        assert len(pts) > 0
        # 任意两点距应 ≥ min_dist (浮点容差)
        if len(pts) > 1:
            d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
            np.fill_diagonal(d, np.inf)
            assert d.min() >= 8.0 - 1e-9

    def test_prune_mode_none(self):
        density = np.ones((30, 30))
        pts, radii = stipple(density, n_points=100, n_iter=0,
                             prune_mode="none", seed=0)
        assert len(pts) == 100


# ---------------------------------------------------------------------------
# S6: kusama_depth 跨层剪枝 (纯 numpy 独立函数, 无 ultralytics 依赖)
# ---------------------------------------------------------------------------

class TestPruneFineAgainstLarge:
    from dotartkit.styles.kusama_depth import prune_fine_against_large  # noqa: E402

    def test_removes_fine_inside_large(self):
        """落入大点范围 (d < r_fine + r_large + gap) 的细点被移除."""
        from dotartkit.styles.kusama_depth import prune_fine_against_large
        pts_fine = np.array([[0.0, 0.0], [50.0, 50.0]])
        rad_fine = np.array([1.0, 1.0])
        pts_large = np.array([[2.0, 0.0]])
        rad_large = np.array([3.0])
        p, r = prune_fine_against_large(pts_fine, rad_fine,
                                        pts_large, rad_large, gap=1.0)
        # 细点 0: d=2 < 1+3+1 → 删; 细点 1: d≈70 → 留
        assert len(p) == 1 and p[0][0] == 50.0

    def test_keeps_all_when_far(self):
        from dotartkit.styles.kusama_depth import prune_fine_against_large
        rng = np.random.default_rng(0)
        pts_fine = rng.uniform(0, 100, (50, 2))
        rad_fine = np.full(50, 1.0)
        pts_large = np.array([[500.0, 500.0]])
        rad_large = np.array([5.0])
        p, r = prune_fine_against_large(pts_fine, rad_fine,
                                        pts_large, rad_large)
        assert len(p) == 50

    def test_empty_inputs(self):
        from dotartkit.styles.kusama_depth import prune_fine_against_large
        empty2, empty1 = np.empty((0, 2)), np.empty((0,))
        p, r = prune_fine_against_large(empty2, empty1,
                                        np.array([[1.0, 1.0]]),
                                        np.array([2.0]))
        assert len(p) == 0
        p, r = prune_fine_against_large(np.array([[1.0, 1.0]]),
                                        np.array([2.0]),
                                        empty2, empty1)
        assert len(p) == 1

    def test_matches_naive_loop(self):
        """与朴素双重循环结果一致 (随机大规模)."""
        from dotartkit.styles.kusama_depth import prune_fine_against_large
        rng = np.random.default_rng(11)
        pts_fine = rng.uniform(0, 80, (120, 2))
        rad_fine = rng.uniform(0.5, 2.0, 120)
        pts_large = rng.uniform(0, 80, (15, 2))
        rad_large = rng.uniform(3.0, 8.0, 15)
        gap = 1.0
        p, r = prune_fine_against_large(pts_fine, rad_fine,
                                        pts_large, rad_large, gap=gap)
        # 朴素真值
        keep = np.ones(len(pts_fine), dtype=bool)
        for i in range(len(pts_fine)):
            for j in range(len(pts_large)):
                if np.linalg.norm(pts_fine[i] - pts_large[j]) \
                        < rad_fine[i] + rad_large[j] + gap:
                    keep[i] = False
                    break
        assert len(p) == int(keep.sum())
        np.testing.assert_allclose(p, pts_fine[keep])
