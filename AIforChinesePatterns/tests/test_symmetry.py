"""symmetry 模块测试: 位姿提取、同形聚类、归并 Pattern。"""

import math

import numpy as np
import pytest

from fcp import (
    CurveLibrary,
    Decomposition,
    FourierCurve,
    Pattern,
    decompose_mask,
    pattern_from_clustering,
    render_pattern,
)
from fcp.symmetry import PartPose, cluster_parts, part_pose


def _rosette_mask(size=256, n_fold=8):
    """标准 n 重团花掩膜: 中心圆 + n 个旋转椭圆花瓣（互不相连）。"""
    m = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    m[np.hypot(xx - cx, yy - cy) < 30] = True
    for i in range(n_fold):
        a = 2 * math.pi * i / n_fold
        px, py = cx + 60 * math.cos(a), cy + 60 * math.sin(a)
        dx, dy = xx - px, yy - py
        la = -a
        ux = dx * math.cos(la) - dy * math.sin(la)
        uy = dx * math.sin(la) + dy * math.cos(la)
        m |= (ux / 20) ** 2 + (uy / 10) ** 2 <= 1
    return m


class TestPartPose:
    def test_pose_circle(self):
        """圆: 位姿给出中心 + 半径（圆旋转/镜像不敏感, 主轴任意是正常现象）。"""
        mask = np.zeros((64, 64), bool)
        yy, xx = np.mgrid[0:64, 0:64]
        mask[np.hypot(xx - 30, yy - 34) < 15] = True
        dec = decompose_mask(mask, max_order=8, tol=0.5)
        canonical, pose = part_pose(dec.parts[0])
        assert pose.offset == pytest.approx((30.0, 34.0), abs=1.0)
        assert pose.scale == pytest.approx(15.0, rel=0.05)

    def test_pose_ellipse_stable_axis(self):
        """椭圆: PCA 主轴稳定, 长轴应对齐 x（rotation ≈ 0 或 90）。"""
        mask = np.zeros((128, 128), bool)
        yy, xx = np.mgrid[0:128, 0:128]
        dx, dy = xx - 64, yy - 64
        ang = math.radians(-30)
        ux = dx * math.cos(ang) - dy * math.sin(ang)
        uy = dx * math.sin(ang) + dy * math.cos(ang)
        mask[(ux / 40) ** 2 + (uy / 15) ** 2 <= 1] = True
        dec = decompose_mask(mask, max_order=12, tol=0.8)
        canonical, pose = part_pose(dec.parts[0])
        # 原椭圆长轴方向 -30°, 位姿旋转应把它转回 x 轴附近
        assert pose.rotation_deg % 180 == pytest.approx(30.0, abs=5.0) or \
            pose.rotation_deg % 180 == pytest.approx(-150.0, abs=5.0)

    def test_canonical_is_unit_scale(self):
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        for part in dec.parts:
            canonical, _ = part_pose(part)
            pts = canonical.to_contour(256)
            r = np.linalg.norm(pts, axis=1).mean()
            assert r == pytest.approx(1.0, abs=0.05)

    def test_rebuild_from_pose(self):
        """母题按位姿重建应近似还原部件轮廓（形状+位置）。"""
        mask = _rosette_mask(size=192, n_fold=6)
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        part = dec.parts[1]  # 某个花瓣
        canonical, pose = part_pose(part)
        rebuilt = canonical.transformed(
            scale=pose.scale, rotation_deg=pose.rotation_deg,
            mirror_x=pose.mirror, offset=pose.offset).to_contour(256)
        # 中心吻合
        assert rebuilt.mean(axis=0) == pytest.approx(
            part.contour.mean(axis=0), abs=1.5)
        # 半径分布吻合（形状保真）
        rr = np.sort(np.linalg.norm(rebuilt - rebuilt.mean(axis=0), axis=1))
        rs = np.sort(np.linalg.norm(
            part.contour - part.contour.mean(axis=0), axis=1))
        # 重采样数量不同, 比较分位数
        q = np.linspace(0.05, 0.95, 19)
        assert np.percentile(rr, q * 100) == pytest.approx(
            np.percentile(rs, q * 100), rel=0.08)


class TestClusterParts:
    def test_rosette_clusters(self):
        """标准 8 重团花: 中心圆 1 簇 + 花瓣 1 簇 = 2 个母题。"""
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        assert len(dec.parts) == 9  # 1 中心 + 8 花瓣
        clu = cluster_parts(dec)
        assert clu.n_motifs == 2
        sizes = sorted((len(c) for c in clu.clusters), reverse=True)
        assert sizes == [8, 1]

    def test_distinct_shapes_not_merged(self):
        """圆形与方形不应聚类到一起。"""
        mask = np.zeros((128, 128), bool)
        yy, xx = np.mgrid[0:128, 0:128]
        mask[np.hypot(xx - 32, yy - 32) < 16] = True
        mask[70:100, 70:100] = True
        dec = decompose_mask(mask, max_order=16, tol=0.8)
        clu = cluster_parts(dec)
        assert clu.n_motifs == 2

    def test_empty(self):
        clu = cluster_parts(Decomposition())
        assert clu.n_motifs == 0
        with pytest.raises(ValueError):
            pattern_from_clustering(Decomposition(), clu)

    def test_report(self):
        mask = _rosette_mask(size=192, n_fold=6)
        dec = decompose_mask(mask, max_order=12, tol=1.2)
        clu = cluster_parts(dec)
        text = clu.report()
        assert "母题" in text and "RMS" in text


class TestPatternFromClustering:
    def test_spec_compression(self):
        """归并后 Spec 应显著小于逐部件 Spec（母题共享）。"""
        import json
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        # 逐部件 spec
        big = dec.to_pattern().to_spec().to_json()
        # 归并 spec
        pattern = pattern_from_clustering(dec, name="rosette")
        small = pattern.to_spec().to_json()
        assert len(small) < len(big) * 0.6
        obj = json.loads(small)
        assert len(obj["motifs"]) == 2          # 2 个共享母题
        assert len(obj["placements"]) == 9      # 9 个摆放

    def test_instances_match_parts(self):
        """归并 Pattern 展开的实例数 = 部件数, 位置对应。"""
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        pattern = pattern_from_clustering(dec, name="rosette")
        inst = pattern.instances()
        assert len(inst) == 9
        centers = np.array([c.center for c, _ in inst])
        ref = np.array([p.contour.mean(axis=0) for p in dec.parts])
        # 逐实例顺序对应部件顺序
        assert np.max(np.abs(centers - ref)) < 2.0

    def test_render_smoke(self):
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=12, tol=1.2)
        pattern = pattern_from_clustering(
            dec, colors=["#a63b2a", "#2b5f8a"], name="rosette")
        img = render_pattern(pattern, size=256)
        assert np.asarray(img).std() > 10
