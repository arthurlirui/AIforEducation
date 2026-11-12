"""FourierCurve: 用椭圆傅里叶描述子 (elliptic Fourier descriptor) 表达封闭曲线.

一条封闭曲线 C: [0, 2π) → R² 被展开为三角级数:

    x(t) = A0 + Σ_{k=1..K} [ a_k·cos(kt) + b_k·sin(kt) ]
    y(t) = C0 + D0·T/(2π) + Σ_{k=1..K} [ c_k·cos(kt) + d_k·sin(kt) ]

对封闭曲线而言 D0·T/(2π) 项为 0，曲线完全由 (A0, C0) 平移量与
谐波系数 (a_k, b_k, c_k, d_k)_{k=1..K} 决定。

主要接口:
    FourierCurve.from_contour(points, order)   # 点列 → 系数（正变换）
    curve.to_contour(num_samples)              # 系数 → 点列（逆变换）
    curve.approximate(order)                   # 低阶近似（截断）
    curve.energy / curve.complexity            # 谐波能量 / 复杂度指标
    curve.normalized()                         # 平移/旋转/尺度不变归一化
    curve.transformed(...)                     # 平移/旋转/缩放/镜像
    FourierCurve.from_json / to_json           # 紧凑序列化

数值约定: 内部点列按弧长参数化到 t∈[0,2π)，傅里叶系数用离散积分
(梯形公式) 计算; 逆变换直接对 t 均匀采样求值。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["FourierCurve"]


@dataclass
class FourierCurve:
    """一条由椭圆傅里叶描述子表达的封闭曲线。

    Attributes:
        coeffs: 形状 (K, 4) 的数组，第 k-1 行为 (a_k, b_k, c_k, d_k)。
        center: (A0, C0)，曲线一阶矩中心（平移分量）。
        order: 保留的谐波阶数 K。
    """

    coeffs: np.ndarray
    center: Tuple[float, float]
    order: int

    # ------------------------------------------------------------------
    # 构造与正变换
    # ------------------------------------------------------------------
    def __post_init__(self):
        self.coeffs = np.asarray(self.coeffs, dtype=float).reshape(-1, 4)
        self.center = (float(self.center[0]), float(self.center[1]))
        if self.order != self.coeffs.shape[0]:
            self.order = int(self.coeffs.shape[0])

    @staticmethod
    def _prepare_points(points: Sequence[Sequence[float]]) -> np.ndarray:
        """整理输入点列: Nx2 数组、float、去重首尾、至少 3 点。"""
        pts = np.asarray(points, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError(f"points 应为 (N,2) 数组, 得到 {pts.shape}")
        if len(pts) < 3:
            raise ValueError("封闭曲线至少需要 3 个点")
        if np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) < 3:
            raise ValueError("去重后点数不足 3")
        return pts

    @classmethod
    def from_contour(
        cls,
        points: Sequence[Sequence[float]],
        order: int = 12,
    ) -> "FourierCurve":
        """点列 → 傅里叶系数（正变换）。

        Args:
            points: 有序封闭轮廓点列 (N, 2)。内部按弧长重参数化，
                因此输入点间距不均匀也不影响结果。
            order: 保留的谐波阶数 K。

        Returns:
            FourierCurve 实例。
        """
        pts = cls._prepare_points(points)
        if order < 1:
            raise ValueError("order 至少为 1")

        # ---- 弧长重参数化: 把曲线映射到均匀 t ∈ [0, 2π) ----
        seg = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
        if np.any(seg <= 1e-12):
            raise ValueError("轮廓存在重复相邻点")
        cum = np.concatenate([[0.0], np.cumsum(seg)])  # (N+1,) 周期弧长
        total = cum[-1]
        if total <= 1e-12:
            raise ValueError("轮廓总弧长为零")
        t_pts = 2.0 * math.pi * cum[:-1] / total  # 每个输入点的参数
        n = len(pts)

        center = pts.mean(axis=0)
        xy = pts - center  # 去均值后做谐波分解

        t_uniform = 2.0 * math.pi * np.arange(n) / n
        # 输入点在 t 上不均匀, 先把 x/y 插值到均匀 t 网格再算 DFT 系数,
        # 避免不均匀采样带来的谱泄漏。
        x_u = np.interp(t_uniform, t_pts, xy[:, 0], period=2 * math.pi)
        y_u = np.interp(t_uniform, t_pts, xy[:, 1], period=2 * math.pi)

        k = np.arange(1, order + 1)
        # 梯形积分的离散傅里叶系数 (对周期信号等价于均值×2)
        ang = np.outer(t_uniform, k)  # (n, K)
        cos = np.cos(ang)
        sin = np.sin(ang)
        coeffs = np.empty((order, 4))
        coeffs[:, 0] = (2.0 / n) * cos.T @ x_u  # a_k
        coeffs[:, 1] = (2.0 / n) * sin.T @ x_u  # b_k
        coeffs[:, 2] = (2.0 / n) * cos.T @ y_u  # c_k
        coeffs[:, 3] = (2.0 / n) * sin.T @ y_u  # d_k
        return cls(coeffs=coeffs, center=tuple(center), order=order)

    # ------------------------------------------------------------------
    # 逆变换与采样
    # ------------------------------------------------------------------
    def to_contour(self, num_samples: int = 256) -> np.ndarray:
        """系数 → 点列（逆变换），在 t∈[0,2π) 均匀采样。"""
        if num_samples < 4:
            raise ValueError("num_samples 至少为 4")
        t = 2.0 * math.pi * np.arange(num_samples) / num_samples
        k = np.arange(1, self.order + 1)
        ang = np.outer(t, k)
        cos, sin = np.cos(ang), np.sin(ang)
        x = self.center[0] + cos @ self.coeffs[:, 0] + sin @ self.coeffs[:, 1]
        y = self.center[1] + cos @ self.coeffs[:, 2] + sin @ self.coeffs[:, 3]
        return np.column_stack([x, y])

    # ------------------------------------------------------------------
    # 分析与编辑
    # ------------------------------------------------------------------
    def harmonic_amplitudes(self) -> np.ndarray:
        """每阶谐波的振幅 ‖(a_k, b_k, c_k, d_k)‖，形状 (K,)。"""
        return np.linalg.norm(self.coeffs, axis=1)

    @property
    def energy(self) -> float:
        """总谐波能量（Parseval）：Σ_k (a²+b²+c²+d²)/2。"""
        return float(0.5 * np.sum(self.coeffs**2))

    @property
    def complexity(self) -> float:
        """形状复杂度: 高阶能量占比。

        定义为去掉前 3 阶谐波后的能量与总能量之比。简单凸形（圆、椭圆）
        接近 0，细节丰富的形（云纹、卷草）接近 1。
        """
        amps2 = np.sum(self.coeffs**2, axis=1)
        total = amps2.sum()
        if total <= 1e-18:
            return 0.0
        low = amps2[: min(3, len(amps2))].sum()
        return float(1.0 - low / total)

    def approximate(self, order: int) -> "FourierCurve":
        """返回只保留前 order 阶谐波的近似曲线（截断，不改中心）。"""
        if order < 1 or order > self.order:
            raise ValueError(f"order 需在 [1, {self.order}] 内")
        return FourierCurve(
            coeffs=self.coeffs[:order].copy(),
            center=self.center,
            order=order,
        )

    def normalized(self, max_scale: float = 1.0) -> "FourierCurve":
        """形状归一化: 平移到原点、主轴对齐 x 轴、尺度归一到给定半径。

        常用于形状检索/比较——归一化后只保留"纯形状"信息。
        """
        pts = self.to_contour(max(256, 64 * self.order))
        xy = pts - pts.mean(axis=0)
        # 主轴对齐: PCA
        cov = xy.T @ xy / len(xy)
        w, v = np.linalg.eigh(cov)
        if w[1] <= 1e-12:
            raise ValueError("退化曲线无法归一化")
        rot = v[:, [1, 0]]  # 第一主成分 → x
        if np.linalg.det(rot) < 0:
            rot[:, 1] *= -1
        xy = xy @ rot
        # 尺度: 均匀缩放到平均半径
        r = np.linalg.norm(xy, axis=1).mean()
        if r <= 1e-12:
            raise ValueError("退化曲线无法归一化")
        xy = xy * (max_scale / r)
        return FourierCurve.from_contour(xy, order=self.order)

    def transformed(
        self,
        scale: float = 1.0,
        rotation_deg: float = 0.0,
        mirror_x: bool = False,
        offset: Tuple[float, float] = (0.0, 0.0),
    ) -> "FourierCurve":
        """摆放语义的复合变换，全部在系数域完成：

            new_p(t) = offset + R(θ)·M·( s · (p(t) - center) )

        即形状先绕**自身中心**缩放/镜像/旋转，再把中心平移到 offset
        （绝对坐标）。这与 Pattern.Placement 的 (x, y) 语义一致：
        形状参数与位置参数互不纠缠——调形状不动位置，调位置不动形状。

        镜像 M 取 diag(-1, 1)（x → -x），作用于形状本体，不改变中心。
        """
        if scale <= 0:
            raise ValueError("scale 必须为正")
        c = self.coeffs.copy() * scale
        if mirror_x:
            # x(t) → -x(t): x 的 cos/sin 系数同时变号
            c[:, 0] *= -1
            c[:, 1] *= -1
        if rotation_deg != 0.0:
            th = math.radians(rotation_deg)
            cos_t, sin_t = math.cos(th), math.sin(th)
            # 注意必须 copy(): 直接切片得到的是视图，先写 c[:,0] 会
            # 污染后面要用的 a，导致旋转矩阵混入旧值（视图别名 bug）。
            a = c[:, 0].copy()
            b = c[:, 1].copy()
            cc = c[:, 2].copy()
            d = c[:, 3].copy()
            c[:, 0] = cos_t * a - sin_t * cc
            c[:, 1] = cos_t * b - sin_t * d
            c[:, 2] = sin_t * a + cos_t * cc
            c[:, 3] = sin_t * b + cos_t * d
        return FourierCurve(
            coeffs=c,
            center=(float(offset[0]), float(offset[1])),
            order=self.order,
        )

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_json(self, round_digits: int = 6) -> str:
        """紧凑 JSON 序列化（系数四舍五入以减小体积）。"""
        payload = {
            "order": self.order,
            "center": [round(self.center[0], round_digits), round(self.center[1], round_digits)],
            "coeffs": [[round(v, round_digits) for v in row] for row in self.coeffs],
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "FourierCurve":
        obj = json.loads(text)
        return cls(
            coeffs=np.asarray(obj["coeffs"], dtype=float),
            center=tuple(obj["center"]),
            order=int(obj["order"]),
        )
