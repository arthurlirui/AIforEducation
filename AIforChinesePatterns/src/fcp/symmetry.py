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

from .decompose import Decomposition, Part
from .fourier_curve import FourierCurve
from .pattern import Pattern, Placement

__all__ = ["PartPose", "SymmetryClustering", "cluster_parts"]


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
        近似重建。
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
        mirror = False
    else:
        rot = v[:, [1, 0]]  # 第一主成分 → x
        mirror = np.linalg.det(rot) < 0
        if mirror:
            rot = rot.copy()
            rot[:, 1] *= -1
    xy = xy @ rot
    scale = np.linalg.norm(xy, axis=1).mean()
    if scale <= 1e-12:
        raise ValueError("退化部件无法提取位姿")
    canonical = FourierCurve.from_contour(
        np.column_stack([xy[:, 0] / scale, xy[:, 1] / scale]),
        order=part.order)
    # rot 的角度: 把 x 轴单位向量变换回去得到主轴方向
    theta = np.degrees(np.arctan2(rot[1, 0], rot[0, 0]))
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

    度量 = RMS + 0.5×max（实测分离度最好: 同形花瓣 ≤0.13,
    圆vs方 ≥0.21, 默认阈值 0.18 居中）。
    """
    A = a.to_contour(n)
    A = A - A.mean(axis=0)
    B = b.to_contour(n)
    B = B - B.mean(axis=0)
    na = np.linalg.norm(A, axis=1).mean()
    if na < 1e-12:
        return float("inf")
    best = float("inf")
    for flip in (1.0, -1.0):
        Bf = B * np.array([1.0, flip])
        for k in range(n):
            d2 = np.sum((A - np.roll(Bf, k, axis=0)) ** 2, axis=1)
            d = np.sqrt(d2.mean()) + 0.5 * np.sqrt(d2.max())
            if d < best:
                best = d
    return best / na


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
            if _descriptor_distance(canon[i], canon[j]) < tol:
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
            # 弧长重采样到相同点数后中心对齐比较
            rb = resample_contour(rebuilt, 256)
            rr = resample_contour(dec.parts[j].contour, 256)
            rb = rb - rb.mean(axis=0)
            rr = rr - rr.mean(axis=0)
            part_errors[j] = float(np.sqrt(np.mean(np.sum(
                (rb - rr) ** 2, axis=1))))

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
        color = (colors[cid % len(colors)] if colors else "#a63b2a")
        placements.append(Placement(
            motif=f"motif{cid}",
            x=pose.offset[0], y=pose.offset[1],
            scale=pose.scale, rotation_deg=pose.rotation_deg,
            mirror_x=pose.mirror,
            color=color, filled=True,
        ))
    return Pattern(motifs=motifs, placements=placements,
                   background=background, name=name)
