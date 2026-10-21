"""exp_figures.py — 生成论文实验章节所需的可视化图 (纯 PIL, 无 matplotlib).

三个实验:
  A. depth_to_radius 理论曲线 (扫 alpha, sigma) → fig_radius_mapping.png
  B. 半径场在真实深度图上的可视化 (pumpkin d_norm → r 场) → fig_radius_field.png
  C. 参数敏感性热力图 (alpha × sigma) → fig_param_heatmap.png + table_param_sensitivity.csv

所有输出写到 paper/figures/.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
PAPER_FIG = ROOT / "paper" / "figures"
PAPER_FIG.mkdir(exist_ok=True)

D_NORM_PATH = ROOT / "outputs" / "depth_demo" / "intermediates" / "depth_normalized.png"

FONT_PATH = "C:/Windows/Fonts/arial.ttf"
FONT_TITLE = ImageFont.truetype(FONT_PATH, 18)
FONT_LABEL = ImageFont.truetype(FONT_PATH, 13)
FONT_TICK = ImageFont.truetype(FONT_PATH, 11)


# ---------------------------------------------------------------------------
# depth_to_radius (复刻自 depth_kusama, 避免 import ultralytics)
# ---------------------------------------------------------------------------

def depth_to_radius(d_norm, r_min=1.0, r_max=25.0, alpha=1.5, sigma=0.15, seed=0):
    rng = np.random.default_rng(seed)
    depth_weight = np.power(1.0 - d_norm, alpha)
    radii = r_min + (r_max - r_min) * depth_weight
    if sigma > 0:
        noise = rng.normal(0.0, sigma, radii.shape)
        radii = radii * (1.0 + noise)
    return np.clip(radii, 0.3, r_max * 1.1).astype(np.float32)


# ---------------------------------------------------------------------------
# 简易绘图工具
# ---------------------------------------------------------------------------

def _colormap(v: float, cmap: str = "viridis") -> tuple[int, int, int]:
    """简易 viridis/inferno/magma 近似, v ∈ [0,1] → RGB."""
    v = float(np.clip(v, 0, 1))
    if cmap == "viridis":
        # 采样几个关键点插值
        stops = [
            (0.00, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.50, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1.00, (253, 231, 37)),
        ]
    elif cmap == "inferno":
        stops = [
            (0.00, (0, 0, 4)),
            (0.25, (87, 15, 109)),
            (0.50, (188, 55, 84)),
            (0.75, (249, 142, 8)),
            (1.00, (252, 255, 164)),
        ]
    elif cmap == "magma":
        stops = [
            (0.00, (0, 0, 4)),
            (0.25, (81, 18, 124)),
            (0.50, (183, 54, 121)),
            (0.75, (252, 137, 97)),
            (1.00, (252, 253, 191)),
        ]
    else:
        raise ValueError(cmap)
    for (v0, c0), (v1, c1) in zip(stops, stops[1:]):
        if v0 <= v <= v1:
            t = (v - v0) / (v1 - v0) if v1 > v0 else 0
            return tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(3))
    return stops[-1][1]


def _field_to_rgb(field: np.ndarray, vmin: float, vmax: float, cmap: str) -> Image.Image:
    norm = np.clip((field - vmin) / (vmax - vmin + 1e-9), 0, 1)
    h, w = norm.shape
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = _colormap(float(norm[y, x]), cmap)
    return img


# ---------------------------------------------------------------------------
# A. 理论映射曲线 (PIL 绘制)
# ---------------------------------------------------------------------------

def fig_radius_mapping() -> None:
    W, H = 1200, 420
    pad_l, pad_r, pad_t, pad_b = 70, 20, 50, 55
    plot_w = (W - pad_l - pad_r) // 2 - 30
    plot_h = H - pad_t - pad_b

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    d_norm = np.linspace(0, 1, 200)
    r_min_v, r_max_v = 0.6, 15.4

    # ---- (a) 不同 alpha ----
    ox, oy = pad_l, pad_t
    d.text((ox + plot_w // 2 - 60, 12), "(a) Effect of α (σ = 0)", font=FONT_TITLE, fill="black")
    # axes
    d.line([(ox, oy + plot_h), (ox + plot_w, oy + plot_h)], fill="black", width=1)
    d.line([(ox, oy), (ox, oy + plot_h)], fill="black", width=1)
    # ticks
    for i in range(5):
        x = ox + plot_w * i / 4
        d.text((x - 8, oy + plot_h + 6), f"{i/4:.2f}".rstrip("0").rstrip("."), font=FONT_TICK, fill="black")
        d.line([(x, oy + plot_h), (x, oy + plot_h + 4)], fill="black")
    for v in [0, 5, 10, 15]:
        y = oy + plot_h - plot_h * (v - 0) / 16
        d.text((ox - 28, y - 6), str(v), font=FONT_TICK, fill="black")
        d.line([(ox - 4, y), (ox, y)], fill="black")
    d.text((ox + plot_w // 2 - 30, oy + plot_h + 30), "depth d̂", font=FONT_LABEL, fill="black")
    d.text((ox - 60, oy - 20), "r (px)", font=FONT_LABEL, fill="black")

    colors = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40)]
    alphas = [0.5, 1.0, 1.5, 2.5]
    for alpha, color in zip(alphas, colors):
        r = depth_to_radius(d_norm, r_min=r_min_v, r_max=r_max_v, alpha=alpha, sigma=0.0)
        pts = []
        for i, x in enumerate(d_norm):
            px = ox + plot_w * x
            py = oy + plot_h - plot_h * (r[i] - 0) / 16
            pts.append((px, py))
        d.line(pts, fill=color, width=2)
        # legend
        d.line([(ox + plot_w - 100, oy + 20 + 18 * alphas.index(alpha)),
                (ox + plot_w - 80, oy + 20 + 18 * alphas.index(alpha))], fill=color, width=2)
        d.text((ox + plot_w - 70, oy + 12 + 18 * alphas.index(alpha)),
               f"α={alpha}", font=FONT_TICK, fill="black")

    # ---- (b) 不同 sigma ----
    ox2 = pad_l + plot_w + 60
    d.text((ox2 + plot_w // 2 - 70, 12), "(b) Effect of σ (α = 1.5)", font=FONT_TITLE, fill="black")
    d.line([(ox2, oy + plot_h), (ox2 + plot_w, oy + plot_h)], fill="black", width=1)
    d.line([(ox2, oy), (ox2, oy + plot_h)], fill="black", width=1)
    for i in range(5):
        x = ox2 + plot_w * i / 4
        d.text((x - 8, oy + plot_h + 6), f"{i/4:.2f}".rstrip("0").rstrip("."), font=FONT_TICK, fill="black")
        d.line([(x, oy + plot_h), (x, oy + plot_h + 4)], fill="black")
    for v in [0, 5, 10, 15]:
        y = oy + plot_h - plot_h * (v - 0) / 16
        d.text((ox2 - 28, y - 6), str(v), font=FONT_TICK, fill="black")
        d.line([(ox2 - 4, y), (ox2, y)], fill="black")
    d.text((ox2 + plot_w // 2 - 30, oy + plot_h + 30), "depth d̂", font=FONT_LABEL, fill="black")

    alpha = 1.5
    base = depth_to_radius(d_norm, r_min=r_min_v, r_max=r_max_v, alpha=alpha, sigma=0.0)
    sigmas = [0.10, 0.15, 0.25]
    fill_colors = [(180, 210, 235), (170, 220, 170), (240, 180, 180)]
    for sigma, fc in zip(sigmas, fill_colors):
        lo = base * (1 - 3 * sigma)
        hi = base * (1 + 3 * sigma)
        poly = []
        for i, x in enumerate(d_norm):
            px = ox2 + plot_w * x
            py = oy + plot_h - plot_h * (hi[i] - 0) / 16
            poly.append((px, py))
        for i in reversed(range(len(d_norm))):
            px = ox2 + plot_w * d_norm[i]
            py = oy + plot_h - plot_h * (lo[i] - 0) / 16
            poly.append((px, py))
        d.polygon(poly, fill=fc)
    pts = []
    for i, x in enumerate(d_norm):
        px = ox2 + plot_w * x
        py = oy + plot_h - plot_h * (base[i] - 0) / 16
        pts.append((px, py))
    d.line(pts, fill="black", width=3)
    # legend
    d.line([(ox2 + plot_w - 100, oy + 18), (ox2 + plot_w - 80, oy + 18)], fill="black", width=3)
    d.text((ox2 + plot_w - 70, oy + 10), "σ=0 (mean)", font=FONT_TICK, fill="black")
    for k, (sigma, fc) in enumerate(zip(sigmas, fill_colors)):
        d.rectangle([ox2 + plot_w - 100, oy + 36 + 18 * k, ox2 + plot_w - 80, oy + 50 + 18 * k], fill=fc)
        d.text((ox2 + plot_w - 70, oy + 38 + 18 * k), f"±3σ, σ={sigma}", font=FONT_TICK, fill="black")

    out = PAPER_FIG / "fig_radius_mapping.png"
    img.save(out)
    print(f"[A] wrote {out}")


# ---------------------------------------------------------------------------
# B. 半径场可视化
# ---------------------------------------------------------------------------

def fig_radius_field() -> None:
    if not D_NORM_PATH.exists():
        print(f"[B] skip, {D_NORM_PATH} not found")
        return
    d_norm_img = cv2.imread(str(D_NORM_PATH), cv2.IMREAD_GRAYSCALE)
    d_norm = d_norm_img.astype(np.float32) / 255.0
    # 缩到 256 让文件小
    d_norm = cv2.resize(d_norm, (256, 256), interpolation=cv2.INTER_AREA)

    panels = []
    panels.append(("(a) depth d̂", _field_to_rgb(d_norm, 0, 1, "inferno")))
    for alpha, label in [(0.5, "(b) α=0.5"), (1.5, "(c) α=1.5"), (2.5, "(d) α=2.5")]:
        r = depth_to_radius(d_norm, r_min=0.6, r_max=15.4, alpha=alpha, sigma=0.0)
        panels.append((label, _field_to_rgb(r, 0.6, 15.4, "viridis")))

    # 拼接: 4 张横排 + 标题
    W = 4 * 256 + 5 * 20
    H = 256 + 60
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for i, (title, panel) in enumerate(panels):
        x = 20 + i * (256 + 20)
        img.paste(panel, (x, 50))
        d.text((x + 60, 18), title, font=FONT_TITLE, fill="black")

    out = PAPER_FIG / "fig_radius_field.png"
    img.save(out)
    print(f"[B] wrote {out}")


# ---------------------------------------------------------------------------
# C. 参数敏感性热力图 + CSV
# ---------------------------------------------------------------------------

def table_param_sensitivity() -> None:
    if not D_NORM_PATH.exists():
        print(f"[C] skip, {D_NORM_PATH} not found")
        return
    d_norm_img = cv2.imread(str(D_NORM_PATH), cv2.IMREAD_GRAYSCALE)
    d_norm = d_norm_img.astype(np.float32) / 255.0
    fg_mask = d_norm < 0.999

    alphas = [0.5, 1.0, 1.5, 2.0, 2.5]
    sigmas = [0.0, 0.10, 0.15, 0.25]
    rows = []
    for a in alphas:
        for s in sigmas:
            r = depth_to_radius(d_norm, r_min=0.6, r_max=15.4, alpha=a, sigma=s, seed=42)
            r_fg = r[fg_mask]
            rows.append({
                "alpha": a, "sigma": s,
                "r_mean": float(r_fg.mean()),
                "r_std": float(r_fg.std()),
                "r_p10": float(np.percentile(r_fg, 10)),
                "r_p90": float(np.percentile(r_fg, 90)),
                "r_min": float(r_fg.min()),
                "r_max": float(r_fg.max()),
            })

    out_csv = PAPER_FIG / "table_param_sensitivity.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[C] wrote {out_csv} ({len(rows)} rows)")

    # 热力图: r_p90 / r_p10
    pivot = np.zeros((len(alphas), len(sigmas)), np.float32)
    for row in rows:
        i = alphas.index(row["alpha"])
        j = sigmas.index(row["sigma"])
        pivot[i, j] = row["r_p90"] / max(row["r_p10"], 1e-3)

    cell = 80
    W = len(sigmas) * cell + 200
    H = len(alphas) * cell + 150
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((W // 2 - 130, 15), "Radius dynamic range r_p90 / r_p10", font=FONT_TITLE, fill="black")
    d.text((W - 140, H // 2 - 40), "σ", font=FONT_TITLE, fill="black")
    d.text((30, 20), "α", font=FONT_TITLE, fill="black")

    vmax = pivot.max()
    for i, a in enumerate(alphas):
        for j, s in enumerate(sigmas):
            v = pivot[i, j] / vmax
            color = _colormap(v, "magma")
            x0 = 100 + j * cell
            y0 = 70 + i * cell
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=color, outline="white")
            text_color = "white" if v < 0.55 else "black"
            d.text((x0 + cell // 2 - 18, y0 + cell // 2 - 8), f"{pivot[i,j]:.1f}",
                   font=FONT_LABEL, fill=text_color)
    for i, a in enumerate(alphas):
        d.text((65, 70 + i * cell + cell // 2 - 8), f"{a:.1f}", font=FONT_LABEL, fill="black")
    for j, s in enumerate(sigmas):
        d.text((100 + j * cell + cell // 2 - 14, 70 + len(alphas) * cell + 8),
               f"{s:.2f}", font=FONT_LABEL, fill="black")

    out = PAPER_FIG / "fig_param_heatmap.png"
    img.save(out)
    print(f"[C] wrote {out}")


if __name__ == "__main__":
    fig_radius_mapping()
    fig_radius_field()
    table_param_sensitivity()
