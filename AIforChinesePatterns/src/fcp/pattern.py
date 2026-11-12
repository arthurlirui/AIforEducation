"""pattern: 多条傅里叶曲线按 Placement 组合成一幅纹样.

纹样 = 曲线库 (motifs) + 摆放规则 (placements)。一条曲线可以
经平移/旋转/缩放/镜像后摆放到任意位置；团花 (rosette) 摆放会按
旋转对称自动复制 n 份，四方连续 (tile) 摆放会按平移格点复制。

PatternSpec 是纹样的完整结构化描述（JSON 可序列化），即调研报告
中 "Pattern Spec" 中间表示的第一版实现——将来 LLM 层直接生成它。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .fourier_curve import FourierCurve

__all__ = ["Placement", "Pattern", "PatternSpec", "CurveLibrary"]


@dataclass
class Placement:
    """一条曲线实例的摆放参数。"""

    motif: str                    # 曲线库中的键名
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0     # 绕自身中心旋转
    mirror_x: bool = False
    color: str = "#1f2430"        # 渲染颜色
    filled: bool = True
    # 摆放模式: "single" 单个 / "rosette" n 重旋转对称 / "tile" 平移格点
    mode: str = "single"
    n_fold: int = 6               # rosette 的重数
    ring_radius: float = 0.0      # rosette: 各副本所在圆环半径
    tile_dx: float = 100.0        # tile: 水平间距
    tile_dy: float = 0.0          # tile: 垂直间距
    tile_nx: int = 3              # tile: 水平份数
    tile_ny: int = 1              # tile: 垂直份数

    def to_dict(self) -> dict:
        return {
            "motif": self.motif,
            "x": self.x, "y": self.y,
            "scale": self.scale,
            "rotation_deg": self.rotation_deg,
            "mirror_x": self.mirror_x,
            "color": self.color,
            "filled": self.filled,
            "mode": self.mode,
            "n_fold": self.n_fold,
            "ring_radius": self.ring_radius,
            "tile_dx": self.tile_dx, "tile_dy": self.tile_dy,
            "tile_nx": self.tile_nx, "tile_ny": self.tile_ny,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Placement":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Pattern:
    """一幅纹样: 曲线库 + 摆放列表。"""

    motifs: Dict[str, FourierCurve]
    placements: List[Placement] = field(default_factory=list)
    background: str = "#f5efe0"   # 默认宣纸色
    name: str = "pattern"

    # ------------------------------------------------------------------
    def instances(self) -> List[Tuple[FourierCurve, Placement]]:
        """展开所有摆放（含对称/平铺复制），返回 (曲线, 摆放) 列表。"""
        result: List[Tuple[FourierCurve, Placement]] = []
        for pl in self.placements:
            if pl.motif not in self.motifs:
                raise KeyError(f"未知曲线 '{pl.motif}'")
            base = self.motifs[pl.motif]
            if pl.mode == "single":
                result.append((base.transformed(
                    scale=pl.scale, rotation_deg=pl.rotation_deg,
                    mirror_x=pl.mirror_x, offset=(pl.x, pl.y)), pl))
            elif pl.mode == "rosette":
                for i in range(pl.n_fold):
                    ang = 360.0 * i / pl.n_fold
                    # 副本中心分布在圆环上，再自转 ang
                    cx = pl.x + pl.ring_radius * math.cos(math.radians(ang))
                    cy = pl.y + pl.ring_radius * math.sin(math.radians(ang))
                    result.append((base.transformed(
                        scale=pl.scale,
                        rotation_deg=pl.rotation_deg + ang,
                        mirror_x=pl.mirror_x,
                        offset=(cx, cy)), pl))
            elif pl.mode == "tile":
                for iy in range(pl.tile_ny):
                    for ix in range(pl.tile_nx):
                        result.append((base.transformed(
                            scale=pl.scale,
                            rotation_deg=pl.rotation_deg,
                            mirror_x=pl.mirror_x,
                            offset=(pl.x + ix * pl.tile_dx,
                                    pl.y + iy * pl.tile_dy)), pl))
            else:
                raise ValueError(f"未知摆放模式 '{pl.mode}'")
        return result

    # ------------------------------------------------------------------
    def to_spec(self, round_digits: int = 6) -> "PatternSpec":
        """导出为可序列化 PatternSpec。"""
        motifs = {
            name: json.loads(curve.to_json(round_digits))
            for name, curve in self.motifs.items()
        }
        return PatternSpec(
            name=self.name,
            background=self.background,
            motifs=motifs,
            placements=[pl.to_dict() for pl in self.placements],
        )

    @classmethod
    def from_spec(cls, spec: "PatternSpec") -> "Pattern":
        motifs = {
            name: FourierCurve.from_json(json.dumps(payload))
            for name, payload in spec.motifs.items()
        }
        return cls(
            motifs=motifs,
            placements=[Placement.from_dict(d) for d in spec.placements],
            background=spec.background,
            name=spec.name,
        )


@dataclass
class PatternSpec:
    """纹样的完整 JSON 可序列化描述。"""

    name: str
    background: str
    motifs: Dict[str, dict]         # name → FourierCurve 的 JSON dict
    placements: List[dict]          # Placement 的 dict 列表

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "PatternSpec":
        obj = json.loads(text)
        return cls(**obj)


class CurveLibrary:
    """常用曲线库: 参数化生成一些基础母题（圆、花瓣、云纹骨架等）。"""

    @staticmethod
    def circle(radius: float = 1.0, order: int = 4) -> FourierCurve:
        t = np.linspace(0, 2 * np.pi, 128, endpoint=False)
        pts = np.column_stack([radius * np.cos(t), radius * np.sin(t)])
        return FourierCurve.from_contour(pts, order=order)

    @staticmethod
    def petal(
        n_petals: int = 6,
        inner_radius: float = 0.6,
        outer_radius: float = 1.0,
        order: int = 16,
    ) -> FourierCurve:
        """n 瓣花形: r(θ) 在内外半径间按 cos 调制。"""
        t = np.linspace(0, 2 * np.pi, 512, endpoint=False)
        r = inner_radius + (outer_radius - inner_radius) * (
            0.5 + 0.5 * np.cos(n_petals * t)
        )
        pts = np.column_stack([r * np.cos(t), r * np.sin(t)])
        return FourierCurve.from_contour(pts, order=order)

    @staticmethod
    def cloud_scroll(order: int = 20) -> FourierCurve:
        """如意云头骨架: 心形线 (cardioid) 加一次调制的近似。"""
        t = np.linspace(0, 2 * np.pi, 512, endpoint=False)
        r = 1.0 + 0.35 * np.cos(t) - 0.15 * np.cos(2 * t)
        pts = np.column_stack([r * np.cos(t - math.pi / 2),
                               r * np.sin(t - math.pi / 2)])
        return FourierCurve.from_contour(pts, order=order)

    @staticmethod
    def rounded_square(side: float = 1.6, order: int = 12) -> FourierCurve:
        """回字/方胜骨架: 圆角方形。"""
        s = side / 2.0
        r = s * 0.45
        straight = s - r
        segs = []
        # 四条直边 + 四个圆角
        corners = [
            (straight, straight, 0, 90),
            (-straight, straight, 90, 180),
            (-straight, -straight, 180, 270),
            (straight, -straight, 270, 360),
        ]
        for cx, cy, a0, a1 in corners:
            ang = np.radians(np.linspace(a0, a1, 16, endpoint=False))
            segs.append(np.column_stack([cx + r * np.cos(ang),
                                         cy + r * np.sin(ang)]))
        pts = np.vstack(segs)
        return FourierCurve.from_contour(pts, order=order)
