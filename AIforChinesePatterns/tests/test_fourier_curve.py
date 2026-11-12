"""fcp 包的单元测试: 傅里叶曲线正逆变换、截断、变换、归一化、序列化。"""

import json
import math

import numpy as np
import pytest

from fcp import FourierCurve, resample_contour


def _circle(radius=1.0, n=256, phase=0.0):
    t = 2 * np.pi * np.arange(n) / n + phase
    return np.column_stack([radius * np.cos(t), radius * np.sin(t)])


def _star(n_points=5, outer=1.0, inner=0.4, n=512):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = outer - (outer - inner) * (0.5 + 0.5 * np.cos(n_points * t))
    return np.column_stack([r * np.cos(t - np.pi / 2), r * np.sin(t - np.pi / 2)])


class TestRoundTrip:
    def test_circle_round_trip(self):
        pts = _circle(2.0)
        c = FourierCurve.from_contour(pts, order=8)
        rec = c.to_contour(256)
        # 圆是纯一阶谐波，往返应几乎精确
        assert np.max(np.abs(np.linalg.norm(rec, axis=1) - 2.0)) < 1e-6

    def test_high_order_reconstruction_error(self):
        """足够高阶时，重建点列与原轮廓（弧长重采样后）逐点误差应很小。

        尖角星形存在 Gibbs 现象，误差收敛到 ~1e-2 量级（角点附近），
        这是傅里叶截断的固有特性而非 bug。
        """
        pts = _star()
        c = FourierCurve.from_contour(pts, order=32)
        rec = c.to_contour(1024)
        ref = resample_contour(_star(), 1024)
        err = np.linalg.norm(rec - ref, axis=1).max()
        assert err < 2e-2

    def test_center_preserved(self):
        pts = _circle() + np.array([5.0, -3.0])
        c = FourierCurve.from_contour(pts, order=4)
        assert np.allclose(c.center, (5.0, -3.0), atol=1e-9)
        rec = c.to_contour(128)
        assert np.allclose(rec.mean(axis=0), (5.0, -3.0), atol=1e-6)

    def test_nonuniform_sampling_ok(self):
        """输入点距不均匀时（弧长重参数化）结果应与均匀采样一致。"""
        t = np.sort(np.random.RandomState(0).uniform(0, 2 * np.pi, 200))
        t = np.concatenate([t[t < 2 * np.pi - 0.01], [2 * np.pi - 0.001]])
        pts = np.column_stack([np.cos(t) * 1.5, np.sin(t)])
        c = FourierCurve.from_contour(pts, order=6)
        rec = c.to_contour(256)
        r = np.linalg.norm(rec, axis=1)
        # 椭圆 a=1.5, b=1；非均匀采样+插值带来的误差 ~4%
        assert r.max() < 1.56 and r.min() > 0.95


class TestTruncation:
    def test_approximate_lower_order(self):
        pts = _star()
        c = FourierCurve.from_contour(pts, order=16)
        low = c.approximate(2)
        assert low.order == 2
        assert low.center == c.center

    def test_approximate_invalid_order(self):
        c = FourierCurve.from_contour(_circle(), order=4)
        with pytest.raises(ValueError):
            c.approximate(0)
        with pytest.raises(ValueError):
            c.approximate(5)

    def test_truncation_reduces_complexity(self):
        """低阶近似应比原曲线更"简单"（complexity 更低或重建更平滑）。"""
        pts = _star(n_points=9, outer=1.0, inner=0.2)
        c = FourierCurve.from_contour(pts, order=24)
        low = c.approximate(3)
        assert low.complexity <= c.complexity + 1e-9
        # 低阶版本的周长更接近凸包（角被抹平 → 曲率总和更小）
        def total_curvature(curve):
            p = curve.to_contour(512)
            d1 = np.roll(p, -1, axis=0) - p
            d2 = np.roll(p, -2, axis=0) - np.roll(p, -1, axis=0)
            a1 = np.arctan2(d1[:, 1], d1[:, 0])
            a2 = np.arctan2(d2[:, 1], d2[:, 0])
            return np.abs(np.angle(np.exp(1j * (a2 - a1)))).sum()
        assert total_curvature(low) < total_curvature(c)


class TestAnalysis:
    def test_circle_is_pure_first_harmonic(self):
        c = FourierCurve.from_contour(_circle(), order=8)
        amps = c.harmonic_amplitudes()
        assert amps[0] > 0.9
        assert amps[1:].max() < 1e-6

    def test_complexity_range(self):
        """复杂度单调于形状细节: 圆 ≈ 0，尖角密纹星 > 0.15。"""
        circle = FourierCurve.from_contour(_circle(), order=16)
        star = FourierCurve.from_contour(_star(n_points=16, inner=0.05), order=32)
        assert circle.complexity < 0.01
        assert star.complexity > 0.15

    def test_energy_positive(self):
        c = FourierCurve.from_contour(_star(), order=8)
        assert c.energy > 0


class TestTransform:
    def test_translate(self):
        c = FourierCurve.from_contour(_circle(), order=4)
        t = c.transformed(offset=(3.0, 4.0))
        rec = t.to_contour(64)
        assert np.allclose(rec.mean(axis=0), (3.0, 4.0), atol=1e-9)
        assert np.max(np.abs(np.linalg.norm(rec - [3, 4], axis=1) - 1.0)) < 1e-6

    def test_scale(self):
        c = FourierCurve.from_contour(_circle(), order=4)
        t = c.transformed(scale=2.5)
        rec = t.to_contour(64)
        assert np.max(np.abs(np.linalg.norm(rec, axis=1) - 2.5)) < 1e-6

    def test_rotation_preserves_shape(self):
        pts = _star()
        c = FourierCurve.from_contour(pts, order=12)
        r = c.transformed(rotation_deg=37.0)
        a = c.to_contour(256)
        b = r.to_contour(256)
        # 旋转不改变点列的半径分布（逐参数角比较会差一个相位）
        ra = np.sort(np.linalg.norm(a, axis=1))
        rb = np.sort(np.linalg.norm(b, axis=1))
        assert np.max(np.abs(ra - rb)) < 1e-9
        # 旋转 90° 的圆形副本应与原图重叠
        circ = FourierCurve.from_contour(_circle(), order=4)
        rc = circ.transformed(rotation_deg=90.0).to_contour(128)
        assert np.max(np.abs(np.linalg.norm(rc, axis=1) - 1.0)) < 1e-9

    def test_mirror(self):
        """镜像作用于形状本体（绕自身中心翻转），不改变中心位置。"""
        star_c = FourierCurve.from_contour(_star(), order=8)
        m = star_c.transformed(mirror_x=True)
        a = star_c.to_contour(256)
        b = m.to_contour(256)
        # x 坐标取反（相对中心，星形中心≈原点）
        assert np.max(np.abs(b[:, 0] + a[:, 0])) < 1e-9
        assert np.max(np.abs(b[:, 1] - a[:, 1])) < 1e-9
        assert m.center == pytest.approx(star_c.center, abs=1e-9)

    def test_composed_transform_matches_matrix(self):
        """系数域复合变换 = 对点列做 (p-center) 的旋转缩放再加 offset。"""
        pts = _star() + np.array([3.0, 2.0])  # 非原点中心，检验摆放语义
        c = FourierCurve.from_contour(pts, order=10)
        s, ang, off = 1.7, 33.0, (4.0, -2.0)
        got = c.transformed(scale=s, rotation_deg=ang, offset=off).to_contour(256)
        ref = c.to_contour(256) - np.asarray(c.center)
        th = math.radians(ang)
        R = np.array([[math.cos(th), -math.sin(th)],
                      [math.sin(th), math.cos(th)]])
        want = (ref @ R.T) * s + np.asarray(off)
        assert np.max(np.abs(got - want)) < 1e-9

    def test_invalid_scale(self):
        c = FourierCurve.from_contour(_circle(), order=2)
        with pytest.raises(ValueError):
            c.transformed(scale=0.0)


class TestNormalized:
    def test_normalized_invariant(self):
        """归一化后，平移/旋转/缩放的同一形状应得到相同结果。"""
        pts = _star()
        a = FourierCurve.from_contour(pts, order=12)
        th = math.radians(71.0)
        R = np.array([[math.cos(th), -math.sin(th)],
                      [math.sin(th), math.cos(th)]])
        moved = (pts @ R.T) * 2.3 + np.array([10.0, -4.0])
        b = FourierCurve.from_contour(moved, order=12)
        na, nb = a.normalized(), b.normalized()
        pa = na.to_contour(512)
        pb = nb.to_contour(512)
        # 主轴对齐 + 尺度归一后，两者应对齐（可能差一个起点相位 → 比较半径分布）
        ra = np.sort(np.linalg.norm(pa, axis=1))
        rb = np.sort(np.linalg.norm(pb, axis=1))
        assert np.max(np.abs(ra - rb)) < 5e-3


class TestSerialization:
    def test_json_round_trip(self):
        c = FourierCurve.from_contour(_star(), order=8)
        c2 = FourierCurve.from_json(c.to_json())
        assert c2.order == c.order
        # to_json 系数保留 6 位小数，1e-7 量级的系数会舍入到 0/1e-6
        assert np.allclose(c2.coeffs, c.coeffs, atol=2e-6)
        assert c2.center == pytest.approx(c.center, abs=1e-6)

    def test_json_compact(self):
        c = FourierCurve.from_contour(_star(n=256), order=8)
        text = c.to_json()
        assert len(text) < 2000  # 远小于 256 个点的坐标串


class TestValidation:
    def test_too_few_points(self):
        with pytest.raises(ValueError):
            FourierCurve.from_contour(np.array([[0, 0], [1, 1]]))

    def test_duplicate_adjacent_points(self):
        pts = _circle(n=64)
        pts[3] = pts[2]  # 制造重复相邻点
        with pytest.raises(ValueError):
            FourierCurve.from_contour(pts)
