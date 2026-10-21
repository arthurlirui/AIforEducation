"""benday.py — Ben-Day 半调网点 / Lichtenstein 波普.

半调数学: 覆盖率 a(x) = 1 - g, 半径 r = λ·sqrt(a/π).

Lichtenstein 波普版用四色固定图谱 (红/黄/蓝/黑):
- 暗 (val < 0.45) 或低饱和 → 黑色网点
- 其余由 hue 量化到最近的 CMY 三色
- 极亮低饱和 → 米色点 (近空白)
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..ops.color import to_float01, luminance, rgb_to_hsv, sample_color, draw_disks


def generate_benday(
    image: Image.Image,
    spacing: int = 10,
    angle_deg: float = 15.0,
    use_pop_palette: bool = True,
    bg=(1.0, 1.0, 1.0),
) -> Image.Image:
    """Ben-Day / 半调生成.

    Parameters
    ----------
    spacing : 网点间距
    angle_deg : 网格旋转角 (度), 半调屏角
    use_pop_palette : True 用 Lichtenstein 四色; False 用单色黑
    bg : 画布底色 (RGB ∈ [0,1])
    """
    arr = to_float01(image)
    h, w = arr.shape[:2]

    th = np.deg2rad(angle_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]], np.float32)

    diag = int(np.hypot(w, h)) + spacing * 2
    ys = np.arange(-diag, diag, spacing)
    xs = np.arange(-diag, diag, spacing)
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)
    P = (R @ P.T).T
    P += np.array([w / 2, h / 2])

    mask = (P[:, 0] >= 0) & (P[:, 0] < w) & (P[:, 1] >= 0) & (P[:, 1] < h)
    P = P[mask]

    lum = sample_color(luminance(arr)[..., None], P)[:, 0]
    coverage = np.clip(1.0 - lum, 0.0, 1.0)
    radii = spacing * np.sqrt(coverage / np.pi) * 0.85

    if use_pop_palette:
        src = sample_color(arr, P)
        hsv_src = rgb_to_hsv(src)
        hue = hsv_src[:, 0]
        sat = hsv_src[:, 1]
        val = hsv_src[:, 2]
        pop = np.array(
            [[0.95, 0.10, 0.10], [0.98, 0.85, 0.05], [0.10, 0.20, 0.85], [0.05, 0.05, 0.05]],
            np.float32,
        )
        centers = np.array([0.0, 1 / 12, 2 / 3], np.float32)
        d = np.abs((hue[:, None] - centers[None, :] + 0.5) % 1.0 - 0.5)
        choice = d.argmin(1)
        colors = pop[choice]
        dark = (val < 0.45) | (sat < 0.20)
        colors[dark] = pop[3]
        light_low_sat = (val > 0.88) & (sat < 0.30)
        colors[light_low_sat] = np.array([0.98, 0.95, 0.88], np.float32)
    else:
        colors = np.tile(np.array([0.05, 0.05, 0.05], np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return draw_disks(canvas, P, radii, colors)
