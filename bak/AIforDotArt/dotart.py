"""dotart.py — 多流派波点/点描艺术生成器.

把 §2 调研报告中的数学模型实现为 6 种生成模式:

  seurat   — 点彩派: 互补色两色分解 + 空间抖动 (Chevreul 同时对比)
  kusama   — 草间弥生: 双峰尺寸分级波点 + 无限网式低频变形场
  benday   — 半调网点 / Lichtenstein: 正交网格, r(x) = λ·sqrt((1-g)/π)
  warp     — 欧普艺术 (Vasarely Vega): 径向变形场 + 等距点阵
  stipple  — 计算点绘 (Secord 2002): 重要性采样 + 最小距离约束, r ∝ ρ^(-1/2)
  vogel    — 叶序黄金角: r_n = c·sqrt(n), θ_n = n·137.508°

所有模式接收 RGB 图像, 输出 PIL Image. 无深度学习依赖.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


class _GridHash:
    """O(1) 近邻最小距离查询 (固定 cell = min_dist). 替代 scipy cKDTree."""

    def __init__(self, cell: float) -> None:
        self.cell = max(cell, 1e-3)
        self.buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return int(x // self.cell), int(y // self.cell)

    def far_enough(self, x: float, y: float, r: float) -> bool:
        cx, cy = self._key(x, y)
        r2 = r * r
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py in self.buckets.get((cx + dx, cy + dy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r2:
                        return False
        return True

    def add(self, x: float, y: float) -> None:
        self.buckets.setdefault(self._key(x, y), []).append((x, y))


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _to_float01(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    return arr / 255.0


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 luminance, ∈ [0,1], shape (H, W)."""
    return (
        0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    ).astype(np.float32)


def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Simple RGB→HSV. rgb ∈ [0,1]^{...,3} -> hsv with h ∈ [0,1)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    idx = nz & (mx == r)
    h[idx] = ((g - b)[idx] / d[idx]) % 6.0
    idx = nz & (mx == g)
    h[idx] = (b - r)[idx] / d[idx] + 2.0
    idx = nz & (mx == b)
    h[idx] = (r - g)[idx] / d[idx] + 4.0
    h = h / 6.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    v = mx
    return np.stack([h, s, v], axis=-1)


def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    h6 = (h * 6.0) % 6.0
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    out = np.zeros_like(hsv)
    for k, (rr, gg, bb) in enumerate(
        [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    ):
        m = i == k
        out[m] = np.stack([rr[m], gg[m], bb[m]], axis=-1)
    return out


def _draw_disks(
    canvas: Image.Image,
    pts: np.ndarray,
    radii: np.ndarray,
    colors: np.ndarray,
) -> Image.Image:
    """Vectorized-ish PIL disk drawing. pts (N,2) xy, radii (N,), colors (N,3) in [0,1]."""
    d = ImageDraw.Draw(canvas)
    cols = (np.clip(colors, 0, 1) * 255.0).astype(np.uint8)
    for (x, y), r, c in zip(pts, radii, cols):
        r = float(max(r, 0.4))
        d.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=(int(c[0]), int(c[1]), int(c[2])),
        )
    return canvas


def _sample_color(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Bilinear sample img at normalized-abs pts (pixel coords)."""
    h, w = img.shape[:2]
    x = np.clip(pts[:, 0], 0, w - 1.001)
    y = np.clip(pts[:, 1], 0, h - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    return (
        img[y0, x0] * (1 - fx) * (1 - fy)
        + img[y0, x1] * fx * (1 - fy)
        + img[y1, x0] * (1 - fx) * fy
        + img[y1, x1] * fx * fy
    )


# ---------------------------------------------------------------------------
# 1) SEURAT — 互补色两色分解 + 空间抖动
# ---------------------------------------------------------------------------

def generate_seurat(
    image: Image.Image,
    dot_spacing: int = 6,
    dot_ratio: float = 0.55,
    sat_boost: float = 1.25,
    canvas_color=(1.0, 1.0, 0.98),
    seed: int = 0,
) -> Image.Image:
    """Chevreul/Rood: 把每个 dot-cell 的目标色分解成"主色 + 互补色"两点的面积混合.

    实现:
      - 网格点阵, 每 cell 取均值色 T
      - 把 T 分解成 hue h 的主色 P 与对径补色 C (= h+180°)
      - 用局部有序抖动决定该 cell 画主色点还是补色点 (模拟面积比)
      - 点径固定 = dot_ratio * spacing, 让色彩在视网膜混合 (远看是 T)
    """
    rng = np.random.default_rng(seed)
    arr = _to_float01(image)
    h, w = arr.shape[:2]

    # cell 均值
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

    hsv = _rgb_to_hsv(cell_mean)
    hsv[..., 1] = np.clip(hsv[..., 1] * sat_boost, 0, 1)

    # 主色 (hue 保留, 高饱和)
    primary = hsv.copy()
    primary[..., 1] = np.clip(primary[..., 1] + 0.15, 0, 1)
    # 补色 (hue + 0.5)
    compl = hsv.copy()
    compl[..., 0] = (compl[..., 0] + 0.5) % 1.0
    compl[..., 1] = np.clip(compl[..., 1] * 0.85, 0, 1)

    primary_rgb = _hsv_to_rgb(primary)
    compl_rgb = _hsv_to_rgb(compl)

    # 亮度决定该 cell 偏向主色 (亮) 还是补色 (暗)
    lum = _luminance(cell_mean)  # (ny, nx)
    # 有序 Bayer 4x4 抖动阈值
    bayer = (
        np.array(
            [
                [0, 8, 2, 10],
                [12, 4, 14, 6],
                [3, 11, 1, 9],
                [15, 7, 13, 5],
            ],
            np.float32,
        )
        / 16.0
    )
    tile = np.tile(bayer, (len(ys) // 4 + 1, len(xs) // 4 + 1))[: len(ys), : len(xs)]
    use_primary = lum > tile  # bool

    # 位置: 网格 + 少量 jitter
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)
    P += rng.uniform(-0.15, 0.15, P.shape) * dot_spacing
    colors = np.where(use_primary[..., None], primary_rgb, compl_rgb).reshape(-1, 3)
    radii = np.full(len(P), dot_ratio * dot_spacing * 0.5, np.float32)

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in canvas_color))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 2) KUSAMA — 双峰尺寸波点 + 低频变形场 (无限网感)
# ---------------------------------------------------------------------------

def generate_kusama(
    image: Image.Image,
    base_spacing: int = 14,
    big_dot_prob: float = 0.06,
    big_dot_scale: float = 2.8,
    warp_amp: float = 3.0,
    warp_freq: float = 0.010,
    palette: str = "kusama_yellow",
    seed: int = 0,
) -> Image.Image:
    """草间弥生:
      - 网格 + 低频正弦变形 (无限网式微错位)
      - 大多数点小, 少量大点 (双峰半径分布) — 视线聚焦
      - 颜色固定图谱 (默认黄底黑点), 与图像内容弱耦合 (消解形体)
    """
    rng = np.random.default_rng(seed)
    arr = _to_float01(image)
    h, w = arr.shape[:2]

    ys = np.arange(base_spacing // 2, h, base_spacing)
    xs = np.arange(base_spacing // 2, w, base_spacing)
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)

    # 变形场 (两层正弦叠加, 伪无限网)
    ph1, ph2, ph3, ph4 = rng.uniform(0, 2 * np.pi, 4)
    P[:, 0] += warp_amp * np.sin(2 * np.pi * warp_freq * P[:, 0] + ph1) + 0.5 * warp_amp * np.sin(
        2 * np.pi * warp_freq * 1.7 * P[:, 1] + ph2
    )
    P[:, 1] += warp_amp * np.sin(2 * np.pi * warp_freq * P[:, 1] + ph3) + 0.5 * warp_amp * np.sin(
        2 * np.pi * warp_freq * 1.7 * P[:, 0] + ph4
    )

    base_r = base_spacing * 0.30
    is_big = rng.uniform(size=len(P)) < big_dot_prob
    radii = np.where(is_big, base_r * big_dot_scale, base_r * rng.uniform(0.85, 1.15, len(P)))

    if palette == "kusama_yellow":
        bg = np.array([0.96, 0.83, 0.05], np.float32)
        fg = np.array([0.05, 0.05, 0.05], np.float32)
        # 大点用反色 (黄底上的黑大点, 也可选黑底黄点)
        colors = np.tile(fg, (len(P), 1))
        canvas_color = tuple(bg.tolist())
    elif palette == "kusama_red":
        canvas_color = (0.85, 0.05, 0.10)
        colors = np.tile(np.array([1.0, 1.0, 1.0], np.float32), (len(P), 1))
    elif palette == "from_image":
        canvas_color = (1, 1, 1)
        colors = _sample_color(arr, P)
    else:
        canvas_color = (1, 1, 1)
        colors = np.tile(np.array([0.0, 0.0, 0.0], np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in canvas_color))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 3) BENDAY — Lichtenstein 半调网点
# ---------------------------------------------------------------------------

def generate_benday(
    image: Image.Image,
    spacing: int = 10,
    angle_deg: float = 15.0,
    use_pop_palette: bool = True,
    bg=(1.0, 1.0, 1.0),
) -> Image.Image:
    """Ben-Day / 半调: 规则网格, 半径 ∝ sqrt(1-g).  Lichtenstein 波普版用固定图谱色."""
    arr = _to_float01(image)
    h, w = arr.shape[:2]

    th = np.deg2rad(angle_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]], np.float32)

    # 扩大采样范围以覆盖旋转后的画布
    diag = int(np.hypot(w, h)) + spacing * 2
    ys = np.arange(-diag, diag, spacing)
    xs = np.arange(-diag, diag, spacing)
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)
    P = (R @ P.T).T
    P += np.array([w / 2, h / 2])

    mask = (P[:, 0] >= 0) & (P[:, 0] < w) & (P[:, 1] >= 0) & (P[:, 1] < h)
    P = P[mask]

    lum = _sample_color(_luminance(arr)[..., None], P)[:, 0]
    # 半调: 覆盖率 a(x) = 1-g, 半径 r = λ·sqrt(a/π); 加一个下限避免纯白区完全消失
    coverage = np.clip(1.0 - lum, 0.0, 1.0)
    radii = spacing * np.sqrt(coverage / np.pi) * 0.85

    if use_pop_palette:
        # Lichtenstein 四色: 由亮度决定黑/彩, 由 hue 决定红/黄/蓝
        src = _sample_color(arr, P)
        hsv_src = _rgb_to_hsv(src)
        hue = hsv_src[:, 0]
        sat = hsv_src[:, 1]
        val = hsv_src[:, 2]
        pop = np.array(
            [
                [0.95, 0.10, 0.10],  # red
                [0.98, 0.85, 0.05],  # yellow
                [0.10, 0.20, 0.85],  # blue
                [0.05, 0.05, 0.05],  # black
            ],
            np.float32,
        )
        centers = np.array([0.0, 1 / 12, 2 / 3], np.float32)
        d = np.abs((hue[:, None] - centers[None, :] + 0.5) % 1.0 - 0.5)
        choice = d.argmin(1)
        colors = pop[choice]
        # 暗 (val < 0.45) → 黑色网点; 低饱和 → 也走黑
        dark = (val < 0.45) | (sat < 0.20)
        colors[dark] = pop[3]
        # 极亮低饱和 → 接近空白的米色点
        light_low_sat = (val > 0.88) & (sat < 0.30)
        colors[light_low_sat] = np.array([0.98, 0.95, 0.88], np.float32)
    else:
        colors = np.tile(np.array([0.05, 0.05, 0.05], np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 4) WARP — Vasarely "Vega" 欧普凸起
# ---------------------------------------------------------------------------

def generate_warp(
    image: Image.Image,
    spacing: int = 12,
    bulge_strength: float = 0.9,
    center=None,
    bg=(0.06, 0.06, 0.08),
    fg=(0.95, 0.90, 0.20),
    seed: int = 0,
) -> Image.Image:
    """Vasarely Vega: 网格上每点向外位移, 位移量随距离中心的径向函数衰减 → 视错觉凸起.
    图像亮度用于调制点的尺寸/明暗, 让形体贴着画布."""
    rng = np.random.default_rng(seed)
    arr = _to_float01(image)
    h, w = arr.shape[:2]
    cx, cy = center if center else (w / 2, h / 2)

    ys = np.arange(spacing // 2, h, spacing)
    xs = np.arange(spacing // 2, w, spacing)
    P = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2).astype(np.float32)

    d = P - np.array([cx, cy])
    r = np.linalg.norm(d, axis=1) + 1e-3
    rn = r / r.max()
    # 凸起位移: 向外, 幅度 ~ 1 - (2r/R - 1)^2  (抛物线凸起)
    amp = bulge_strength * spacing * 1.6 * (1.0 - (2 * rn - 1) ** 2)
    amp = np.clip(amp, 0, None)
    P += (d / r[:, None]) * amp[:, None]

    # 点大小也随凸起程度变化 (近心处大)
    lum = _sample_color(_luminance(arr)[..., None], P)[:, 0]
    bump = amp / (bulge_strength * spacing * 1.6 + 1e-6)
    radii = spacing * (0.22 + 0.85 * bump)
    # 暗部点大、亮部点小, 强化立体感
    radii *= 0.45 + 1.20 * (1.0 - lum)

    colors = np.tile(np.array(fg, np.float32), (len(P), 1))
    # 亮度差异拉大, 增强画面内容感
    colors *= (0.35 + 1.10 * lum)[:, None]

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 5) STIPPLE — Secord 加权重要采样 + 半径 ∝ ρ^(-1/2)
# ---------------------------------------------------------------------------

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
    """计算点绘:
      - 密度场 ρ = 1 - luminance (暗处点密)
      - 拒绝采样: 按 ρ 采样 + 与已有点最小距离约束
      - 半径 r_i = clip(r0 · ρ(x_i)^(-1/2), r_min, r_max)
    """
    rng = np.random.default_rng(seed)
    arr = _to_float01(image)
    h, w = arr.shape[:2]
    lum = _luminance(arr)
    density = (1.0 - lum) if not invert else lum
    density = np.clip(density, 0, 1) ** density_gamma
    density += 0.02  # 避免零区

    # 预计算概率的积分图, 逆变换采样
    flat = density.ravel().astype(np.float64)
    flat /= flat.sum()

    pts: list[list[float]] = []
    grid = _GridHash(min_dist_px)
    tries_per_batch = 20000
    while len(pts) < n_dots:
        idx = rng.choice(flat.size, size=tries_per_batch, p=flat, replace=True)
        ys, xs = np.divmod(idx, w)
        cand = np.stack(
            [xs + rng.uniform(0, 1, len(xs)), ys + rng.uniform(0, 1, len(ys))],
            axis=-1,
        )
        for x, y in cand:
            # 密度高的地方允许更近的间距 → 暗处更密
            rho_here = density[int(y), int(x)]
            local_min = min_dist_px * (0.5 + 1.0 * (1.0 - rho_here))
            if grid.far_enough(x, y, local_min):
                grid.add(x, y)
                pts.append([x, y])
                if len(pts) >= n_dots:
                    break

    P = np.array(pts[:n_dots], np.float32)
    rho_at = _sample_color(density[..., None], P)[:, 0]
    # Secord: 点半径 ∝ ρ^(-1/2), 即密的地方点 *小* (防糊), 疏的地方点 *大* (保持总墨量)
    radii = np.clip(1.0 * (rho_at + 0.05) ** -0.5, r_min, r_max)
    colors = np.tile(np.array(fg, np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 6) VOGEL — 黄金角叶序
# ---------------------------------------------------------------------------

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
    """Vogel phyllotaxis: r_n = c·sqrt(n), θ_n = n·α, α = 137.508°.
    用图像亮度调制点半径与颜色, 让点列沿斐波那契螺线从中心铺开."""
    arr = _to_float01(image)
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

    lum = _sample_color(_luminance(arr)[..., None], P)[:, 0]
    # 中心大、向外变小; 暗部点更大
    radii = (2.2 + 3.2 * (1.0 - n / n_dots)) * (0.55 + 0.75 * (1.0 - lum))
    radii = np.clip(radii, 0.6, None)

    if color_from == "image":
        colors = _sample_color(arr, P)
        # 提饱和
        hsv = _rgb_to_hsv(colors)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.3, 0, 1)
        colors = _hsv_to_rgb(hsv)
    else:
        colors = np.tile(np.array([0.10, 0.10, 0.10], np.float32), (len(P), 1))

    canvas = Image.new("RGB", (w, h), tuple(int(c * 255) for c in bg))
    return _draw_disks(canvas, P, radii, colors)


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

MODES = {
    "seurat": generate_seurat,
    "kusama": generate_kusama,
    "benday": generate_benday,
    "warp": generate_warp,
    "stipple": generate_stipple,
    "vogel": generate_vogel,
}


def generate(mode: str, image: Image.Image, **kwargs) -> Image.Image:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, choose from {list(MODES)}")
    return MODES[mode](image, **kwargs)
