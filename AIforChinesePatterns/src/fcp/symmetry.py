"""symmetry: 同形部件聚类归并（对称检测）.

传统纹样大量使用旋转/镜像重复（团花 n 重、二方连续）。分解产生的
几十上百个部件里, 很多是同一母题经相似变换摆放的副本。本模块:

  1. 对每个部件提取"位姿" (offset, scale, rotation, mirror)——
     中心/PCA 主轴/平均半径, 形状归一到单位圆;
  2. 用归一化 EFD 描述子距离做贪心聚类, 同形部件归为一簇;
  3. 每簇取面积最大的成员作为母题（medoid）, 其余成员用
     motif.transformed(位姿) 重建——Pattern 从 N 条独立曲线
     压缩为 K 个母题 + N 个摆放参数。

这是 PatternSpec 面向 LLM 生成目标的关键压缩: 团花纹样从
"100 个部件 × 独立系数"变成"几个母题 + 对称摆放规则"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .decompose import Decomposition, Part
from .fourier_curve import FourierCurve
from .pattern import Pattern, Placement

__all__ = ["PartPose", "SymmetryClustering", "cluster_parts"]

# 二面体 × 倒序的全部 8 个比较变体 (±x, ±y, 是否倒序)
_VARIANTS = (
    (1.0, 1.0, False), (1.0, -1.0, False),
    (-1.0, 1.0, False), (-1.0, -1.0, False),
    (1.0, 1.0, True), (1.0, -1.0, True),
    (-1.0, 1.0, True), (-1.0, -1.0, True),
)


def _aligned_rms(rb: np.ndarray, rr: np.ndarray) -> float:
    """两条重采样轮廓的循环移位+倒序对齐逐点 RMS。

    轮廓起点与遍历方向是 Moore 追踪的任意选择（镜像成员的点序列互为
    倒序）, 须吸收; 调用方自行决定是否吸收镜像。向量化同 _shape_distance。
    """
    n = len(rb)
    best = float("inf")
    for rrv in (rr, rr[::-1]):
        W = sliding_window_view(np.vstack([rrv, rrv]), n, axis=0)
        W = W.transpose(0, 2, 1)[:n]
        d2 = np.sum((rb[None, :, :] - W) ** 2, axis=2)
        best = min(best, float(np.sqrt(d2.mean(axis=1).min())))
    return best


@dataclass
class PartPose:
    """部件的相似变换位姿: part ≈ motif.transformed(**pose)。"""

    offset: Tuple[float, float]
    scale: float
    rotation_deg: float
    mirror: bool


def part_pose(part: Part) -> Tuple[FourierCurve, PartPose]:
    """提取部件的规范形状（单位尺度、PCA 对齐）与位姿。

    Returns:
        (canonical, pose): canonical 为归一化母题曲线（中心在原点、
        主轴对齐 x、平均半径 1）; part 的原始轮廓可由
        canonical.transformed(scale, rotation_deg, mirror_x, offset)
        精确重建。

    规范化约定（确定性, 同形部件必得同一母题）:
    eigh 特征向量列符号任意（±主轴、±次轴）, 早期用 det(rot)<0 判
    镜像既不可靠（符号任意导致漏检, 镜像对不聚簇）也与重建恒等式
    R(θ)·Mᵀ·rot = I 不自洽。改用两个三阶矩把规范形状钉到唯一变体:

        Σx³ < 0 → 整体旋转 180°（主轴方向歧义）
        Σy³ < 0 → y 翻转（反射歧义）; M_x·F = R(180°), 旋转相应 +180°

    对称形状的相应三阶矩为 0, 该歧义本身无害。位姿满足
    p = offset + s·R(θ)·M_x^k·canonical（k = mirror）。
    """
    pts = part.contour
    center = pts.mean(axis=0)
    xy = pts - center
    # PCA 主轴对齐
    cov = xy.T @ xy / len(xy)
    w, v = np.linalg.eigh(cov)
    if w[1] <= 1e-12:
        # 退化（近似直线）: 用一阶谐波方向
        w1 = part.curve.coeffs[0]
        if abs(w1[0]) + abs(w1[1]) < 1e-12:
            raise ValueError("退化部件无法提取位姿")
        ang = np.degrees(np.arctan2(w1[2], w1[0]))
        rot = np.array([[np.cos(np.radians(ang)), -np.sin(np.radians(ang))],
                        [np.sin(np.radians(ang)), np.cos(np.radians(ang))]])
    else:
        rot = v[:, [1, 0]]  # 第一主成分 → x
        if np.linalg.det(rot) < 0:
            rot = rot.copy()
            rot[:, 1] *= -1   # 规范成纯旋转; 反射记入位姿 mirror
    xy = xy @ rot
    mirror = False
    extra_rot = 0.0
    if float(np.sum(xy[:, 0] ** 3)) < 0.0:
        xy = -xy
        extra_rot += 180.0
    if float(np.sum(xy[:, 1] ** 3)) < 0.0:
        xy = xy * np.array([1.0, -1.0])
        mirror = True
        extra_rot += 180.0
    scale = np.linalg.norm(xy, axis=1).mean()
    if scale <= 1e-12:
        raise ValueError("退化部件无法提取位姿")
    canonical = FourierCurve.from_contour(
        np.column_stack([xy[:, 0] / scale, xy[:, 1] / scale]),
        order=part.order)
    # rot 的角度: 把 x 轴单位向量变换回去得到主轴方向
    theta = np.degrees(np.arctan2(rot[1, 0], rot[0, 0])) + extra_rot
    return canonical, PartPose(
        offset=(float(center[0]), float(center[1])),
        scale=float(scale),
        rotation_deg=float(theta),
        mirror=bool(mirror),
    )


def _shape_distance(a: FourierCurve, b: FourierCurve, n: int = 64) -> float:
    """两条规范曲线的形状距离（起点相位不变 + 镜像不变）。

    直接比较傅里叶系数对起点相位敏感（Moore 追踪的起点在不同部件上
    任意）, 相同形状会得到巨大伪距离。这里在弧长重采样点集上做
    循环移位对齐 + 镜像尝试, 取最小值。

    翻转搜索覆盖全部四个二面体变体 (±x, ±y): PCA 特征向量的列符号
    任意, 两个同形部件的规范形状可能差 180° 旋转或 x 镜像——实测
    精确镜像对曾因只搜 y 翻转而伪距离爆表、无法聚簇。此外轮廓
    遍历方向也是本质歧义: Moore 追踪对原形与镜像形同为顺时针,
    两者的点序列互为倒序, 循环移位吸收不了, 须再试倒序变体。

    度量 = RMS + 0.5×max（实测分离度最好: 同形花瓣 ≤0.13,
    圆vs方 ≥0.21, 默认阈值 0.18 居中）。

    实现: 8 变体 × n 移位逐点比较是 O(n²)/变体, 逐移位 np.roll 的
    分配开销使 191 部件的两两比较耗时分钟级。用 sliding_window_view
    把 8 个变体的全部循环移位拼成 (8, n, n) 张量后一次广播, 结果与
    逐移位滚动一致, 快一个数量级以上。
    """
    A = a.to_contour(n)
    A = A - A.mean(axis=0)
    B = b.to_contour(n)
    B = B - B.mean(axis=0)
    na = np.linalg.norm(A, axis=1).mean()
    if na < 1e-12:
        return float("inf")
    return _contours_distance(A, B, na)


def _contours_distance(A: np.ndarray, B: np.ndarray, na: float) -> float:
    """已中心化轮廓数组的 8 变体×全循环移位最小形状距离。

    A/B 形状 (n, 2), na 为 A 的平均半径（归一化分母）。
    """
    n = len(B)
    V = np.empty((8, n, 2))
    for v, (fx, fy, rev) in enumerate(_VARIANTS):
        Bv = B * np.array([fx, fy])
        V[v] = Bv[::-1] if rev else Bv
    Vt = np.concatenate([V, V], axis=1)                # (8, 2n, 2)
    W = sliding_window_view(Vt, n, axis=1)             # (8, n+1, 2, n)
    W = W.transpose(0, 1, 3, 2)[:, :n]                 # (8, n, n, 2)
    d2 = np.sum((A[None, None, :, :] - W) ** 2, axis=3)  # (8, n, n)
    d = np.sqrt(d2.mean(axis=2)) + 0.5 * np.sqrt(d2.max(axis=2))
    return float(d.min()) / na


def _descriptor_distance(a: FourierCurve, b: FourierCurve) -> float:
    """同形判定的公开距离入口（当前实现 = _shape_distance）。"""
    return _shape_distance(a, b)


@dataclass
class SymmetryClustering:
    """聚类结果: 簇列表 + 每部件的簇编号 + 每簇母题。"""

    clusters: List[List[int]] = field(default_factory=list)   # 每簇的部件索引
    medoids: List[int] = field(default_factory=list)          # 每簇母题部件索引
    labels: List[int] = field(default_factory=list)           # 部件 → 簇
    poses: List[PartPose] = field(default_factory=list)       # 部件 → 位姿
    part_errors: List[float] = field(default_factory=list)    # 成员用母题重建的 RMS

    @property
    def n_motifs(self) -> int:
        return len(self.clusters)

    def report(self) -> str:
        sizes = sorted((len(c) for c in self.clusters), reverse=True)
        return (f"{len(self.labels)} 部件 → {self.n_motifs} 个母题 "
                f"(簇大小 {sizes}), 归并重建平均 RMS "
                f"{np.mean(self.part_errors):.2f}px")


def cluster_parts(
    dec: Decomposition,
    tol: float = 0.18,
) -> SymmetryClustering:
    """对分解部件做同形聚类。

    Args:
        dec: 部件分解结果（parts 需按面积降序, decompose_mask 已保证）。
        tol: 归一化描述子距离阈值, 小于该值视为同形（单位尺度下,
             0.18 为校准值: 同形 ≤0.13, 异形 ≥0.21）。

    Returns:
        SymmetryClustering。
    """
    if not dec.parts:
        return SymmetryClustering()
    canon: List[FourierCurve] = []
    poses: List[PartPose] = []
    for part in dec.parts:
        c, p = part_pose(part)
        canon.append(c)
        poses.append(p)

    # 同形预筛（安全下界, 拒绝即证明不可能同形, 不会漏掉真同形对）:
    #   ① 排序半径分布: 刚体/反射不变, |‖a‖−‖b‖| ≤ ‖a−b‖;
    #   ② 排序 |x| / |y| 分布: 翻转/倒序不变, 逐点 |xA−xB| ≥
    #      ‖|xA|−|xB|‖, 排序匹配又是一维最优指派。
    # ③ 频域相关精确下界: 完整度量 = RMS + 0.5×max ≥ RMS, 而 8 变体
    #   ×全循环移位的最小 RMS 可用批量 FFT 一次算出（每对 ~20µs,
    #   实测 18145 对屏蔽 98.5%）。真实纹样部件多为有机 blob, ①②
    #   拦截率仅 ~26%, ③ 是性能主力。
    # 中心化轮廓只算一次, 各级预筛与全搜索共用。
    NS = 64  # 预筛/搜索的轮廓采样数, 须与 _shape_distance 默认一致
    conts: List[np.ndarray] = []
    ax_sorted: List[np.ndarray] = []
    ay_sorted: List[np.ndarray] = []
    radii_sorted: List[np.ndarray] = []
    radii_mean: List[float] = []
    fft_a: List[np.ndarray] = []    # 每部件 (2, NS//2+1): rfft(x), rfft(y)
    fft_b: List[np.ndarray] = []    # 每部件 (8, 2, NS//2+1): 8 变体的同上
    energy: List[float] = []
    for c in canon:
        pts = c.to_contour(NS)
        pts = pts - pts.mean(axis=0)
        radii = np.linalg.norm(pts, axis=1)
        conts.append(pts)
        ax_sorted.append(np.sort(np.abs(pts[:, 0])))
        ay_sorted.append(np.sort(np.abs(pts[:, 1])))
        radii_sorted.append(np.sort(radii))
        radii_mean.append(float(radii.mean()))
        energy.append(float(np.sum(pts ** 2)))
        fa = np.fft.rfft(pts, axis=0)                    # (NS, 2)→(NS//2+1, 2)
        fft_a.append(np.asarray(fa).T)                   # (2, NS//2+1)
        fb = np.empty((8, 2, NS // 2 + 1), dtype=complex)
        for v, (fx, fy, rev) in enumerate(_VARIANTS):
            Bv = pts * np.array([fx, fy])
            if rev:
                Bv = Bv[::-1]
            fb[v] = np.asarray(np.fft.rfft(Bv, axis=0)).T
        fft_b.append(fb)

    def _screen_reject(i: int, j: int) -> bool:
        ai = radii_mean[i]
        dr = np.mean((radii_sorted[i] - radii_sorted[j]) ** 2)
        dx = np.mean((ax_sorted[i] - ax_sorted[j]) ** 2)
        dy = np.mean((ay_sorted[i] - ay_sorted[j]) ** 2)
        if min(dr, dx + dy) / ai**2 >= tol * tol:
            return True
        # 频域精确 RMS 下界: d2mean(v,k) = (Ea+Eb−2·C(v,k))/NS,
        # C 为 A 与 B 变体的循环互相关 (相关定理, 频域乘积一次 irfft)
        prod = (np.conj(fft_a[i])[None] * fft_b[j]).sum(axis=1)  # (8, NS//2+1)
        corr = np.fft.irfft(prod, NS)                            # (8, NS)
        rms2 = (energy[i] + energy[j] - 2.0 * corr) / NS
        rms_min = np.sqrt(max(float(rms2.min()), 0.0)) / ai
        # 留 1e-9 余量防浮点舍入把边界真同形对误杀
        return rms_min >= tol * (1.0 + 1e-9)

    # 贪心聚类: 面积大的先当母题（parts 已按面积降序）
    labels = [-1] * len(dec.parts)
    clusters: List[List[int]] = []
    medoids: List[int] = []
    for i in range(len(dec.parts)):
        if labels[i] >= 0:
            continue
        cid = len(clusters)
        labels[i] = cid
        clusters.append([i])
        medoids.append(i)
        for j in range(i + 1, len(dec.parts)):
            if labels[j] >= 0:
                continue
            if _screen_reject(i, j):
                continue
            if _contours_distance(conts[i], conts[j], radii_mean[i]) < tol:
                labels[j] = cid
                clusters[cid].append(j)

    # 成员用母题位姿重建的误差（评估归并质量）
    from .contour import resample_contour
    part_errors: List[float] = [0.0] * len(dec.parts)
    for cid, members in enumerate(clusters):
        m = medoids[cid]
        for j in members:
            if j == m:
                continue
            rebuilt = canon[m].transformed(
                scale=poses[j].scale,
                rotation_deg=poses[j].rotation_deg,
                mirror_x=poses[j].mirror,
                offset=poses[j].offset,
            ).to_contour(256)
            # 弧长重采样到相同点数后中心对齐比较。轮廓起点与遍历方向
            # 都是 Moore 追踪的任意选择, 逐点比较会被二者污染（同形
            # 花瓣真实误差 0.2px 曾被虚报为 25px; 镜像成员的点序列
            # 互为倒序）——循环移位 + 倒序取最优对齐。刻意不吸收
            # 镜像: 反射重建错误必须在误差里可见。
            rb = resample_contour(rebuilt, 256)
            rr = resample_contour(dec.parts[j].contour, 256)
            rb = rb - rb.mean(axis=0)
            rr = rr - rr.mean(axis=0)
            part_errors[j] = _aligned_rms(rb, rr)

    return SymmetryClustering(
        clusters=clusters, medoids=medoids, labels=labels,
        poses=poses, part_errors=part_errors,
    )


def pattern_from_clustering(
    dec: Decomposition,
    clu: Optional[SymmetryClustering] = None,
    colors: Optional[Sequence[str]] = None,
    background: str = "#f2ead8",
    name: str = "symmetry",
    tol: float = 0.18,
) -> Pattern:
    """聚类 → 归并 Pattern（每簇一个共享母题 + 每部件一个摆放）。

    同簇成员用母题的规范形状按各自位姿摆放（形状共享, 位置/旋转/
    缩放/镜像独立）。Spec 体积从 N×(4K+2) 系数降为
    n_motifs×(4K+2) + N×4 个摆放参数。
    """
    if clu is None:
        clu = cluster_parts(dec, tol=tol)
    if not clu.clusters:
        raise ValueError("没有部件可归并")

    motifs: Dict[str, FourierCurve] = {}
    placements: List[Placement] = []
    for cid, members in enumerate(clu.clusters):
        m = clu.medoids[cid]
        canonical, _ = part_pose(dec.parts[m])
        motifs[f"motif{cid}"] = canonical

    for j, part in enumerate(dec.parts):
        cid = clu.labels[j]
        pose = clu.poses[j]
        # 逐部件配色（GUI 传 color_of(i) 列表）; 曾误按簇号 cid 索引,
        # 导致单部件改色/调色板在归并模式下全部失效
        color = (colors[j % len(colors)] if colors else "#a63b2a")
        placements.append(Placement(
            motif=f"motif{cid}",
            x=pose.offset[0], y=pose.offset[1],
            scale=pose.scale, rotation_deg=pose.rotation_deg,
            mirror_x=pose.mirror,
            color=color, filled=True,
        ))
    return Pattern(motifs=motifs, placements=placements,
                   background=background, name=name)
