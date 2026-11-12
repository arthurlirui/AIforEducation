"""Demo 4: 真实纹样掩膜的部件分解全链路.

    掩膜 → 连通部件 → 每部件自动阶数 EFD → PatternSpec → 重建渲染

用法:  py demos/demo_decompose.py [输出目录]
输出:
    decomposition.png     三联对比: 原始掩膜 | 部件分解着色 | EFD 重建
    decomposition_spec.json   分解结果的 PatternSpec
    控制台打印误差报告（每部件的阶数/RMS/压缩率）
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fcp import decompose_mask, pattern_from_decomposition, render_pattern  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demos/output")
OUT.mkdir(parents=True, exist_ok=True)

BG = "#f2ead8"
# 部件着色盘（土红/石青/石绿/赭黄/绛紫/黛蓝 循环）
PALETTE = ["#a63b2a", "#2b5f8a", "#4a7c59", "#c99742", "#7b4b6e", "#31506b"]


def make_baoxiang_mask(size=320):
    """宝相花风格复合掩膜（详见 tests/test_decompose.py 同名函数）。"""
    k = size / 256.0
    m = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    r = np.hypot(xx - cx, yy - cy)
    m[r < 30 * k] = True
    for ang in range(0, 360, 45):
        a = math.radians(ang)
        px, py = cx + 58 * k * math.cos(a), cy + 58 * k * math.sin(a)
        dx, dy = xx - px, yy - py
        la = math.radians(-ang)
        ux = dx * math.cos(la) - dy * math.sin(la)
        uy = dx * math.sin(la) + dy * math.cos(la)
        m |= (ux / (22 * k)) ** 2 + (uy / (12 * k)) ** 2 <= 1
    for ang in range(22, 360, 45):
        a = math.radians(ang)
        px, py = cx + 100 * k * math.cos(a), cy + 100 * k * math.sin(a)
        m |= np.hypot(xx - px, yy - py) < 9 * k
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        px, py = cx + 104 * k * math.cos(a), cy + 104 * k * math.sin(a)
        m |= np.hypot(xx - px, yy - py) < 16 * k
    return m


def main():
    size = 320
    mask = make_baoxiang_mask(size)

    # ---- 分解: 每部件自动选阶, RMS 阈值 0.8px ----
    dec = decompose_mask(mask, max_order=24, tol=0.8)
    print(dec.report())

    # ---- 三联对比图: 掩膜 | 分解着色 | EFD 重建 ----
    cell = 360
    title_h = 30  # 顶部标题带
    img = Image.new("RGB", (cell * 3, cell + title_h), BG)
    draw = ImageDraw.Draw(img)
    titles = ["raster mask", f"parts ({len(dec.parts)})", "EFD rebuild"]

    # 左: 原始掩膜（黑底白形 → 改为暖灰形）
    ox = 0
    mask_img = Image.fromarray((~mask * 255).astype(np.uint8))
    mask_img = Image.merge("RGB", (mask_img, mask_img, mask_img))
    tint = Image.new("RGB", (size, size), "#6b6355")
    mask_img = Image.composite(tint, Image.new("RGB", (size, size), BG),
                               Image.fromarray(mask.astype(np.uint8) * 255))
    img.paste(mask_img.resize((cell, cell), Image.LANCZOS), (ox, title_h))

    # 中: 每部件独立着色（多边形填充）
    ox = cell
    for i, part in enumerate(dec.parts):
        pts = part.contour
        poly = [(ox + p[0], p[1] + title_h) for p in pts]
        draw.polygon(poly, fill=PALETTE[i % len(PALETTE)])

    # 右: EFD 重建（用 to_pattern + render 单格渲染）
    pattern = dec.to_pattern(colors=PALETTE, name="baoxiang")
    rebuild = render_pattern(pattern, size=cell, pad=0.05)
    img.paste(rebuild, (cell * 2, title_h))

    for i, t in enumerate(titles):
        draw.text((i * cell + 10, 8), t, fill="#333")
    img.save(OUT / "decomposition.png")
    print(f"[demo4] decomposition.png ({len(dec.parts)} parts)")

    # ---- Spec 导出 ----
    spec = pattern_from_decomposition(dec, colors=PALETTE, name="baoxiang")
    (OUT / "decomposition_spec.json").write_text(spec.to_json(), encoding="utf-8")
    n_coeff = sum(4 * p.order + 2 for p in dec.parts)
    n_pts = sum(len(p.contour) for p in dec.parts)
    print(f"[demo4] decomposition_spec.json "
          f"({n_pts} pts → {n_coeff} coeffs, {len(spec.to_json())} bytes)")


if __name__ == "__main__":
    main()
