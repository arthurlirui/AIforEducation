"""render: 用 PIL 把 Pattern 渲染成 PNG（抗锯齿 + 传统配色）。"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw

from .pattern import Pattern

__all__ = ["render_pattern"]


def render_pattern(
    pattern: Pattern,
    size: int = 512,
    supersample: int = 4,
    pad: float = 0.1,
    background: Optional[str] = None,
) -> Image.Image:
    """渲染纹样为 PNG。

    Args:
        pattern: 纹样对象。
        size: 输出图像边长（正方形画布）。
        supersample: 超采样倍数（抗锯齿），最终缩回 size。
        pad: 画布四周留白比例。
        background: 背景色，None 时用 pattern.background。

    Returns:
        PIL.Image (RGB)。
    """
    instances = pattern.instances()
    if not instances:
        raise ValueError("纹样没有任何曲线实例")

    all_pts = np.vstack([c.to_contour(128) for c, _ in instances])
    xs, ys = all_pts[:, 0], all_pts[:, 1]
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    span = max(x1 - x0, y1 - y0, 1e-6)
    # 让内容居中并按 span+2*pad 比例缩放到画布。
    # 注意: 绘制发生在 size*supersample 的大画布上，缩放系数必须
    # 乘上 supersample，否则内容只占画布的 1/supersample。
    usable = size * (1.0 - 2.0 * pad) * supersample
    s = usable / span
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)

    big = size * supersample
    img = Image.new("RGB", (big, big), background or pattern.background)
    draw = ImageDraw.Draw(img)

    def to_px(p: np.ndarray):
        # 画布坐标: 像素中心约定，y 向下
        px = (p[:, 0] - cx) * s + big / 2.0
        py = big / 2.0 - (p[:, 1] - cy) * s
        return px, py

    for curve, pl in instances:
        pts = curve.to_contour(192)
        px, py = to_px(pts)
        poly = list(zip(px.tolist(), py.tolist()))
        if pl.filled:
            draw.polygon(poly, fill=pl.color)
        else:
            draw.line(poly + [poly[0]], fill=pl.color, width=2 * supersample)

    return img.resize((size, size), Image.LANCZOS)
