"""warp.py — Vasarely "Vega" 欧普凸起.

网格点阵每点向外位移, 位移量随距中心径向函数衰减, 产生视错觉凸起:

    amp(x,y) = bulge_strength · spacing · 1.6 · (1 - (2r/R - 1)²)

图像亮度调制点尺寸/明暗, 让形体贴着画布.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..ops.color import to_float01, luminance, sample_color, draw_disks


def generate_warp(
    image: Image.Image,
    spacing: int = 12,
    bulge_strength: float = 0.9,
    center=None,
    bg=(0.06, 0.06, 0.08),
    fg=(0.95, 0.90, 0.20),
    seed: int = 0,
) -> Image.Image:
    """Vasarely Vega 欧普凸起生成.

    Parameters
    ----------
    spacing : 网格间距
    bulge_strength : 凸起强度 (0=平面, 1=强凸)
    center : 凸起中心 (cx, cy), 默认图像中心
    bg : 画布底色 (RGB ∈ [0,1])
    fg : 点颜色 (RGB ∈ [0,1])
    """
    rng = np.random.default_rng(seed)
    arr = to_float01(image)
    h, w = arr.shape[:2]
    cx, cy = center if center else (w / 2, h / 2)

    ys = np.arange(spacing // 2, h, spacing)
    xs = np.arange(spacing // 2, w, spacing)
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)

    d = P - np.array([cx, cy])
    r = np.linalg.norm(d, axis=1) + 1e-3
    rn = r / r.max()
    amp = bulge_strength * spacing * 1.6 * (1.0 - (2 * rn - 1) ** 2)
    amp = np.clip(amp, 0, None)
    P += (d / r[:, None]) * amp[:, None]

    lum = sample_color(luminance(arr)[..., None], P)[:, 0]
    bump = amp / (bulge_strength * spacing * 1.6 + 1e-6)
    radii = spacing * (0.22 + 0.85 * bump)
    radii *= 0.45 + 1.20 * (1.0 - lum)

    colors = np.tile(np.array(fg, np.float32), (len(P), 1))
    colors *= (0.35 + 1.10 * lum)[:, None]

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return draw_disks(canvas, P, radii, colors)
