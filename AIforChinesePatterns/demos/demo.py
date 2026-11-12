"""Demo: 傅里叶曲线表达传统纹样的三个验证场景.

用法:  py demos/demo.py [输出目录]
输出:
    harmonic_convergence.png  同一母题在 K=1..20 阶下的收敛过程
    rosette_pattern.png       多母题团花组合纹样（多位置傅里叶曲线装配）
    raster_roundtrip.png      栅格掩膜 → 轮廓 → EFD → 重建 的往返验证
    demo_spec.json            团花纹样的 PatternSpec（LLM 友好中间表示）
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fcp import (  # noqa: E402
    CurveLibrary,
    FourierCurve,
    Pattern,
    Placement,
    extract_contours,
    render_pattern,
    resample_contour,
)

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demos/output")
OUT.mkdir(parents=True, exist_ok=True)

# 传统配色（敦煌土红/石青/石绿/赭黄 + 宣纸底）
BG = "#f2ead8"
RED = "#a63b2a"
BLUE = "#2b5f8a"
GREEN = "#4a7c59"
GOLD = "#c99742"


def _star(n_points=5, outer=1.0, inner=0.38, num=512):
    t = np.linspace(0, 2 * np.pi, num, endpoint=False)
    r = outer - (outer - inner) * (0.5 + 0.5 * np.cos(n_points * t))
    return np.column_stack([r * np.cos(t - np.pi / 2), r * np.sin(t - np.pi / 2)])


# ----------------------------------------------------------------------
# Demo 1: 谐波收敛 —— 一个五角星母题用 K 阶傅里叶逼近的效果
# ----------------------------------------------------------------------
def demo_harmonic_convergence():
    cell = 220
    cols = 5
    orders = list(range(1, 21))
    rows = math.ceil(len(orders) / cols)
    img = Image.new("RGB", (cell * cols, cell * rows), BG)
    draw = ImageDraw.Draw(img)
    curve = FourierCurve.from_contour(_star(), order=20)
    ref = resample_contour(_star(), 256)

    for idx, k in enumerate(orders):
        cx, cy = (idx % cols) * cell, (idx // cols) * cell
        approx = curve.approximate(k).to_contour(256)
        err = np.linalg.norm(approx - ref, axis=1).max()

        def to_px(p):
            s = cell * 0.36
            return (cx + cell / 2 + p[:, 0] * s, cy + cell / 2 - p[:, 1] * s)

        rx, ry = to_px(ref)
        ax, ay = to_px(approx)
        draw.line(list(zip(rx, ry)) + [(rx[0], ry[0])], fill="#c8bfa8", width=1)
        draw.line(list(zip(ax, ay)) + [(ax[0], ay[0])], fill=RED, width=2)
        draw.text((cx + 8, cy + 6), f"K={k}", fill="#333")
        draw.text((cx + 8, cy + 24), f"err={err:.3f}", fill="#888")
    img.save(OUT / "harmonic_convergence.png")
    print(f"[demo1] harmonic_convergence.png  ({cols}x{rows})")


# ----------------------------------------------------------------------
# Demo 2: 团花组合 —— 多条傅里叶曲线在不同位置装配成纹样
# ----------------------------------------------------------------------
def demo_rosette_pattern():
    motifs = {
        "petal8": CurveLibrary.petal(n_petals=8, inner_radius=0.55, order=14),
        "petal6": CurveLibrary.petal(n_petals=6, inner_radius=0.5, order=12),
        "cloud": CurveLibrary.cloud_scroll(order=16),
        "dot": CurveLibrary.circle(0.3, order=3),
        "ring": CurveLibrary.circle(0.16, order=3),
    }
    placements = [
        # 外圈: 八朵云头向外的团花
        Placement(motif="cloud", mode="rosette", n_fold=8, ring_radius=2.6,
                  scale=0.9, color=BLUE, filled=False),
        # 中圈: 16 个小圆点
        Placement(motif="dot", mode="rosette", n_fold=16, ring_radius=2.2,
                  scale=0.8, color=GOLD),
        # 主体: 八瓣花
        Placement(motif="petal8", scale=1.6, color=RED),
        # 内层: 六瓣花（旋转 22.5° 错位）
        Placement(motif="petal6", scale=0.9, rotation_deg=22.5, color=GREEN),
        # 花心
        Placement(motif="ring", scale=1.2, color=RED),
    ]
    pattern = Pattern(motifs=motifs, placements=placements,
                      background=BG, name="团花·八瓣云纹")
    render_pattern(pattern, size=640).save(OUT / "rosette_pattern.png")
    spec = pattern.to_spec()
    (OUT / "demo_spec.json").write_text(spec.to_json(), encoding="utf-8")
    n_inst = len(pattern.instances())
    size_json = len(spec.to_json())
    print(f"[demo2] rosette_pattern.png  ({n_inst} 条曲线实例, spec {size_json} 字节)")


# ----------------------------------------------------------------------
# Demo 3: 栅格往返 —— 掩膜 → Moore 轮廓 → EFD(12阶) → 重建 → 叠加对比
# ----------------------------------------------------------------------
def demo_raster_roundtrip():
    # 造一个"如意纹风格"的测试掩膜: 大圆 + 环绕的四个凸出小圆 + 中心方孔
    size = 400
    mask = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    r = np.hypot(xx - cx, yy - cy)
    mask[r < 150] = True
    # 小圆必须凸出大圆轮廓（圆心距 + 半径 > 150），外轮廓才呈复合形
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        px, py = cx + 160 * math.cos(a), cy + 160 * math.sin(a)
        rr = np.hypot(xx - px, yy - py)
        mask |= rr < 42
    mask[r < 28] = False  # 中心挖孔（洞不参与外轮廓追踪）

    contours = extract_contours(mask, min_area=50)
    print(f"[demo3] 提取到 {len(contours)} 条轮廓")

    cell = 420
    img = Image.new("RGB", (cell * 2, cell), BG)
    draw = ImageDraw.Draw(img)

    # 左: 原始掩膜; 右: 傅里叶重建叠加
    for col, mode in enumerate(["mask", "fourier"]):
        ox = col * cell
        for pts in contours:
            if mode == "mask":
                poly = [(ox + p[0], p[1]) for p in pts]
                draw.line(poly + [poly[0]], fill="#8a8272", width=1)
            else:
                c = FourierCurve.from_contour(pts, order=12)
                rec = c.to_contour(384)
                poly = [(ox + p[0], p[1]) for p in rec]
                draw.line(poly + [poly[0]], fill=RED, width=2)
                # 中心标记
                ccx, ccy = c.center
                draw.ellipse([ox + ccx - 3, ccy - 3, ox + ccx + 3, ccy + 3],
                             fill=BLUE)
        draw.text((ox + 10, 8), "raster mask" if mode == "mask"
                  else "EFD K=12 (center marked)", fill="#333")
    img.save(OUT / "raster_roundtrip.png")
    print("[demo3] raster_roundtrip.png")


if __name__ == "__main__":
    demo_harmonic_convergence()
    demo_rosette_pattern()
    demo_raster_roundtrip()
    print(f"done → {OUT.resolve()}")
