"""Layered painting renderer.

Converts hand-authored style prescriptions (see data/masterpieces.py) into
raster PNG layers. Pure numpy + PIL — no scipy, no torch, fully offline.

Each masterpiece defines 3-4 layers (sky/hills/cypress...), each with:
  - depth : 3D parallax offset given to the frontend
  - zdraw : painting order (back to front)
  - style : renderer key dispatched below
  - palette / detail : colors and geometric hints

The renderer is deterministic: same prescription -> identical bytes.
"""
from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1024, 768

# 源码不可读时（frozen/zipapp 部署）assets._renderer_code_sig 的兜底版本号；
# 手动 bump 亦可强制轮换缓存签名
FALLBACK_VERSION = "1"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))  # type: ignore[return-value]


def _gradient_vertical(palette: list[str], w: int = W, h: int = H) -> Image.Image:
    stops = [_hex2rgb(c) for c in palette]
    y = np.linspace(0.0, 1.0, h)
    arr = np.zeros((h, w, 3), dtype=np.float32)
    for ch in range(3):
        vals = np.zeros(h)
        for i in range(len(stops) - 1):
            m = (y >= i / (len(stops) - 1)) & (y <= (i + 1) / (len(stops) - 1))
            t = (y[m] - i / (len(stops) - 1)) * (len(stops) - 1)
            vals[m] = [stops[i][ch] * (1 - tt) + stops[i + 1][ch] * tt for tt in t]
        noise = np.random.default_rng(11 + ch).normal(0, 1.2, h)
        arr[:, :, ch] = np.clip(vals[:, None] + noise[:, None], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


# 笔触落笔判定阈值：基图 RGB 最大通道 >= 该值的像素视为"有内容"。
# 必须高于 render_layers_sorted 的 BLACK_ALPHA_THRESHOLD=12：前景层在黑底上
# 取色 arr[y,x]+N(0,18)，若允许在空白处起笔，噪声本身就能把暗色推到 30-54，
# 远超阈值 12，会在本应透明的区域留下不透明暗斑（"黑方块"级回归）。
STROKE_CONTENT_THRESHOLD = 24


def _stroke_texture(img: Image.Image, strength: float = 0.12, seed: int = 3) -> Image.Image:
    """Overlay short directional strokes — 'painted' feel instead of flat fills."""
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32)
    # 唯一的绘制载体：笔触直接画在 img 的副本上，之后从同一副本读回。
    # （历史上这里把笔触画进一个临时 PIL 图、却从原 numpy 数组重新读回，
    #   所有笔触被静默丢弃——该函数曾是彻底的 no-op。）
    overlay_img = img.copy()
    dr = ImageDraw.Draw(overlay_img)
    n = 2600
    xs = rng.integers(0, W - 40, n).tolist()
    ys = rng.integers(0, H - 6, n).tolist()
    lens = rng.integers(8, 42, n).tolist()
    angs = rng.uniform(0, math.pi, n).tolist()
    for x, y, ln, a in zip(xs, ys, lens, angs):
        # 逐笔起点检查（简单方案，避免整幅 alpha 按位与的开销）：只在基图
        # 有内容的像素上起笔。空白处起笔的笔触取色自纯黑+噪声，画出来
        # 只会污染透明区，跳过即可。
        if arr[y, x].max() < STROKE_CONTENT_THRESHOLD:
            continue
        dx, dy = math.cos(a) * ln, math.sin(a) * ln * 0.35
        col = tuple(int(c + rng.normal(0, 18)) for c in arr[y, x])
        dr.line([(x, y), (x + dx, y + dy)], fill=col, width=2)
    overlay = np.asarray(overlay_img).astype(np.float32)
    out = arr * (1 - strength) + overlay * strength
    # 双保险（等价于 stroke 前后 alpha 按位与）：有内容的笔触可能以 width=2
    # 探出轮廓 1-2px，或跨越轮廓内凹处；这些"基图空白"的像素必须还原，
    # 否则混合值 c*strength 仍可能超过 BLACK_ALPHA_THRESHOLD 而变不透明。
    empty = arr.max(axis=-1) < STROKE_CONTENT_THRESHOLD
    out[empty] = arr[empty]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


# --------------------------------------------------------------------------
# Starry Night layer styles
# --------------------------------------------------------------------------
def _night_sky(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = _gradient_vertical(pal, )
    rng = np.random.default_rng(42)
    dr = ImageDraw.Draw(img)

    # Two great swirls: logarithmic-spiral flow ribbons
    for (cx, cy, r0, dirn, bright) in [(W * 0.30, H * 0.30, 46, 1, 3), (W * 0.66, H * 0.24, 34, -1, 2)]:
        theta = np.linspace(0, math.tau * 1.45, 220)
        rr = r0 * np.exp(0.32 * dirn * theta)
        pts = [(float(cx + rr[i] * math.cos(theta[i] + (0.4 if i % 7 < 3 else 0))),
                float(cy + rr[i] * math.sin(theta[i]) * 0.62)) for i in range(len(theta))]
        for i in range(0, len(pts) - 1):
            t = i / len(pts)
            col = _mix(_hex2rgb(pal[1]), _hex2rgb(pal[3]), t * 0.85)
            dr.line([pts[i], pts[i + 1]], fill=col, width=max(2, int(9 * (1 - t)) + 2))

    # Stars: glowing halos + bright cores
    star_pos = [(0.10, 0.14), (0.20, 0.42), (0.42, 0.10), (0.50, 0.36), (0.58, 0.16),
                (0.74, 0.38), (0.80, 0.12), (0.88, 0.30), (0.94, 0.20), (0.34, 0.50), (0.66, 0.52)]
    for (sx, sy) in star_pos[: int(detail.get("stars", 11))]:
        x, y = int(sx * W), int(sy * H)
        halo = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        for rr in range(70, 8, -6):
            a = int(38 * (1 - rr / 70))
            hd.ellipse([80 - rr, 80 - rr * 0.8, 80 + rr, 80 + rr * 0.8], fill=(244, 232, 160, a))
        # 以 halo 自身为 mask 粘贴：无 mask 时整个 160×160 方块（含
        # 透明区转出的纯黑）会盖住天空，留下可见的黑方块
        img.paste(halo, (x - 80, y - 80), halo)
        dr = ImageDraw.Draw(img)
        dr.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(248, 238, 170))
        dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 252, 224))

    # Crescent moon, top-right
    if detail.get("moon", True):
        mx, my, r = int(W * 0.90), int(H * 0.13), 52
        for rr in range(110, r, -5):
            a = max(10, int(60 * (1 - (rr - r) / (110 - r))))
            dr.ellipse([mx - rr, my - rr, mx + rr, my + rr], outline=(246, 224, 130, a))
        dr.ellipse([mx - r, my - r, mx + r, my + r], fill=(250, 226, 128))
        dr.ellipse([mx - r + 26, my - r - 8, mx + r + 26, my + r - 8], fill=_hex2rgb(pal[1]))

    img = _stroke_texture(img, 0.30, seed=5)
    return img


def _rolling_hills(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    amp = detail.get("amplitude", 0.05) * H
    freq = detail.get("frequency", 2.2)
    horizon = H * 0.62
    rng = np.random.default_rng(9)
    for li in range(3):
        col = _hex2rgb(pal[min(li, len(pal) - 1)])
        base = horizon + li * 46
        xs = np.arange(W)
        ys = base + amp * np.sin(xs / W * math.tau * freq + li * 1.4) + rng.normal(0, 3, W).cumsum() * 0.04
        poly = list(zip(xs.tolist(), np.clip(ys, 0, H).tolist())) + [(W, H), (0, H)]
        dr.polygon(poly, fill=col)
        # brush ridge highlight
        edge = list(zip(xs.tolist(), np.clip(ys - 5, 0, H).tolist()))
        dr.line(edge, fill=_mix(col, (255, 255, 255), 0.10), width=4)
    img = img.crop((0, int(horizon) - 90, W, H))
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(img, (0, int(horizon) - 90))
    return _stroke_texture(canvas, 0.22, seed=8)


def _village(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    rng = np.random.default_rng(21)
    base_y = int(H * 0.70)
    n = int(detail.get("houses", 12))
    for i in range(n):
        bw = int(rng.integers(38, 74))
        bh = int(rng.integers(30, 60))
        x = int(i * (W / n) + rng.integers(-8, 10))
        y = base_y + int(rng.integers(-26, 30))
        body = _mix(_hex2rgb(pal[0]), _hex2rgb(pal[1]), rng.uniform(0.2, 0.8))
        dr.rectangle([x, y - bh, x + bw, y], fill=body)
        # roof
        rh = int(rng.integers(12, 24))
        dr.polygon([(x - 4, y - bh), (x + bw + 4, y - bh), (x + bw // 2, y - bh - rh)],
                   fill=_mix(body, (10, 10, 20), 0.35))
        # lit window
        if detail.get("windows", True) and rng.random() < 0.75:
            wx = x + int(rng.integers(6, max(8, bw - 14)))
            dr.rectangle([wx, y - bh + 8, wx + 8, y - 14], fill=_hex2rgb(pal[2]))
    # church spire
    if detail.get("church", True):
        cx = int(W * 0.42)
        dr.rectangle([cx - 9, base_y - 96, cx + 9, base_y - 10], fill=_hex2rgb(pal[1]))
        dr.polygon([(cx - 12, base_y - 96), (cx + 12, base_y - 96), (cx, base_y - 148)],
                   fill=_mix(_hex2rgb(pal[1]), (240, 240, 220), 0.15))
    return _stroke_texture(img, 0.14, seed=13)


def _cypress(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    rng = np.random.default_rng(77)
    flame = bool(detail.get("flame", True))
    for (cx, top, bot, wid) in [(int(W * 0.135), H * 0.08, H * 1.0, 58), (int(W * 0.205), H * 0.30, H * 0.98, 30)]:
        ys = np.linspace(top, bot, 90)
        for i, y in enumerate(ys):
            t = i / len(ys)
            # flame-like sinuous profile
            sway = math.sin(t * 7.5 + cx) * 10 * (1 - t) if flame else 0
            w = wid * (0.30 + 0.95 * math.sin(min(1, t * 1.25) * math.pi * 0.5) * (1 - t * 0.55))
            col = _mix(_hex2rgb(pal[1]), _hex2rgb(pal[2]), rng.uniform(0.1, 0.7))
            dr.ellipse([cx - w + sway, y - 12, cx + w + sway, y + 12], fill=col)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return _stroke_texture(img, 0.25, seed=17)


# --------------------------------------------------------------------------
# Great Wave layer styles
# --------------------------------------------------------------------------
def _wave_sky(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = _gradient_vertical(pal)
    dr = ImageDraw.Draw(img)
    # Fuji: small serene triangle left-of-center behind the wave
    if detail.get("fuji", True):
        fx, fy = int(W * 0.52), int(H * 0.60)
        fw, fh = 190, 96
        dr.polygon([(fx - fw, fy), (fx + fw, fy), (fx, fy - fh)], fill=(198, 196, 190))
        dr.polygon([(fx - fw * 0.42, fy - fh * 0.55), (fx + fw * 0.42, fy - fh * 0.55), (fx, fy - fh)],
                   fill=(240, 238, 232))
    # stylized cloud bands
    for i in range(int(detail.get("clouds", 4))):
        cy = int(H * (0.12 + i * 0.07))
        x0 = (i * 260) % (W - 200)
        dr.ellipse([x0, cy, x0 + 220, cy + 28], fill=_mix(_hex2rgb(pal[1]), (255, 255, 255), 0.4))
    return img


def _great_wave(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    """The wave itself: layered claw arcs built from repeated small hooks."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    deep, mid, light, foam = (_hex2rgb(c) for c in pal[:4])
    sea_level = H * 0.66
    # base sea
    dr.rectangle([0, int(sea_level), W, H], fill=deep)
    for i in range(0, W, 26):
        dr.line([(i, sea_level + 6), (i + 14, sea_level + 6)], fill=mid, width=3)

    # main wave body: big arc from left rising then curling right
    cx, cy = int(W * 0.30), int(H * 0.66)
    pts = []
    for t in np.linspace(0, 1, 260):
        ang = math.pi * (1.05 - 0.95 * t)          # sweep up and over
        r = 300 + 190 * math.sin(t * math.pi)        # bulge
        x = cx + r * math.cos(ang) * 1.35
        y = cy - r * math.sin(ang) * 0.88
        pts.append((x, y))
    dr.polygon(pts + [(cx + 330, cy), (cx - 340, cy)], fill=mid)

    # inner darker trough
    for k, (col, shrink) in enumerate([(deep, 0.86), (mid, 0.94)]):
        pts2 = [(cx + (x - cx) * shrink, cy + (y - cy) * shrink) for x, y in pts]
        dr.line(pts2, fill=col, width=10 - k * 2)

    # claws: repeated hook strokes along the crest
    if detail.get("claws", True):
        rng = np.random.default_rng(101)
        for i, t in enumerate(np.linspace(0.25, 0.97, 46)):
            idx = int(t * (len(pts) - 1))
            x, y = float(pts[idx][0]), float(pts[idx][1])
            # hook curls back toward the trough
            ang = math.pi * (1.05 - 0.95 * t) + math.pi * 0.55
            ln = float(rng.integers(16, 44)) * (1 - t * 0.3)
            ex, ey = x + math.cos(ang) * ln, y + math.sin(ang) * ln * 0.7
            col = foam if i % 4 == 0 else light
            for wline in (7, 3):
                dr.line([(x, y), (ex, ey)], fill=col, width=wline)
            dr.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], fill=foam)

    # foam speckles
    if detail.get("foam", True):
        rng = np.random.default_rng(55)
        for _ in range(240):
            x = int(rng.integers(60, W - 40))
            y = int(rng.integers(int(H * 0.28), int(H * 0.70)))
            r = int(rng.integers(2, 6))
            dr.ellipse([x - r, y - r * 0.6, x + r, y + r * 0.6], fill=foam)
    return _stroke_texture(img, 0.10, seed=23)


def _fishing_boats(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    positions = [(W * 0.56, H * 0.60), (W * 0.68, H * 0.64), (W * 0.40, H * 0.66)]
    for i, (bx, by) in enumerate(positions[: int(detail.get("boats", 3))]):
        bx, by = float(bx), float(by)
        bl, bh = 120 - i * 14, 22
        col = _hex2rgb(pal[0])
        # hull
        dr.polygon([(bx - bl / 2, by), (bx + bl / 2, by), (bx + bl / 2 - 18, by + bh), (bx - bl / 2 + 18, by + bh)],
                   fill=col)
        # deck line + rowers
        dr.line([(bx - bl / 2 + 6, by), (bx + bl / 2 - 6, by)], fill=_hex2rgb(pal[2]), width=3)
        if detail.get("rowers", True):
            for r in range(6):
                rx = bx - bl / 2 + 14 + r * (bl - 28) / 5
                dr.ellipse([rx - 4, by - 12, rx + 4, by - 2], fill=_hex2rgb(pal[1]))
                dr.line([(rx, by - 4), (rx + 6, by + 4)], fill=_hex2rgb(pal[1]), width=2)
    return img


def _hokusai_frame(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    if detail.get("cartouche", True):
        # rectangular title cartouche top-right
        dr.rectangle([W - 250, 34, W - 44, 92], fill=(244, 240, 230), outline=_hex2rgb(pal[1]), width=3)
        for i in range(3):  # pseudo-cartouche text columns
            x = W - 226 + i * 58
            dr.rectangle([x, 44, x + 10, 82], fill=_hex2rgb(pal[1]))
    if detail.get("seal", True):
        dr.rounded_rectangle([40, 40, 92, 100], 6, fill=_hex2rgb(pal[0]))
        dr.rectangle([54, 56, 78, 84], fill=(244, 240, 230))
    return img


# --------------------------------------------------------------------------
# Girl with a Pearl Earring layer styles
# --------------------------------------------------------------------------
def _dark_void(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = _gradient_vertical(pal)
    v = float(detail.get("vignette", 0.5))
    if v > 0:
        # 暗角：mask 在中心亮、边缘暗 → 取反映射后边缘更暗
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([-W * 0.25, -H * 0.25, W * 1.25, H * 1.25], fill=int(255 * (1 - v)))
        mask = mask.filter(ImageFilter.GaussianBlur(120))
        dark = Image.new("RGB", (W, H), (6, 7, 10))
        img = Image.composite(img, dark, mask.point(lambda p: 255 - p)).convert("RGB")
    return _stroke_texture(img, 0.10, seed=31)


def _delft_girl(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    skin, skin_shade, blue, gold = (_hex2rgb(c) for c in pal[:4])
    img = Image.new("RGB", (W, H), (0, 0, 0))
    dr = ImageDraw.Draw(img)

    cx = W * 0.50
    # torso / collar geometry
    if detail.get("collar", True):
        dr.polygon([(cx - 200, H), (cx + 200, H), (cx + 150, H * 0.66), (cx - 150, H * 0.66)], fill=gold)
        dr.ellipse([cx - 160, H * 0.60, cx + 160, H * 0.80], fill=(238, 234, 222))
        dr.polygon([(cx - 150, H * 0.66), (cx + 150, H * 0.66), (cx + 120, H * 0.78), (cx - 120, H * 0.78)],
                   fill=(240, 236, 226))

    # neck
    dr.rectangle([cx - 34, H * 0.48, cx + 34, H * 0.70], fill=_mix(skin, skin_shade, 0.25))

    # face (oval) — soft shading via concentric ellipses
    if detail.get("face", True):
        fx0, fy0, fx1, fy1 = cx - 88, H * 0.16, cx + 88, H * 0.56
        dr.ellipse([fx0, fy0, fx1, fy1], fill=skin)
        # shadow side (left, away from window light)
        for i in range(18):
            t = i / 18
            dr.ellipse([fx0 + 88 * (1 - t) - 88, fy0 + 10 * t, fx0 + 88 * (1 - t), fy1 - 10 * t],
                       fill=_mix(skin, skin_shade, 0.5 * (1 - t)))
        # eyes: two points of light
        ey = H * 0.335
        for ex in (cx - 38, cx + 40):
            dr.ellipse([ex - 9, ey - 6, ex + 9, ey + 6], fill=(46, 42, 40))
            dr.ellipse([ex + 1, ey - 4, ex + 6, ey + 1], fill=(248, 245, 238))
        # nose hint + lips slightly parted
        dr.line([(cx + 6, ey + 8), (cx + 10, ey + 34)], fill=_mix(skin, skin_shade, 0.4), width=4)
        dr.ellipse([cx - 16, ey + 52, cx + 20, ey + 66], fill=(196, 130, 110))
        dr.line([(cx - 14, ey + 59), (cx + 18, ey + 59)], fill=(150, 88, 74), width=2)

    # blue-and-gold turban
    if detail.get("turban", True):
        dr.ellipse([cx - 118, H * 0.05, cx + 118, H * 0.34], fill=blue)
        # fabric folds
        rng = np.random.default_rng(4)
        for i in range(16):
            x0 = cx - 100 + i * 13
            dr.arc([x0 - 30, H * 0.04, x0 + 34, H * 0.36], 180, 360,
                   fill=_mix(blue, (20, 30, 60), rng.uniform(0.2, 0.7)), width=5)
        # hanging tail
        dr.polygon([(cx + 96, H * 0.24), (cx + 128, H * 0.24), (cx + 116, H * 0.56), (cx + 92, H * 0.52)], fill=blue)
        # gold band highlight
        dr.arc([cx - 108, H * 0.06, cx + 108, H * 0.30], 200, 340, fill=gold, width=7)

    img = img.filter(ImageFilter.GaussianBlur(1.2))
    return _stroke_texture(img, 0.16, seed=37)


def _pearl(pal: list[str], detail: dict[str, Any]) -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    if not detail.get("glow", True):
        return img
    dr = ImageDraw.Draw(img)
    px, py = int(W * 0.615), int(H * 0.545)
    soft = _hex2rgb(pal[2])
    # halo（以 halo 自身为 mask 粘贴，正确按 alpha 混合）
    for r, a in [(26, 60), (18, 90), (11, 140)]:
        halo = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse([60 - r, 60 - r, 60 + r, 60 + r],
                                     fill=_hex2rgb(pal[1]) + (a,))
        img.paste(halo, (px - 60, py - 60), halo)
    dr = ImageDraw.Draw(img)
    # the pearl: a light stroke, a dark stroke, a reflected gleam
    dr.ellipse([px - 10, py - 10, px + 10, py + 12], fill=soft)
    dr.ellipse([px - 3, py - 7, px + 5, py - 1], fill=(255, 255, 255))
    dr.arc([px - 9, py - 2, px + 9, py + 11], 20, 150, fill=(210, 205, 190), width=3)
    return img


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
RENDERERS = {
    "night-sky": _night_sky,
    "rolling-hills": _rolling_hills,
    "village": _village,
    "cypress": _cypress,
    "wave-sky": _wave_sky,
    "great-wave": _great_wave,
    "fishing-boats": _fishing_boats,
    "hokusai-frame": _hokusai_frame,
    "dark-void": _dark_void,
    "delft-girl": _delft_girl,
    "pearl": _pearl,
}


def render_layer(style: str, palette: list[str], detail: dict[str, Any]) -> Image.Image:
    fn = RENDERERS.get(style)
    if fn is None:
        raise ValueError(f"unknown layer style: {style}")
    return fn(list(palette), dict(detail))


def render_layers_sorted(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render all layers in zdraw order; returns metadata with PNG bytes.

    Only the three backdrop styles (night-sky / wave-sky / dark-void) are
    opaque. Every other style paints sparse content on a black canvas, so
    near-black pixels (below BLACK_ALPHA_THRESHOLD) become alpha=0 — letting
    backdrops show through when the frontend composites layers as 3D parallax
    planes. The stroke texture only paints on content pixels (see
    STROKE_CONTENT_THRESHOLD in _stroke_texture), so it never lifts empty
    pixels above this threshold.
    """
    OPAQUE_STYLES = {"night-sky", "wave-sky", "dark-void"}
    BLACK_ALPHA_THRESHOLD = 12
    out = []
    for layer in sorted(layers, key=lambda l: l.get("zdraw", 0)):
        img = render_layer(layer["style"], layer["palette"], layer.get("detail", {}))
        rgba = img.convert("RGBA")
        if layer["style"] not in OPAQUE_STYLES:
            arr = np.asarray(rgba).copy()
            mask = arr[..., :3].max(axis=-1) < BLACK_ALPHA_THRESHOLD
            arr[mask, 3] = 0
            rgba = Image.fromarray(arr, "RGBA")
        if layer.get("opacity", 1.0) < 1.0:
            # copy()：不与 PIL 只读图像共享缓冲，就地写 alpha 才安全
            a = np.asarray(rgba).copy()
            a[..., 3] = (a[..., 3].astype(np.float32) * layer["opacity"]).astype(np.uint8)
            rgba = Image.fromarray(a, "RGBA")
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        out.append(
            {
                "role": layer["role"],
                "depth": layer["depth"],
                "zdraw": layer.get("zdraw", 0),
                "semantics": layer.get("semantics", ""),
                "png": buf.getvalue(),
            }
        )
    return out
