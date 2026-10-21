"""seurat.py — 点彩派 (Seurat / Chevreul / Rood).

把每个网格 cell 的目标色分解成"主色 + 互补色"两点的面积混合:

- 网格点阵, 每 cell 取均值色 T
- T 分解成 hue h 的主色 P 与对径补色 C (= h+180°)
- Bayer 4×4 有序抖动决定该 cell 画主色点还是补色点
- 点径固定, 让色彩在视网膜混合 (远看是 T)

数学: 加法混色 — 眼睛作为空间低通滤波器 Gσ, 当点径 d << σ 时
卷积近似面积加权平均 ``I_seen ≈ Σ w_k · C_k``.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..ops.color import (
    to_float01,
    luminance,
    rgb_to_hsv,
    hsv_to_rgb,
    draw_disks,
)


def generate_seurat(
    image: Image.Image,
    dot_spacing: int = 6,
    dot_ratio: float = 0.55,
    sat_boost: float = 1.25,
    canvas_color=(1.0, 1.0, 0.98),
    seed: int = 0,
) -> Image.Image:
    """点彩派生成.

    Parameters
    ----------
    dot_spacing : 网格间距 (像素)
    dot_ratio : 点径 / 间距
    sat_boost : 饱和度提升倍数
    canvas_color : 画布底色 (RGB ∈ [0,1])
    """
    rng = np.random.default_rng(seed)
    arr = to_float01(image)
    h, w = arr.shape[:2]

    ys = np.arange(dot_spacing // 2, h, dot_spacing)
    xs = np.arange(dot_spacing // 2, w, dot_spacing)
    cell_mean = np.zeros((len(ys), len(xs), 3), np.float32)
    for iy, y in enumerate(ys):
        y0 = max(0, y - dot_spacing // 2)
        y1 = min(h, y + dot_spacing // 2)
        for ix, x in enumerate(xs):
            x0 = max(0, x - dot_spacing // 2)
            x1 = min(w, x + dot_spacing // 2)
            cell_mean[iy, ix] = arr[y0:y1, x0:x1].reshape(-1, 3).mean(0)

    hsv = rgb_to_hsv(cell_mean)
    hsv[..., 1] = np.clip(hsv[..., 1] * sat_boost, 0, 1)

    primary = hsv.copy()
    primary[..., 1] = np.clip(primary[..., 1] + 0.15, 0, 1)
    compl = hsv.copy()
    compl[..., 0] = (compl[..., 0] + 0.5) % 1.0
    compl[..., 1] = np.clip(compl[..., 1] * 0.85, 0, 1)

    primary_rgb = hsv_to_rgb(primary)
    compl_rgb = hsv_to_rgb(compl)

    lum = luminance(cell_mean)
    bayer = (
        np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32)
        / 16.0
    )
    tile = np.tile(bayer, (len(ys) // 4 + 1, len(xs) // 4 + 1))[: len(ys), : len(xs)]
    use_primary = lum > tile

    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)
    P += rng.uniform(-0.15, 0.15, P.shape) * dot_spacing
    colors = np.where(use_primary[..., None], primary_rgb, compl_rgb).reshape(-1, 3)
    radii = np.full(len(P), dot_ratio * dot_spacing * 0.5, np.float32)

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in canvas_color))
    return draw_disks(canvas, P, radii, colors)
