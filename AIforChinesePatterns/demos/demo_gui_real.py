"""GUI 真实纹样实操截图: 宝相花卡片 → 边框剥离 → 分解 → 对称归并.

演示新功能: ①预处理面板"边框剥离"（真实卡片素材必开）
         ②"对称归并"（同形部件聚类为共享母题）
输出: demos/output/real_gui_*.png
运行: py demos/demo_gui_real.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demos" / "output"
OUT.mkdir(parents=True, exist_ok=True)

DRIVER = r"""
import sys
from pathlib import Path
sys.path.insert(0, r"{root}/src")

import numpy as np

IMG = r"{root}/images/002_宝相花纹.png"

from fcp.gui.app import PatternApp
app = PatternApp()
app.geometry("1280x820+40+30")
app.update_idletasks(); app.update()

app.load_image(IMG)
app.update()

# ---- 预处理: 反色 + 边框剥离(28px) + 标题栏(12%) ----
app.invert_var.set(True)
app.strip_border_var.set(True)
app.strip_band_var.set(28)
app.on_apply_preprocess()
app.update()
print("preprocess:", app.status_var.get())

# ---- 分解 ----
app.on_decompose()
app.update()
print("decompose:", app.status_var.get())
n_parts = len(app.fill_state.decomposition.parts)

# ---- 视图截图(画布渲染内容) ----
def shot_view(view, name):
    app.view = view
    app.view_var.set(view)
    app._refresh_view()
    app.update()
    app._current_image().save(r"{out}/" + name)

shot_view("original", "real_gui_original.png")
shot_view("mask", "real_gui_mask.png")
shot_view("fill", "real_gui_fill.png")          # 逐部件填色

# ---- 对称归并 ----
app.merge_var.set(True)
app._on_merge_toggle()
app.update()
print("merge:", app.merge_info.cget("text"))
app.view = "fill"; app.view_var.set("fill")
app._refresh_view(); app.update()
shot_view("fill", "real_gui_fill_merged.png")   # 归并母题重建

# ---- 归并 Spec 导出对比 ----
import json
big = app.fill_state.decomposition.to_pattern().to_spec().to_json()
small = app.merged_pattern.to_spec().to_json()
Path(r"{out}/real_gui_spec_merged.json").write_text(small, encoding="utf-8")
print("spec: full %d bytes -> merged %d bytes (%d motifs)" % (
    len(big), len(small), len(app.merged_pattern.motifs)))

# ---- 全窗 UI 截图(PrintWindow) ----
def _grab_window():
    import ctypes
    from PIL import Image
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = app.winfo_id()
    top = user32.GetAncestor(hwnd, 2)
    w = app.winfo_width(); h = app.winfo_height()
    hdc = user32.GetWindowDC(top)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(top, memdc, 2)
    buf = np.empty((h, w, 4), dtype=np.uint8)
    gdi32.GetBitmapBits(bmp, buf.size, buf.ctypes.data_as(ctypes.POINTER(ctypes.c_char)))
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(memdc); user32.ReleaseDC(top, hdc)
    bgr = buf[:, :, :3][::-1]
    rgb = bgr[:, :, ::-1]
    Image.fromarray(np.ascontiguousarray(rgb)).save(r"{out}/real_gui_window.png")
    app.after(200, app.quit)

app.after(700, _grab_window)
app.mainloop()
print("done", n_parts)
"""

driver_path = OUT / "_driver_real.py"
driver_path.write_text(
    DRIVER.format(root=str(ROOT).replace("\\", "/"), out=str(OUT).replace("\\", "/")),
    encoding="utf-8",
)

proc = subprocess.run(
    [sys.executable, "-X", "utf8", str(driver_path)],
    capture_output=True, text=True, timeout=300,
)
print(proc.stdout.strip())
if proc.returncode != 0:
    print("STDERR:", proc.stderr[-1500:])
    sys.exit(1)

for name in ("real_gui_original.png", "real_gui_mask.png",
             "real_gui_fill.png", "real_gui_fill_merged.png",
             "real_gui_window.png"):
    p = OUT / name
    assert p.exists() and p.stat().st_size > 1000, f"缺失: {name}"
    print(f"ok {name} ({p.stat().st_size // 1024}KB)")
driver_path.unlink()
print("真实纹样 GUI 截图完成")
