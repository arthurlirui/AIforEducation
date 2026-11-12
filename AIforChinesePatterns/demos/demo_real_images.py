"""真实纹样图片批量测试: images/*.png → 预处理 → EFD 分解 → 填色重建.

对 images/manifest.json 中的每张纹样图:
  1. GUI 预处理管线（Otsu + 反色/孔洞填充按前景占比自动选择）
  2. 部件分解（自动选阶）
  3. 填色重建渲染
  4. 汇总指标: 部件数 / 自动阶数分布 / 压缩率 / 重建 RMS

输出: demos/output/real_test_<id>.png (左原图/中掩膜/右重建) + 控制台报告。
运行: py demos/demo_real_images.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fcp.gui.imio import imread_                     # noqa: E402
from fcp.gui.pipeline import PreprocessParams, preprocess  # noqa: E402
from fcp.gui.fill import FillState, render_fill      # noqa: E402
from fcp.decompose import decompose_mask             # noqa: E402

OUT = ROOT / "demos" / "output"
OUT.mkdir(parents=True, exist_ok=True)
PALETTE = ["#a63b2a", "#2b5f8a", "#4a7c59", "#c99742", "#7b4b6e", "#31506b"]


def strip_border_band(mask: np.ndarray, band: int = 28) -> np.ndarray:
    """在掩膜上剥离卡片边框带（复验收建议: 分解前处理而非事后丢部件）。

    卡片纹样主体常通过装饰边框与图边连通成单一连通域, 事后按 bbox
    丢部件会把主体一起丢掉。正确做法: 把贴图边的 band 像素环带直接
    从前景中扣除, 切断主体与边框的连接, 主体自然成为独立连通域。
    band=28: 覆盖 Wenyang 卡片边框环内沿(距边 16-23px), 避免主体
    经由存活的边框内圈继续与边框残余连体(复验收实测结论)。
    同时清除顶部标题栏区域（前 12% 高度整条置背景）。
    """
    m = mask.copy()
    h, w = m.shape
    m[:band, :] = False          # 顶带
    m[h - band:, :] = False      # 底带
    m[:, :band] = False          # 左带
    m[:, w - band:] = False      # 右带
    m[: int(h * 0.12), :] = False  # 标题文字栏
    return m


def choose_params(img: np.ndarray) -> PreprocessParams:
    """卡片图是米白底+彩色纹样: 先试普通 Otsu, 前景占比不合理时反选。"""
    p = PreprocessParams(invert=True, thresh_mode="otsu", blur_kind="gauss",
                         blur_ksize=3, morph_close=3)
    m = preprocess(img, p)
    fg = m.mean()
    # 卡片有大面积文字边栏: 前景太多说明把背景当前景了 → 不反色
    if fg > 0.5:
        p.invert = False
        m = preprocess(img, p)
        fg = m.mean()
    return p


def main():
    manifest = json.loads((ROOT / "images" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for item in manifest:
        name = item["name_cn"]
        path = ROOT / "images" / item["file"]
        img = imread_(path)
        if img is None:
            rows.append((item["id"], name, "读取失败", "-", "-", "-"))
            continue

        params = choose_params(img)
        raw_mask = preprocess(img, params)
        # 掩膜阶段剥离边框带/标题栏（切断主体与边框的连通）
        mask = strip_border_band(raw_mask, band=28)
        fg_removed = raw_mask.sum() - mask.sum()
        dec = decompose_mask(mask, max_order=24, tol=1.0, min_area=60)

        # 指标
        orders = sorted({p.order for p in dec.parts})
        n_coeff = sum(4 * p.order + 2 for p in dec.parts)
        n_pts = sum(len(p.contour) for p in dec.parts)
        rms = max(p.rms_error for p in dec.parts) if dec.parts else float("nan")

        # 三联图（渲染按面积升序: 小部件后画不被大部件淹没——验收建议②）
        state = FillState(decomposition=dec, mode="both")
        dec.parts = sorted(dec.parts, key=lambda p: p.area)  # 小→大, 小的后画
        cell = 360
        canvas = Image.new("RGB", (cell * 3, cell), "#f2ead8")
        orig = Image.fromarray(img[:, :, ::-1]).resize((cell, cell), Image.LANCZOS)
        canvas.paste(orig, (0, 0))
        m_img = Image.fromarray(np.where(mask, 100, 235).astype(np.uint8)).convert("RGB")
        canvas.paste(m_img.resize((cell, cell), Image.LANCZOS), (cell, 0))
        if dec.parts:
            rebuild = render_fill(state, size=cell, supersample=2)
            canvas.paste(rebuild, (cell * 2, 0))
        d = ImageDraw.Draw(canvas)
        d.text((10, 8), f"{item['id']} {name} · {len(dec.parts)} parts "
                        f"(border−{fg_removed}px) K={orders}", fill="#333")
        out_path = OUT / f"real_test_{item['id']}.png"
        canvas.save(out_path)

        rows.append((item["id"], name, len(dec.parts),
                     f"K={orders}", f"{n_pts}→{n_coeff} ({n_coeff/max(n_pts,1):.0%})",
                     f"rms≤{rms:.2f}px"))
        print(f"[{item['id']}] {name}: {len(dec.parts)} 部件 "
              f"(剥边框 {fg_removed}px), 阶数 {orders}, "
              f"{n_pts}pt→{n_coeff}coef, max rms {rms:.2f}px → {out_path.name}")

    # 汇总表
    print("\n===== 真实纹样 EFD 分解测试汇总 =====")
    print(f"{'ID':<4}{'纹样':<8}{'部件':>6}  {'自动阶数':<22}{'压缩':<16}{'精度'}")
    for r in rows:
        print(f"{r[0]:<4}{r[1]:<8}{str(r[2]):>6}  {str(r[3]):<22}{str(r[4]):<16}{r[5]}")


if __name__ == "__main__":
    main()
