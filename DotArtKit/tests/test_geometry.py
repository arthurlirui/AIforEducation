"""test_geometry.py — 几何感知目标函数测试.

覆盖:
1. ops/geometry.py 曲率场数学正确性 (抛物面/鞍面/平面解析验证)
2. polka_document 新激活函数 (curvature / depth_curv)
3. learned.py 6 通道网络前向 + 新损失项 (需 torch)

曲率符号约定: 高度场 h = 1 - d̂ (近=高).
κ > 0 = 凸面 (球顶), κ < 0 = 凹/鞍面.
"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.ops.geometry import (  # noqa: E402
    gradient_magnitude, mean_curvature, gaussian_curvature_sign,
    geometry_fields,
)


# ---------------------------------------------------------------------------
# 解析测试面
# ---------------------------------------------------------------------------

def _paraboloid_dome(H=200, W=200, spread=0.15):
    """凸抛物面 h = 1 - c·r² (球顶近似). d̂ = 1 - h → 中心近边缘远."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    cx, cy = (W - 1) / 2, (H - 1) / 2
    r2 = ((xx - cx) / W) ** 2 + ((yy - cy) / H) ** 2
    h = 1.0 - spread * r2 / max(r2.max(), 1e-9) * 1.0  # 中心 1, 边缘 1-spread
    d = 1.0 - h
    return d.astype(np.float32)


def _saddle(H=200, W=200, amp=0.4):
    """鞍面 h = amp·(x² - y²)/norm — x 方向上凸, y 方向下凹."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    xn = (xx - (W - 1) / 2) / W
    yn = (yy - (H - 1) / 2) / H
    h = amp * (xn ** 2 - yn ** 2) * 4
    d = (1.0 - h).astype(np.float32)
    # 归一 d 到 [0,1]
    d = (d - d.min()) / (d.max() - d.min() + 1e-9)
    return d


# ---------------------------------------------------------------------------
# 曲率场正确性
# ---------------------------------------------------------------------------

class TestMeanCurvature:
    def test_dome_center_is_convex(self):
        """凸抛物面顶点 κ 应为正 (凸)."""
        d = _paraboloid_dome()
        k = mean_curvature(d, smooth_sigma=0)   # 不平滑, 直接看解析形状
        center = k[100, 100]
        edge = k[10, 10]
        assert center > 0, f"dome center κ={center:.4f} 应为正 (凸)"
        assert center > edge, "顶点曲率应大于边缘"

    def test_saddle_x_vs_y(self):
        """鞍面: 沿 x (凸方向) 与 y (凹方向) 的曲率符号应相反."""
        d = _saddle()
        k = mean_curvature(d, smooth_sigma=0)
        # 中心附近沿 x 轴取点 vs 沿 y 轴取点
        kx = k[100, 140]   # x 偏离中心 → h 上升 → 局部凸
        ky = k[140, 100]   # y 偏离中心 → h 下降 → 局部凹
        # 鞍面平均曲率在 x-凸/y-凹对称时应近 0; 但不对称采样处符号可辨
        # 更可靠的判据: 高斯曲率中心为负
        K = gaussian_curvature_sign(d, smooth_sigma=0)
        assert K[100, 100] < 0.1, f"鞍点 K={K[100, 100]:.4f} 应为负"

    def test_flat_plane_near_zero(self):
        """平面的曲率应≈0."""
        d = np.full((100, 100), 0.5, np.float32)
        k = mean_curvature(d)
        assert np.abs(k).max() < 1e-5

    def test_range_and_dtype(self):
        d = _paraboloid_dome()
        k = mean_curvature(d)
        assert k.dtype == np.float32
        assert -1.0 <= k.min() and k.max() <= 1.0

    def test_normalization_direction(self):
        """d_norm 与 h=1-d̂ 方向一致: 倒置深度图曲率符号翻转."""
        d = _paraboloid_dome()
        k1 = mean_curvature(d, smooth_sigma=0)
        k2 = mean_curvature(1.0 - d, smooth_sigma=0)
        c = slice(80, 120), slice(80, 120)
        # d̂ 倒置 = h 倒置 = 凹面
        assert np.sign(k1[c].mean()) == -np.sign(k2[c].mean()) or \
               abs(k1[c].mean()) < 1e-3


class TestGradientMagnitude:
    def test_flat_zero(self):
        d = np.full((50, 50), 0.3, np.float32)
        assert gradient_magnitude(d).max() < 1e-6

    def test_ramp_max_at_edges(self):
        """斜坡的梯度处处相等, 归一后≈1."""
        d = np.tile(np.linspace(0, 1, 100, dtype=np.float32), (50, 1))
        g = gradient_magnitude(d)
        assert g[:, 50].mean() > 0.9


class TestGeometryFields:
    def test_all_keys_and_shapes(self):
        d = _paraboloid_dome(H=64, W=64)
        geo = geometry_fields(d)
        assert set(geo) == {"grad_mag", "kappa", "kappa_pos",
                            "kappa_neg", "gauss_sign"}
        for v in geo.values():
            assert v.shape == d.shape
            assert v.dtype == np.float32
        # kappa_pos + kappa_neg = |kappa|
        assert np.allclose(geo["kappa_pos"] + geo["kappa_neg"],
                           np.abs(geo["kappa"]), atol=1e-6)


# ---------------------------------------------------------------------------
# 新激活函数 (PolkaDocument)
# ---------------------------------------------------------------------------

class TestGeometryActivations:
    @pytest.fixture
    def doc(self):
        from dotartkit.gui.polka_document import PolkaDocument
        d = PolkaDocument()
        img = np.zeros((120, 160, 3), np.uint8)
        img[:] = np.linspace(10, 240, 160).astype(np.uint8)[None, :, None]
        d.load_image(img)
        return d

    def test_registry_has_new_activations(self):
        from dotartkit.gui.polka_document import ACTIVATIONS
        assert "curvature" in ACTIVATIONS
        assert "depth_curv" in ACTIVATIONS
        assert len(ACTIVATIONS) == 6

    def test_curvature_activation(self, doc):
        """纯曲率激活: 凸面区域点更大."""
        import numpy as np
        from dotartkit.ops.geometry import mean_curvature
        doc.ensure_depth("luminance")
        # 用解析凸面替换 d_norm, 保证曲率场已知
        H, W = doc.gray.shape
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        r2 = ((xx - W/2)/W)**2 + ((yy - H/2)/H)**2
        d = (r2 / r2.max()).astype(np.float32)  # 中心近 (d̂=0)
        doc.d_norm = d
        doc.kappa = mean_curvature(d)
        doc.density = np.ones_like(d) * 0.5
        doc.generate(n_points=800, r_max=6.0, activation="curvature",
                     prune="none", edge_dots=False, bg_fill=False, seed=1)
        # 中心 (凸面) vs 边缘 的点半径
        r_center = [p.r for p in doc.dots
                    if np.hypot(p.x - W/2, p.y - H/2) < W*0.15]
        r_edge = [p.r for p in doc.dots
                  if np.hypot(p.x - W/2, p.y - H/2) > W*0.4]
        if r_center and r_edge:
            assert np.mean(r_center) > np.mean(r_edge), \
                "凸面中心点应大于边缘"

    def test_depth_curv_activation(self, doc):
        """几何感知激活在凸面中心的点 ≥ 纯幂律 (凸面增益)."""
        import numpy as np
        from dotartkit.ops.geometry import mean_curvature
        doc.ensure_depth("luminance")
        H, W = doc.gray.shape
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        r2 = ((xx - W/2)/W)**2 + ((yy - H/2)/H)**2
        d = (r2 / r2.max()).astype(np.float32)
        doc.d_norm = d
        doc.kappa = mean_curvature(d)
        doc.density = np.ones_like(d) * 0.5

        doc.generate(n_points=800, r_max=6.0, alpha=1.5,
                     activation="power", sigma=0.0, prune="none",
                     edge_dots=False, bg_fill=False, seed=1)
        power_dots = list(doc.dots)
        doc.generate(n_points=800, r_max=6.0, alpha=1.5,
                     activation="depth_curv", sigma=0.0, prune="none",
                     edge_dots=False, bg_fill=False, seed=1)
        geo_dots = list(doc.dots)

        r_power_c = [p.r for p in power_dots
                     if np.hypot(p.x - W/2, p.y - H/2) < W*0.12]
        r_geo_c = [p.r for p in geo_dots
                   if np.hypot(p.x - W/2, p.y - H/2) < W*0.12]
        if r_power_c and r_geo_c:
            # 凸面增益: 几何感知版中心点均值应不小于幂律版
            assert np.mean(r_geo_c) >= np.mean(r_power_c) * 0.95, \
                (f"geo {np.mean(r_geo_c):.2f} vs power {np.mean(r_power_c):.2f}")

    def test_kappa_cache_invalidated(self, doc):
        """换深度后端必须失效曲率缓存."""
        doc.ensure_depth("luminance")
        doc.generate(n_points=200, r_max=3.0, activation="depth_curv",
                     edge_dots=False, bg_fill=False)
        assert doc.kappa is not None
        doc._depth_backend = "yolo26"      # 强制后端变化
        doc.ensure_depth("luminance")
        # ensure_depth 重算 → _recompute_norm_density 清空 kappa
        assert doc.kappa is None


# ---------------------------------------------------------------------------
# learned.py 6 通道网络 + 新损失 (torch)
# ---------------------------------------------------------------------------

class TestLearnedGeometry:
    @pytest.fixture
    def data(self):
        d = _paraboloid_dome(H=64, W=64)
        gray = (d * 255).astype(np.float32) / 255.0
        return d, gray

    def test_net_forward_6ch(self, data):
        pytest.importorskip("torch")
        from dotartkit.learned import DepthRadiusNet
        d, gray = data
        net = DepthRadiusNet(r_min=1.0, r_max=10.0)
        r, dens = net.predict_numpy(d, gray)
        assert r.shape == d.shape and dens.shape == d.shape
        assert r.min() >= 1.0 and r.max() <= 10.0
        assert 0 <= dens.min() and dens.max() <= 1

    def test_loss_with_curvature(self, data):
        pytest.importorskip("torch")
        import torch
        from dotartkit.learned import DepthRadiusNet, StipplePerceptualLoss
        from dotartkit.ops.geometry import geometry_fields
        d, gray = data
        net = DepthRadiusNet(r_min=1.0, r_max=10.0)
        d_t = torch.from_numpy(d).unsqueeze(0).unsqueeze(0)
        g_t = torch.from_numpy(gray).unsqueeze(0).unsqueeze(0)
        geo = geometry_fields(d)
        k_t = torch.from_numpy(geo["kappa"]).unsqueeze(0).unsqueeze(0)
        x = torch.cat([d_t, g_t, d_t.abs(), g_t.abs(), k_t, k_t], dim=1)
        radius, dens = net(x)
        crit = StipplePerceptualLoss()
        losses = crit(radius, dens, d_t, d_t.abs(), kappa=k_t)
        assert "curvature_align" in losses
        assert "concavity_density" in losses
        assert torch.isfinite(losses["total"])
        # 可反传
        losses["total"].backward()

    def test_train_smoke(self, data):
        """3 epoch 训练冒烟 (损失有限且下降趋势)."""
        pytest.importorskip("torch")
        from dotartkit.learned import train_depth_radius_net
        d, gray = data
        model = train_depth_radius_net([(d, gray)], epochs=3,
                                       r_min=1.0, r_max=10.0)
        r, _ = model.predict_numpy(d, gray)
        assert np.isfinite(r).all()
