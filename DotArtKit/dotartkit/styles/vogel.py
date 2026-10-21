"""vogel.py — 黄金角叶序 (Vogel phyllotaxis).

    r_n = c · sqrt(n),   θ_n = n · α,   α = 137.508° (黄金角)

点列沿斐波那契螺线从中心铺开, 用图像亮度调制点半径与颜色.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..ops.color import to_float01, luminance, rgb_to_hsv, hsv_to_rgb, sample_color, draw_disks


def generate_vogel(
    image: Image.Image,
    n_dots: int = 2200,
    scale: float = None,
    golden_angle: float = 137.508,
    center=None,
    radius_power: float = 0.5,
    color_from: str = "image",
    bg=(0.98, 0.97, 0.94),
    seed: int = 0,
) -> Image.Image:
    """Vogel 黄金角叶序生成.

    Parameters
    ----------
    n_dots : 点数
    scale : 螺线尺度系数, 默认 0.55·min(w,h)/sqrt(n_dots)
    golden_angle : 黄金角 (度), 默认 137.508°
    center : 螺线中心, 默认图像中心
    radius_power : 未使用 (保留接口)
    color_from : "image" 从原图采样并提饱和; 其他用单色
    bg : 画布底色
    """
    arr = to_float01(image)
    h, w = arr.shape[:2]
    cx, cy = center if center else (w / 2, h / 2)
    if scale is None:
        scale = 0.55 * min(w, h) / np.sqrt(n_dots)

    n = np.arange(n_dots, dtype=np.float32)
    theta = np.deg2rad(n * golden_angle)
    r = scale * np.sqrt(n)
    P = np.stack([cx + r * np.cos(theta), cy + r * np.sin(theta)], axis=-1)
    mask = (P[:, 0] >= 0) & (P[:, 0] < w) & (P[:, 1] >= 0) & (P[:, 1] < h)
    P, n, r = P[mask], n[mask], r[mask]

    lum = sample_color(luminance(arr)[..., None], P)[:, 0]
    radii = (2.2 + 3.2 * (1.0 - n / n_dots)) * (0.55 + 0.75 * (1.0 - lum))
    radii = np.clip(radii, 0.6, None)

    if color_from == "image":
        colors = sample_color(arr, P)
        hsv = rgb_to_hsv(colors)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.3, 0, 1)
        colors = hsv_to_rgb(hsv)
    else:
        colors = np.tile(np.array([0.10, 0.10, 0.10], np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return draw_disks(canvas, P, radii, colors)
