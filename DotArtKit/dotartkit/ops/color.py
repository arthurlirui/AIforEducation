"""color.py — 颜色与亮度原语.

所有流派共享的像素级工具:

- :func:`to_float01`   — PIL Image → float32 RGB ∈ [0,1]
- :func:`luminance`    — Rec.709 亮度
- :func:`rgb_to_hsv` / :func:`hsv_to_rgb` — 向量化 HSV 转换 (h ∈ [0,1))
- :func:`sample_color` — 双线性采样
- :func:`draw_disks`   — PIL 向量化圆点绘制

草间弥生调色板 :data:`KUSAMA_PALETTES` 以 BGR (cv2) 元组给出, 与
``kusama_basic`` / ``kusama_depth`` 流派共享.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# 像素工具
# ---------------------------------------------------------------------------

def to_float01(img: Image.Image) -> np.ndarray:
    """PIL Image → float32 RGB 数组 ∈ [0,1], shape (H, W, 3)."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    return arr / 255.0


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 luminance, ∈ [0,1], shape (H, W) 或 (...,) ."""
    return (
        0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    ).astype(np.float32)


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """向量化 RGB→HSV. rgb ∈ [0,1]^{...,3} → hsv, h ∈ [0,1)."""
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


def hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    """向量化 HSV→RGB. 输入 h ∈ [0,1)."""
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


def sample_color(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """双线性采样. img (H,W,*), pts (N,2) xy 像素坐标 → (N, *)."""
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


def draw_disks(
    canvas: Image.Image,
    pts: np.ndarray,
    radii: np.ndarray,
    colors: np.ndarray,
) -> Image.Image:
    """PIL 圆点绘制. pts (N,2) xy, radii (N,), colors (N,3) ∈ [0,1]."""
    d = ImageDraw.Draw(canvas)
    cols = (np.clip(colors, 0, 1) * 255.0).astype(np.uint8)
    for (x, y), r, c in zip(pts, radii, cols):
        r = float(max(r, 0.4))
        d.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=(int(c[0]), int(c[1]), int(c[2])),
        )
    return canvas


# ---------------------------------------------------------------------------
# 草间弥生调色板 — BGR (cv2) 元组 (background, dot)
# ---------------------------------------------------------------------------

KUSAMA_PALETTES = {
    "black_red":      ((0, 0, 0),       (0, 0, 220)),     # 黑底, 红点
    "yellow_black":   ((0, 215, 255),   (0, 0, 0)),       # 铬黄底, 黑点
    "white_red":      ((255, 255, 255), (0, 0, 220)),     # 白底, 猩红点
    "red_white":      ((0, 0, 200),     (255, 255, 255)), # 红底, 白点
    "magenta_black":  ((0, 0, 0),       (220, 0, 220)),   # 黑底, 品红点
    "yellow_red":     ((0, 215, 255),   (0, 0, 220)),     # 黄底, 红点
    # 深度感知版扩展
    "magenta_cyan":   ((220, 220, 0),   (180, 0, 180)),   # 青底, 品红点
    "red_yellow":     ((0, 215, 255),   (0, 0, 220)),     # 黄底, 红点 (别名)
}
"""草间弥生风格高饱和双色板. 键 → (bg BGR, dot BGR)."""
