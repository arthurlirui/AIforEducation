"""decompose: 真实纹样掩膜的部件分解与 EFD 编码.

把一幅纹样二值掩膜分解为若干部件（连通区域），每个部件独立做
EFD 编码，并自动选择"够用"的谐波阶数（在误差阈值内取最小 K）。
分解结果可直接组装回 Pattern（母题库 + 摆放），实现

    掩膜 → 部件 → EFD 系数（PatternSpec） → 重建

的完整往返。这是三层管线中 L2 结构层对真实素材的入口。

阶数自动选择策略:
    对每个部件轮廓，先用高阶 (max_order) 拟合得到参考曲线，再从
    低到高搜索第一个满足 pointwise RMS 误差 < tol 的 K。误差按
    弧长重采样后的逐点距离计算，避免参数相位错位的假误差。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .contour import extract_contours, resample_contour
from .fourier_curve import FourierCurve
from .pattern import CurveLibrary, Pattern, PatternSpec, Placement

__all__ = ["Part", "Decomposition", "decompose_mask", "pattern_from_decomposition"]


@dataclass
class Part:
    """一个部件: 轮廓 + 选定阶数的 EFD 曲线 + 拟合报告。"""

    contour: np.ndarray            # 原始轮廓点列 (N, 2)
    curve: FourierCurve            # 选定阶数的 EFD 曲线
    order: int                     # 自动选择的阶数
    rms_error: float               # 重建 vs 原轮廓的逐点 RMS
    max_error: float               # 逐点最大误差
    area: float                    # 部件面积（像素数）

    @property
    def centroid(self) -> Tuple[float, float]:
        return self.curve.center


@dataclass
class Decomposition:
    """一幅掩膜的完整分解结果。"""

    parts: List[Part] = field(default_factory=list)
    max_order: int = 32
    tol: float = 0.75              # RMS 误差阈值（像素）

    # ------------------------------------------------------------------
    def report(self) -> str:
        """人可读的分解报告（每部件一行）。"""
        lines = [
            f"分解为 {len(self.parts)} 个部件 "
            f"(max_order={self.max_order}, tol={self.tol}px)"
        ]
        for i, p in enumerate(self.parts):
            lines.append(
                f"  part{i}: area={p.area:6d}px  K={p.order:2d}  "
                f"rms={p.rms_error:5.2f}px  max={p.max_error:5.2f}px  "
                f"center=({p.centroid[0]:7.1f},{p.centroid[1]:7.1f})"
            )
        total_coeff = sum(4 * p.order + 2 for p in self.parts)
        total_pts = sum(len(p.contour) for p in self.parts)
        lines.append(
            f"压缩: {total_pts} 轮廓点 → {total_coeff} 个系数 "
            f"({total_coeff / max(total_pts, 1):.1%})"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def to_pattern(
        self,
        colors: Optional[Sequence[str]] = None,
        background: str = "#f2ead8",
        name: str = "decomposed",
    ) -> Pattern:
        """把分解结果组装回 Pattern（每部件一个 single 摆放）。"""
        if not self.parts:
            raise ValueError("没有部件可组装")
        motifs: Dict[str, FourierCurve] = {}
        placements: List[Placement] = []
        for i, part in enumerate(self.parts):
            mname = f"part{i}"
            # 曲线的 center 已含位置信息，normalized 曲线 + offset 更利于
            # 后续编辑复用；这里保持原始曲线（含中心）以忠实重建。
            motifs[mname] = part.curve
            color = colors[i % len(colors)] if colors else "#a63b2a"
            placements.append(Placement(
                motif=mname, x=part.centroid[0], y=part.centroid[1],
                color=color, filled=True,
            ))
        return Pattern(motifs=motifs, placements=placements,
                       background=background, name=name)


def _choose_order(
    contour: np.ndarray,
    max_order: int,
    tol: float,
    n_ref: int = 512,
) -> Tuple[FourierCurve, int, float, float]:
    """对单条轮廓自动选择满足 RMS 阈值的最小阶数。

    Returns:
        (curve, order, rms_error, max_error)
    """
    ref = resample_contour(contour, n_ref)
    # 高阶参考: 用 max_order 拟合作为"可达到的最好水平"
    best = FourierCurve.from_contour(contour, order=max_order)
    best_rec = resample_contour(best.to_contour(n_ref), n_ref)
    floor_rms = float(np.sqrt(np.mean(np.sum((best_rec - ref) ** 2, axis=1))))
    # 若最高阶都达不到 tol（极端尖角），直接用最高阶
    target = min(tol, max(floor_rms, 1e-9))

    prev: Optional[Tuple[FourierCurve, float, float]] = None
    for k in range(3, max_order + 1):
        curve = FourierCurve.from_contour(contour, order=k)
        rec = resample_contour(curve.to_contour(n_ref), n_ref)
        err = rec - ref
        rms = float(np.sqrt(np.mean(np.sum(err ** 2, axis=1))))
        mx = float(np.max(np.linalg.norm(err, axis=1)))
        if rms <= target:
            return curve, k, rms, mx
        prev = (curve, rms, mx)
    # 未达标: 用最高阶结果
    if prev is None:
        return best, max_order, floor_rms, float(np.max(
            np.linalg.norm(best_rec - ref, axis=1)))
    curve, rms, mx = prev
    return curve, max_order, rms, mx


def decompose_mask(
    mask: Sequence[Sequence[bool]],
    max_order: int = 32,
    tol: float = 0.75,
    min_area: int = 24,
) -> Decomposition:
    """掩膜 → 部件分解 + 每部件自动阶数的 EFD 编码。

    Args:
        mask: 二值掩膜（前景 True / >0）。
        max_order: 每部件允许的最大谐波阶数。
        tol: 阶数自动选择的 RMS 误差阈值（像素）；实际阈值取
             min(tol, 最高阶可达水平)，避免极端尖角下死循环。
        min_area: 小于该像素数的连通区域视为噪点丢弃。

    Returns:
        Decomposition（parts + 报告 + to_pattern 组装）。
    """
    if max_order < 3:
        raise ValueError("max_order 至少为 3")
    if tol <= 0:
        raise ValueError("tol 必须为正")
    contours = extract_contours(mask, min_area=min_area)
    dec = Decomposition(max_order=max_order, tol=tol)
    for contour in contours:
        area = int(_contour_area(contour))
        curve, order, rms, mx = _choose_order(contour, max_order, tol)
        dec.parts.append(Part(
            contour=contour, curve=curve, order=order,
            rms_error=rms, max_error=mx, area=area,
        ))
    # 按面积降序，主体在前（组装与报告更稳定）
    dec.parts.sort(key=lambda p: -p.area)
    return dec


def _contour_area(contour: np.ndarray) -> float:
    """鞋带公式计算轮廓面积（近似部件像素数）。"""
    x, y = contour[:, 0], contour[:, 1]
    return 0.5 * abs(
        float(np.dot(x, np.roll(y, -1)) - float(np.dot(np.roll(x, -1), y)))
    )


def pattern_from_decomposition(
    dec: Decomposition,
    colors: Optional[Sequence[str]] = None,
    background: str = "#f2ead8",
    name: str = "decomposed",
) -> PatternSpec:
    """便捷函数: 分解结果 → Pattern → PatternSpec (JSON 可序列化)。"""
    pattern = dec.to_pattern(colors=colors, background=background, name=name)
    return pattern.to_spec()
