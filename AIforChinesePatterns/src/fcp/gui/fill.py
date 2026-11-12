"""fill: 分解部件的填色渲染（GUI 可测试核心, 不依赖 tkinter）.

- 每个部件有独立颜色（默认按调色板轮转, GUI 可单独改色）;
- 渲染模式: lines(仅线条) / fill(填充) / both(线条+填充);
- 全局阶数覆盖: 可把所有部件强制为同一阶（论文 demo 展示
  "K 越大细节越丰富"的核心卖点）, 或用分解时的自动阶数;
- 导出: 填色结果 PNG + PatternSpec JSON。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from ..decompose import Decomposition
from ..fourier_curve import FourierCurve

import colorsys

__all__ = ["FillState", "render_fill", "PALETTES", "Palette"]

# 传统配色（复用 demo 配色体系）
PALETTES: Dict[str, Sequence[str]] = {
    "敦煌": ["#a63b2a", "#2b5f8a", "#4a7c59", "#c99742", "#7b4b6e", "#31506b"],
    "青花": ["#1f3a5f", "#3d6b99", "#7fa8c9", "#27496d", "#5b8bb0", "#142d47"],
    "朱砂": ["#a63b2a", "#c0392b", "#8e2a20", "#d35400", "#b03a2e", "#7b241c"],
    "水墨": ["#2b2b2b", "#4a4a4a", "#6b6b6b", "#8a8a8a", "#3d3d3d", "#555555"],
    "七彩": ["#a63b2a", "#2b5f8a", "#4a7c59", "#c99742", "#7b4b6e",
             "#31506b", "#d35400", "#8e6c4a"],
}


@dataclass
class FillState:
    """填色会话状态（GUI 的单一事实来源, 线程快照用 dataclass 复制）。"""

    decomposition: Decomposition
    palette_name: str = "敦煌"
    mode: str = "both"              # lines / fill / both
    order_override: int = 0         # 0 = 用每部件自动阶数; >0 = 全局统一阶
    part_colors: List[str] = field(default_factory=list)  # 单部件改色
    background: str = "#f2ead8"
    line_width: int = 2

    def __post_init__(self):
        if not self.part_colors:
            self.part_colors = list(PALETTES[self.palette_name])

    def color_of(self, index: int) -> str:
        """部件 i 的颜色: 单独改色优先, 否则按调色板轮转。"""
        if index < len(self.part_colors) and self.part_colors[index]:
            return self.part_colors[index]
        pal = PALETTES.get(self.palette_name, PALETTES["敦煌"])
        return pal[index % len(pal)]

    def set_part_color(self, index: int, color: str) -> None:
        while len(self.part_colors) <= index:
            self.part_colors.append("")
        self.part_colors[index] = color

    def effective_curve(self, index: int) -> FourierCurve:
        """部件 i 的生效曲线（应用全局阶数覆盖）。"""
        part = self.decomposition.parts[index]
        if self.order_override and self.order_override != part.order:
            return FourierCurve.from_contour(part.contour, order=self.order_override)
        return part.curve


def render_fill(
    state: FillState,
    size: int = 768,
    supersample: int = 2,
) -> Image.Image:
    """渲染填色结果（复用 fcp 渲染坐标体系: 内容自适应缩放居中）。"""
    parts = state.decomposition.parts
    if not parts:
        raise ValueError("没有部件可渲染")
    curves = [state.effective_curve(i) for i in range(len(parts))]
    all_pts = np.vstack([c.to_contour(128) for c in curves])
    xs, ys = all_pts[:, 0], all_pts[:, 1]
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    span = max(x1 - x0, y1 - y0, 1e-6)

    big = size * supersample
    pad = 0.04
    usable = size * (1.0 - 2.0 * pad) * supersample
    s = usable / span
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)

    img = Image.new("RGB", (big, big), state.background)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)

    for i, (curve, part) in enumerate(zip(curves, parts)):
        pts = curve.to_contour(256)
        px = (pts[:, 0] - cx) * s + big / 2.0
        py = big / 2.0 - (pts[:, 1] - cy) * s
        poly = list(zip(px.tolist(), py.tolist()))
        color = state.color_of(i)
        if state.mode in ("fill", "both"):
            draw.polygon(poly, fill=color)
        if state.mode in ("lines", "both"):
            lw = max(1, state.line_width * supersample)
            if state.mode == "lines":
                draw.line(poly + [poly[0]], fill=color, width=lw)
            else:
                # both: 描边用深一号的同色系
                draw.line(poly + [poly[0]], fill=_darken(color, 0.35),
                          width=max(1, lw // 2))

    return img.resize((size, size), Image.LANCZOS)


def _darken(hex_color: str, factor: float) -> str:
    """颜色加深（both 模式的描边）。"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(hh, max(0, ll * (1 - factor)), ss)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
