"""contour / pattern / render 模块测试。"""

import json
import math

import numpy as np
import pytest
from PIL import Image

from fcp import (
    CurveLibrary,
    FourierCurve,
    Pattern,
    PatternSpec,
    Placement,
    extract_contours,
    render_pattern,
    resample_contour,
)


class TestContour:
    def _mask_with_square(self, size=32, r0=8, c0=8, w=12):
        m = np.zeros((size, size), dtype=bool)
        m[r0:r0 + w, c0:c0 + w] = True
        return m

    def test_single_square(self):
        m = self._mask_with_square()
        cs = extract_contours(m)
        assert len(cs) == 1
        pts = cs[0]
        # Moore 追踪从扫描序第一个像素出发, 走 3 条整边 + 2 个半边 = 4w-4
        assert len(pts) == 44
        # 中心约在 (c0 + w/2 + 0.5, r0 + w/2 + 0.5) = (14.5, 14.5)
        assert np.allclose(pts.mean(axis=0), (14.5, 14.5), atol=0.5)

    def test_two_components(self):
        m = np.zeros((48, 64), dtype=bool)
        m[5:15, 5:15] = True
        m[25:40, 30:45] = True
        cs = extract_contours(m)
        assert len(cs) == 2
        # 小于 min_area 的噪点被忽略
        m[45:46, 45:46] = True
        cs2 = extract_contours(m, min_area=4)
        assert len(cs2) == 2

    def test_hole_not_traced_separately(self):
        """4-连通前景追踪只走外边界；环形的洞不单独成轮廓（首版约定）。"""
        m = np.zeros((32, 32), dtype=bool)
        m[4:28, 4:28] = True
        m[12:20, 12:20] = False  # 挖洞
        cs = extract_contours(m)
        assert len(cs) == 1

    def test_contour_to_fourier_round_trip(self):
        m = self._mask_with_square(size=64, r0=8, c0=8, w=24)
        pts = extract_contours(m)[0]
        c = FourierCurve.from_contour(pts, order=12)
        rec = c.to_contour(512)
        # 重建轮廓贴着原方形边界（像素中心坐标 8.5 与 31.5，容 Gibbs 振铃）
        x_lo, x_hi = rec[:, 0].min(), rec[:, 0].max()
        assert 8.5 - 0.15 < x_lo < 8.5 + 0.15
        assert 31.5 - 0.15 < x_hi < 31.5 + 0.15

    def test_resample(self):
        t = np.linspace(0, 2 * np.pi, 100, endpoint=False)
        pts = np.column_stack([np.cos(t), np.sin(t)])
        rs = resample_contour(pts, 64)
        assert len(rs) == 64
        # 64 边内接多边形的半径 = cos(π/64)，插值弦偏差 ~5e-4 是固有的
        assert np.max(np.abs(np.linalg.norm(rs, axis=1) - 1.0)) < 1e-3

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            extract_contours(np.zeros((3, 3, 3)))
        with pytest.raises(ValueError):
            resample_contour(np.array([[0, 0], [1, 1]]))


class TestPattern:
    def _motifs(self):
        return {
            "petal": CurveLibrary.petal(n_petals=6, order=10),
            "dot": CurveLibrary.circle(radius=0.5, order=3),
        }

    def test_single_placement(self):
        p = Pattern(motifs=self._motifs(), placements=[
            Placement(motif="petal", x=0, y=0, color="#aa3333"),
        ])
        inst = p.instances()
        assert len(inst) == 1
        assert inst[0][0].order == 10

    def test_rosette_expansion(self):
        p = Pattern(motifs=self._motifs(), placements=[
            Placement(motif="petal", mode="rosette", n_fold=8,
                      ring_radius=2.0, scale=0.5, color="#3333aa"),
        ])
        inst = p.instances()
        assert len(inst) == 8
        # 副本中心分布在半径 2 的圆上
        centers = np.array([c.center for c, _ in inst])
        r = np.linalg.norm(centers, axis=1)
        assert np.allclose(r, 2.0, atol=1e-9)
        # 相邻副本夹角 45°（含负角，先模 360 再排序）
        angs = np.sort(np.degrees(np.arctan2(centers[:, 1], centers[:, 0])) % 360.0)
        assert np.allclose(np.diff(angs), 45.0, atol=1e-6)

    def test_tile_expansion(self):
        p = Pattern(motifs=self._motifs(), placements=[
            Placement(motif="dot", mode="tile", tile_dx=3.0, tile_dy=2.0,
                      tile_nx=4, tile_ny=3),
        ])
        assert len(p.instances()) == 12
        xs = sorted({round(c.center[0], 6) for c, _ in p.instances()})
        ys = sorted({round(c.center[1], 6) for c, _ in p.instances()})
        assert xs == [0.0, 3.0, 6.0, 9.0]
        assert ys == [0.0, 2.0, 4.0]

    def test_unknown_motif(self):
        p = Pattern(motifs=self._motifs(), placements=[
            Placement(motif="nope"),
        ])
        with pytest.raises(KeyError):
            p.instances()

    def test_unknown_mode(self):
        p = Pattern(motifs=self._motifs(), placements=[
            Placement(motif="dot", mode="spiral"),
        ])
        with pytest.raises(ValueError):
            p.instances()

    def test_spec_round_trip(self):
        p = Pattern(
            motifs=self._motifs(),
            placements=[
                Placement(motif="petal", x=1.0, y=-1.0, scale=0.8,
                          rotation_deg=15.0, mirror_x=True, color="#123456"),
                Placement(motif="dot", mode="rosette", n_fold=5,
                          ring_radius=1.5),
            ],
            name="demo",
        )
        spec = p.to_spec()
        text = spec.to_json()
        spec2 = PatternSpec.from_json(text)
        p2 = Pattern.from_spec(spec2)
        # 展开后的实例几何一致（容 JSON 6 位小数舍入；-0.0==0.0 不影响）
        a = p.instances()
        b = p2.instances()
        assert len(a) == len(b)
        for (ca, pla), (cb, plb) in zip(a, b):
            assert np.allclose(ca.to_contour(64), cb.to_contour(64), atol=1e-4)
            assert pla.to_dict() == plb.to_dict()
        assert p2.name == "demo"

    def test_spec_is_llm_friendly(self):
        """Spec JSON 应小而结构化，适合作为 LLM 的生成目标。"""
        p = Pattern(
            motifs=self._motifs(),
            placements=[Placement(motif="dot", mode="tile", tile_nx=3, tile_ny=3)],
        )
        text = p.to_spec().to_json()
        assert len(text) < 4000
        obj = json.loads(text)
        assert set(obj.keys()) == {"name", "background", "motifs", "placements"}


class TestCurveLibrary:
    def test_shapes_closed(self):
        for curve in [CurveLibrary.circle(), CurveLibrary.petal(),
                      CurveLibrary.cloud_scroll(), CurveLibrary.rounded_square()]:
            pts = curve.to_contour(512)
            # 封闭: 首尾距离在一个采样步长以内
            step = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).mean()
            assert np.linalg.norm(pts[0] - pts[-1]) <= step + 1e-9
            # 非退化
            assert curve.energy > 1e-6

    def test_petal_fold_structure(self):
        """六瓣花的能量集中在第 5/6/7 阶谐波（n 瓣调制的主边带）。"""
        c = CurveLibrary.petal(n_petals=6, order=12)
        amps = c.harmonic_amplitudes()
        band = amps[4:8].sum()
        assert band > 0.1  # 该频带显著
        assert amps[1] < 0.01  # 二阶残余极小
        assert amps[8:].max() < 0.05  # 高阶快速衰减


class TestRender:
    def test_render_basic(self):
        p = Pattern(
            motifs={
                "petal": CurveLibrary.petal(n_petals=8, order=12),
                "dot": CurveLibrary.circle(0.35, order=3),
            },
            placements=[
                Placement(motif="petal", color="#b03a2e", filled=True),
                Placement(motif="dot", mode="rosette", n_fold=8,
                          ring_radius=1.25, scale=1.0, color="#1a5276"),
                Placement(motif="dot", scale=0.6, color="#f0c419"),
            ],
        )
        img = render_pattern(p, size=256)
        assert isinstance(img, Image.Image)
        assert img.size == (256, 256)
        arr = np.asarray(img)
        # 背景不是全白/全单色 → 确实画了东西
        assert arr.std() > 10

    def test_render_empty_raises(self):
        p = Pattern(motifs={"a": CurveLibrary.circle()}, placements=[])
        with pytest.raises(ValueError):
            render_pattern(p)
