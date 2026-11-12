"""decompose 模块测试: 掩膜部件分解、自动阶数选择、重建保真、组装往返。"""

import json
import math

import numpy as np
import pytest

from fcp import (
    Decomposition,
    FourierCurve,
    Pattern,
    PatternSpec,
    decompose_mask,
    pattern_from_decomposition,
    render_pattern,
)


def _mask_baoxiang(size=256):
    """宝相花风格复合掩膜: 中心大圆 + 8 花瓣 + 8 外圈小圆点 + 4 角叶片。

    各部件互不相连（留缝隙），便于验证多部件分解。半径参数按 size/256
    等比缩放，保证小尺寸下部件仍在画布内且不粘连。几何约束:
    花瓣内缘 58-22=36 > 中心圆 30（留 6px 缝）；45° 花瓣外缘
    58+22=80 < 角叶内缘 104-16=88（留 8px 缝）。
    """
    k = size / 256.0
    m = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    r = np.hypot(xx - cx, yy - cy)
    # 中心圆
    m[r < 30 * k] = True
    # 8 花瓣: 椭圆中心距 58，径向半长 22
    for ang in range(0, 360, 45):
        a = math.radians(ang)
        px, py = cx + 58 * k * math.cos(a), cy + 58 * k * math.sin(a)
        # 花瓣椭圆沿径向拉长: 把坐标旋转到花瓣局部系再判椭圆
        dx, dy = xx - px, yy - py
        la = math.radians(-ang)
        ux = dx * math.cos(la) - dy * math.sin(la)
        uy = dx * math.sin(la) + dy * math.cos(la)
        m |= (ux / (22 * k)) ** 2 + (uy / (12 * k)) ** 2 <= 1
    # 8 外圈小圆点
    for ang in range(22, 360, 45):
        a = math.radians(ang)
        px, py = cx + 100 * k * math.cos(a), cy + 100 * k * math.sin(a)
        m |= np.hypot(xx - px, yy - py) < 9 * k
    # 4 角叶片
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        px, py = cx + 104 * k * math.cos(a), cy + 104 * k * math.sin(a)
        m |= np.hypot(xx - px, yy - py) < 16 * k
    return m


class TestDecomposeMask:
    def test_baoxiang_part_count(self):
        """中心 1 + 花瓣 8 + 圆点 8 + 角叶 4 = 21 个部件。"""
        dec = decompose_mask(_mask_baoxiang())
        assert len(dec.parts) == 21

    def test_parts_sorted_by_area(self):
        dec = decompose_mask(_mask_baoxiang())
        areas = [p.area for p in dec.parts]
        assert areas == sorted(areas, reverse=True)
        # 主体应是中心圆（面积 π·30² ≈ 2827）
        assert dec.parts[0].area > 2500

    def test_auto_order_within_budget(self):
        """自动阶数应在 [3, max_order] 内且圆类部件用低阶。"""
        dec = decompose_mask(_mask_baoxiang(), max_order=24, tol=0.75)
        for p in dec.parts:
            assert 3 <= p.order <= 24
        # 中心圆是纯一阶谐波，低阶即达标
        assert dec.parts[0].order <= 6

    def test_reconstruction_fidelity(self):
        """选定的阶数下重建 RMS 应 ≤ tol。"""
        tol = 0.75
        dec = decompose_mask(_mask_baoxiang(), max_order=32, tol=tol)
        for p in dec.parts:
            assert p.rms_error <= tol

    def test_min_area_filters_noise(self):
        m = _mask_baoxiang()
        m[5:8, 5:8] = True  # 9px 噪点
        dec = decompose_mask(m, min_area=24)
        assert len(dec.parts) == 21

    def test_empty_mask(self):
        dec = decompose_mask(np.zeros((32, 32), dtype=bool))
        assert dec.parts == []
        with pytest.raises(ValueError):
            dec.to_pattern()

    def test_invalid_args(self):
        with pytest.raises(ValueError):
            decompose_mask(np.zeros((8, 8), dtype=bool), max_order=2)
        with pytest.raises(ValueError):
            decompose_mask(np.zeros((8, 8), dtype=bool), tol=0.0)


class TestDecomposeAssemble:
    def test_pattern_spec_round_trip(self):
        """分解 → Pattern → Spec → Pattern，实例几何一致。"""
        dec = decompose_mask(_mask_baoxiang(128), max_order=16, tol=1.0)
        pattern = dec.to_pattern(name="baoxiang")
        spec = pattern_from_decomposition(dec, name="baoxiang")
        p2 = Pattern.from_spec(PatternSpec.from_json(spec.to_json()))
        a = pattern.instances()
        b = p2.instances()
        assert len(a) == len(b) == len(dec.parts)
        for (ca, _), (cb, _) in zip(a, b):
            assert np.allclose(ca.to_contour(128), cb.to_contour(128), atol=1e-4)
        assert p2.name == "baoxiang"

    def test_reassembled_covers_original(self):
        """重建的部件中心应与原部件质心吻合（空间对齐）。"""
        m = _mask_baoxiang()
        dec = decompose_mask(m, max_order=16, tol=1.0)
        # 部件中心应分布在大致正确的半径带上
        c = np.array([128.0, 128.0])
        radii = sorted(np.linalg.norm(p.centroid - c) for p in dec.parts)
        # 最内是中心圆(≈0)，花瓣带 ~52，圆点带 ~100，角叶带 ~88
        assert radii[0] < 2.0
        bands = [r for r in radii[1:] if r > 5]
        assert min(bands) > 40 and max(bands) < 110
        # 8 花瓣带 + 8 圆点带 + 4 角叶带 = 20 个外围部件
        assert len(bands) == 20

    def test_render_from_decomposition(self):
        """分解结果可渲染且非空。"""
        dec = decompose_mask(_mask_baoxiang(128), max_order=12, tol=1.5)
        pattern = dec.to_pattern(
            colors=["#a63b2a", "#2b5f8a", "#4a7c59", "#c99742"],
            name="baoxiang",
        )
        img = render_pattern(pattern, size=256)
        arr = np.asarray(img)
        assert arr.std() > 10

    def test_report_readable(self):
        dec = decompose_mask(_mask_baoxiang(128), max_order=12, tol=1.5)
        text = dec.report()
        assert "21 个部件" in text
        assert "part0" in text
        assert "压缩" in text
