"""test_remap_editing.py — 再编辑能力测试: 映射函数 × 特征 × 配色 × remap.

覆盖目标要求的全部数量指标:
- ≥8 种尺寸映射函数 (实际 10)
- ≥5 种特征通道 (实际 6)
- 10 种艺术配色
- 波点再编辑 (remap_radii 全局/局部 + 撤销)
"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.gui.polka_document import (  # noqa: E402
    PolkaDocument, ACTIVATIONS, FEATURES,
)
from dotartkit.ops.depth import DEPTH_PALETTES  # noqa: E402


@pytest.fixture
def doc():
    """渐变测试图 (暗=近), 100x140."""
    d = PolkaDocument()
    img = np.zeros((100, 140, 3), dtype=np.uint8)
    img[:] = np.linspace(10, 240, 140).astype(np.uint8)[None, :, None]
    d.load_image(img)
    d.ensure_depth("luminance")
    return d


# ---------------------------------------------------------------------------
# 数量指标
# ---------------------------------------------------------------------------

class TestCounts:
    def test_at_least_8_activations(self):
        assert len(ACTIVATIONS) >= 8
        assert len(ACTIVATIONS) == 10

    def test_at_least_5_features(self):
        assert len(FEATURES) >= 5
        assert len(FEATURES) == 6

    def test_10_palettes(self):
        assert len(DEPTH_PALETTES) == 10
        # 每套 3 色齐全
        for name, pal in DEPTH_PALETTES.items():
            assert set(pal) == {"bg", "fg_dot", "bg_dot"}, name
            for v in pal.values():
                assert len(v) == 3 and all(0 <= c <= 255 for c in v), name


# ---------------------------------------------------------------------------
# 新映射函数数学性质
# ---------------------------------------------------------------------------

class TestNewActivations:
    """用合成特征场 x∈[0,1] 直接验证公式形状."""

    X = np.linspace(0, 1, 101).astype(np.float32)
    RNG = np.random.default_rng(0)

    def _r(self, fn, alpha):
        return fn(self.X, 1.0, 10.0, alpha, self.RNG, 0.0)

    def test_log_monotone_decreasing(self):
        r = self._r(ACTIVATIONS["log"][1], 2.0)
        assert r[0] > r[-1]                      # 近大远小
        assert r[0] == pytest.approx(10.0, abs=1e-3)

    def test_cosine_shape(self):
        r = self._r(ACTIVATIONS["cosine"][1], 1.0)
        assert r[0] == pytest.approx(10.0, abs=1e-3)   # cos(0)=1
        assert r[50] == pytest.approx(5.5, abs=0.1)    # 中点 ≈ 半幅
        assert r[-1] == pytest.approx(1.0, abs=1e-3)

    def test_step_quantized(self):
        r = self._r(ACTIVATIONS["step"][1], 1.0)      # n=4 台阶
        vals = sorted(set(np.round(r, 4)))
        assert len(vals) <= 5                          # 4 台阶 + 边界

    def test_inverse_direction(self):
        r = self._r(ACTIVATIONS["inverse"][1], 1.5)
        assert r[0] < r[-1]                            # 远大近小 (倒置)

    def test_all_in_range(self):
        for key, (_, fn) in ACTIVATIONS.items():
            kwargs = {"kappa": np.zeros_like(self.X)} \
                if key in ("curvature", "depth_curv") else {}
            r = fn(self.X, 1.0, 10.0, 1.5, self.RNG, 0.2, **kwargs)
            assert r.min() >= 0.3 and r.max() <= 11.0, key
            assert np.isfinite(r).all(), key


# ---------------------------------------------------------------------------
# 特征场
# ---------------------------------------------------------------------------

class TestFeatures:
    def test_all_features_valid(self, doc):
        for name in FEATURES:
            f = doc.get_feature(name)
            assert f.shape == doc.gray.shape, name
            assert f.min() >= -1e-6 and f.max() <= 1.0 + 1e-6, name

    def test_luminance_direction(self, doc):
        f = doc.get_feature("luminance")
        # 渐变图: 左暗 → luminance 特征左高 (暗=1)
        assert f[50, 5] > f[50, 135]

    def test_geo_cache_reuse(self, doc):
        doc.get_feature("curvature")
        src = doc._geo_cache.get("src")
        doc.get_feature("gradient")            # 应命中缓存不再重算
        assert doc._geo_cache.get("src") is src

    def test_unknown_feature(self, doc):
        with pytest.raises(ValueError):
            doc.get_feature("edge_density")


# ---------------------------------------------------------------------------
# 生成: 映射 × 特征全组合
# ---------------------------------------------------------------------------

class TestGenerateCombos:
    @pytest.mark.parametrize("activation", list(ACTIVATIONS))
    @pytest.mark.parametrize("feature", list(FEATURES))
    def test_all_combos(self, doc, activation, feature):
        stats = doc.generate(n_points=300, r_max=4.0, sigma=0.0,
                             activation=activation, feature=feature,
                             prune="overlap", edge_dots=False,
                             bg_fill=False, seed=3)
        assert stats["n_dots"] > 20, f"{activation}/{feature}"
        assert stats["r_max"] <= 4.4


# ---------------------------------------------------------------------------
# 再编辑: remap_radii
# ---------------------------------------------------------------------------

class TestRemap:
    def test_remap_keeps_positions(self, doc):
        doc.generate(n_points=300, r_max=4.0, activation="power",
                     feature="depth", sigma=0.0, edge_dots=False,
                     bg_fill=False, seed=3)
        pos_before = [(round(d.x, 4), round(d.y, 4)) for d in doc.dots]
        n = doc.remap_radii("log", feature="depth", r_min=1.0,
                            r_max=8.0, alpha=2.0, sigma=0.0)
        assert n == len(doc.dots) == len(pos_before)
        pos_after = [(round(d.x, 4), round(d.y, 4)) for d in doc.dots]
        assert pos_after == pos_before         # 位置不动

    def test_remap_changes_radii(self, doc):
        doc.generate(n_points=300, r_max=4.0, sigma=0.0,
                     edge_dots=False, bg_fill=False, seed=3)
        r_before = [d.r for d in doc.dots]
        doc.remap_radii("step", r_min=1.0, r_max=9.0, alpha=0.5, sigma=0.0)
        r_after = [d.r for d in doc.dots]
        assert r_before != r_after
        assert max(r_after) <= 9.9

    def test_remap_region_local(self, doc):
        doc.generate(n_points=400, r_max=4.0, sigma=0.0,
                     edge_dots=False, bg_fill=False, seed=3)
        # 选区: 图左半一个小圆
        region = (35.0, 50.0, 25.0)
        inside = [i for i, d in enumerate(doc.dots)
                  if np.hypot(d.x - 35, d.y - 50) <= 25]
        outside_r = {i: doc.dots[i].r for i in range(len(doc.dots))
                     if np.hypot(doc.dots[i].x - 35, doc.dots[i].y - 50) > 25}
        n = doc.remap_radii("inverse", r_min=1.0, r_max=9.0,
                            alpha=1.0, sigma=0.0, region=region)
        assert n == len(inside)
        # 选区外的点半径不变
        for i, r in outside_r.items():
            assert doc.dots[i].r == r, f"选区外点 {i} 被误改"

    def test_remap_undoable(self, doc):
        doc.generate(n_points=200, r_max=4.0, sigma=0.0,
                     edge_dots=False, bg_fill=False, seed=3)
        r_before = [d.r for d in doc.dots]
        doc.remap_radii("cosine", r_min=1.0, r_max=8.0, sigma=0.0)
        assert [d.r for d in doc.dots] != r_before
        assert doc.undo()
        assert [d.r for d in doc.dots] == r_before

    def test_remap_manual_edits_survive(self, doc):
        """remap 保留手动添加/移动的点 (只有半径变)."""
        doc.generate(n_points=200, r_max=4.0, sigma=0.0,
                     edge_dots=False, bg_fill=False, seed=3)
        doc.add_dot(70, 50, 6.0)               # 手动点
        manual_pos = (doc.dots[-1].x, doc.dots[-1].y)
        doc.remap_radii("sigmoid", r_min=1.0, r_max=8.0, sigma=0.0)
        # 手动点位置保留, 半径被重映射
        assert (doc.dots[-1].x, doc.dots[-1].y) == manual_pos
        assert 0.3 <= doc.dots[-1].r <= 8.8

    def test_remap_bad_args(self, doc):
        with pytest.raises(ValueError):
            doc.remap_radii("nope")
        with pytest.raises(ValueError):
            doc.remap_radii("power", feature="nope")


# ---------------------------------------------------------------------------
# 配色渲染
# ---------------------------------------------------------------------------

class TestPalettes:
    @pytest.mark.parametrize("palette", list(DEPTH_PALETTES))
    def test_render_all_10(self, doc, palette):
        doc.generate(n_points=300, r_max=3.0, sigma=0.0,
                     edge_dots=False, bg_fill=False, seed=3)
        out = doc.render(palette)
        assert out.shape == (100, 140, 3)
        pal = DEPTH_PALETTES[palette]
        bg_rgb = pal["bg"][::-1]
        assert (out == np.array(bg_rgb)).any(), \
            f"{palette}: 背景色未出现 (画布被点完全覆盖?)"
