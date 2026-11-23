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


# ----------------------------------------------------------------------
# 2026-11 审阅回归: 配色索引 / 误差对齐 / 镜像与旋转位姿
# ----------------------------------------------------------------------
def _triskelion_mask(placements, size=256):
    """非对称三圆部件（头+右上小圆+右下尾, 半径各异）。

    placements = [(cx, cy, 旋转°, 镜像), ...], 同一母题经刚体/反射摆放。
    """
    m = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    subs = [((0.0, 0.0), 22.0), ((17.0, -13.0), 9.0), ((22.0, 13.0), 6.0)]
    for cx, cy, rot_deg, mirror in placements:
        a = math.radians(rot_deg)
        for (ox, oy), r in subs:
            x = -ox if mirror else ox
            lx = x * math.cos(a) - oy * math.sin(a)
            ly = x * math.sin(a) + oy * math.cos(a)
            m[np.hypot(xx - (cx + lx), yy - (cy + ly)) < r] = True
    return m


def _aligned_rms_noflip(rebuilt, ref, n=256):
    """循环移位+倒序对齐的 RMS; 刻意不吸收镜像——反射重建错误必须可见。

    轮廓起点与遍历方向是 Moore 追踪的任意选择（镜像成员的点序列互为
    倒序）, 须吸收; 翻转是几何差异, 不吸收。
    """
    from fcp.contour import resample_contour
    rb = resample_contour(rebuilt, n)
    rr = resample_contour(ref, n)
    rb = rb - rb.mean(axis=0)
    rr = rr - rr.mean(axis=0)
    return min(
        float(np.sqrt(np.mean(np.sum(
            (rb - np.roll(rrv, k, axis=0)) ** 2, axis=1))))
        for rrv in (rr, rr[::-1]) for k in range(n))


class TestMergeRegressions:
    def test_per_part_colors_preserved(self):
        """归并 Pattern 应逐部件保留颜色（修复: 曾误按簇号 cid 索引,
        单部件改色与调色板轮转在归并模式下全部失效, 7/9 部件错配）。"""
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        colors = [f"#{i * 111111:06x}" for i in range(len(dec.parts))]
        colors[3] = "#ffffff"                      # 模拟单部件改色
        pat = pattern_from_clustering(dec, colors=colors, name="t")
        assert [pl.color for pl in pat.placements] == colors

    def test_part_errors_phase_aligned(self):
        """重建误差须吸收起点相位与遍历方向（修复: 真实 0.2px 的同形
        花瓣曾被虚报为 24.8px, report()/GUI 归并 RMS 标签全部失真）。"""
        mask = _rosette_mask()
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        clu = cluster_parts(dec)
        assert max(clu.part_errors) < 2.0

    def test_mirror_pair_merged_and_rebuilt(self):
        """非对称部件与其精确镜像应聚为一簇且重建不差反射（修复前:
        镜像对不聚簇——距离搜索无倒序/四象限变体; mirror 标志也双双
        漏检——det(eigh 特征向量) 判据不可靠）。"""
        mask = _triskelion_mask([(60, 128, 0, False), (196, 128, 0, True)])
        dec = decompose_mask(mask, max_order=16, tol=0.8)
        assert len(dec.parts) == 2
        clu = cluster_parts(dec)
        assert clu.n_motifs == 1
        # 镜像对的 mirror 标志必相反
        assert clu.poses[0].mirror != clu.poses[1].mirror
        m = clu.medoids[0]
        canon_m, _ = part_pose(dec.parts[m])
        for j in range(2):
            rebuilt = canon_m.transformed(
                scale=clu.poses[j].scale,
                rotation_deg=clu.poses[j].rotation_deg,
                mirror_x=clu.poses[j].mirror,
                offset=clu.poses[j].offset).to_contour(256)
            assert _aligned_rms_noflip(rebuilt, dec.parts[j].contour) < 3.0

    def test_rotated_copies_cluster_and_rebuild(self):
        """非对称母题的旋转/反射摆放副本应聚为一簇（修复前: PCA 特征
        向量列符号歧义产生的 180°/镜像变体无搜索覆盖, 同形不聚,
        真实纹样 191 部件只归并出 153 母题的部分原因）。"""
        mask = _triskelion_mask([(64, 64, 0, False), (196, 70, 73, False),
                                 (128, 200, 211, True)])
        dec = decompose_mask(mask, max_order=16, tol=0.8)
        assert len(dec.parts) == 3
        clu = cluster_parts(dec)
        assert clu.n_motifs == 1
        m = clu.medoids[0]
        canon_m, _ = part_pose(dec.parts[m])
        for j in range(3):
            rebuilt = canon_m.transformed(
                scale=clu.poses[j].scale,
                rotation_deg=clu.poses[j].rotation_deg,
                mirror_x=clu.poses[j].mirror,
                offset=clu.poses[j].offset).to_contour(256)
            assert _aligned_rms_noflip(rebuilt, dec.parts[j].contour) < 3.0
