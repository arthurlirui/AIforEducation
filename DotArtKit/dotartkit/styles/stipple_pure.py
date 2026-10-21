"""stipple_pure.py — 纯 numpy Secord 点绘 (无 scipy 依赖).

实现 Secord (2002) 的密度驱动点绘:

- 密度场 ρ = 1 - luminance (暗处点密)
- 拒绝采样: 按 ρ 采样 + :class:`~dotartkit.ops.grid.GridHash` 最小距离约束
- 半径 r_i = clip(r0 · ρ(x_i)^(-1/2), r_min, r_max) — 密处点小防糊, 疏处点大保墨量

**与 :mod:`kusama_basic` 的区别**: kusama_basic 用 scipy Voronoi Lloyd 松弛
逼近蓝噪声; 本流派用 GridHash 密度自适应 min_dist, 纯 numpy, 在 scipy
不可用时仍可运行.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..ops.color import to_float01, luminance, sample_color, draw_disks
from ..ops.grid import GridHash


def generate_stipple(
    image: Image.Image,
    n_dots: int = 4000,
    density_gamma: float = 2.2,
    min_dist_px: float = 3.0,
    r_min: float = 0.9,
    r_max: float = 4.0,
    invert: bool = False,
    bg=(1.0, 1.0, 1.0),
    fg=(0.05, 0.05, 0.05),
    seed: int = 0,
) -> Image.Image:
    """Secord 计算点绘 (纯 numpy).

    Parameters
    ----------
    n_dots : 目标点数
    density_gamma : 密度场 gamma (>1 增对比)
    min_dist_px : 基础最小间距, 实际按密度自适应 (密处更近)
    r_min, r_max : 半径范围
    invert : True 则亮处点密 (反向)
    """
    rng = np.random.default_rng(seed)
    arr = to_float01(image)
    h, w = arr.shape[:2]
    lum = luminance(arr)
    density = (1.0 - lum) if not invert else lum
    density = np.clip(density, 0, 1) ** density_gamma
    density += 0.02

    flat = density.ravel().astype(np.float64)
    flat /= flat.sum()

    pts: list[list[float]] = []
    grid = GridHash(min_dist_px)
    tries_per_batch = 20000
    while len(pts) < n_dots:
        idx = rng.choice(flat.size, size=tries_per_batch, p=flat, replace=True)
        ys, xs = np.divmod(idx, w)
        cand = np.stack(
            [xs + rng.uniform(0, 1, len(xs)), ys + rng.uniform(0, 1, len(ys))],
            axis=-1,
        )
        for x, y in cand:
            rho_here = density[int(y), int(x)]
            local_min = min_dist_px * (0.5 + 1.0 * (1.0 - rho_here))
            if grid.far_enough(x, y, local_min):
                grid.add(x, y)
                pts.append([x, y])
                if len(pts) >= n_dots:
                    break

    P = np.array(pts[:n_dots], np.float32)
    rho_at = sample_color(density[..., None], P)[:, 0]
    radii = np.clip(1.0 * (rho_at + 0.05) ** -0.5, r_min, r_max)
    colors = np.tile(np.array(fg, np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return draw_disks(canvas, P, radii, colors)
