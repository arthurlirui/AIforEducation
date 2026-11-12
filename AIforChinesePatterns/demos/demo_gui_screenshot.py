"""GUI 无头实操验证: 驱动 PatternApp 走完论文 Demo 全流程并截图.

流程: 打开线稿 → 反色+孔洞填充预处理 → 傅里叶分解 →
     截四视图（原图/掩膜/线条/填色）→ 全局阶数覆盖 K=3 截图 →
     导出 PNG + Spec → 校验产物。

运行: py demos/demo_gui_screenshot.py
输出: demos/output/gui_*.png + gui_spec.json
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demos" / "output"
OUT.mkdir(parents=True, exist_ok=True)

# 驱动脚本用独立进程跑（tkinter mainloop 在脚本内手动 update）
DRIVER = r"""
import sys, json
from pathlib import Path
sys.path.insert(0, r"{root}/src")
sys.path.insert(0, r"{root}/tests/gui")

import numpy as np, cv2

# ---- 1. 生成测试线稿（白底黑描边宝相花）----
from test_gui_core import _baoxiang_parts
img, _ = _baoxiang_parts(size=288, line=True)
img_path = Path(r"{out}/gui_input_lineart.png")
cv2.imencode(".png", img[:, :, ::-1])[1].tofile(str(img_path))

# ---- 2. 启动 GUI 走全流程 ----
from fcp.gui.app import PatternApp
app = PatternApp()
app.geometry("1280x820+60+40")
app.update_idletasks(); app.update()

app.load_image(str(img_path))
app.update()

# 预处理: 反色 + 孔洞填充（线稿工作流）
app.invert_var.set(True)
app.fill_holes_var.set(True)
app.on_apply_preprocess()
app.update()

# 分解
app.on_decompose()
app.update()
assert app.fill_state is not None, "分解失败"
n_parts = len(app.fill_state.decomposition.parts)
assert n_parts == 21, "部件数错误: " + str(n_parts)

# 截图方案: ImageGrab 依赖窗口可见性与绘制时序（曾抓到同一帧屏幕）。
# 视图内容直接用 app._current_image() 高分辨率保存（所见即所得的画布内容）;
# 完整 UI 另用 after 调度 + 主循环跑一小段时间后抓一次窗口。
def shot_view(view, name):
    app.view = view
    app.view_var.set(view)
    app._refresh_view()
    app.update()
    img = app._current_image()
    img.save(r"{out}/" + name)

# 四视图（画布内容）
for view, name in (("original", "gui_view_original.png"),
                   ("mask", "gui_view_mask.png"),
                   ("lines", "gui_view_lines.png"),
                   ("fill", "gui_view_fill.png")):
    shot_view(view, name)

# 全局阶数覆盖 K=3（谐波收敛演示）
app.fill_state.order_override = 3
shot_view("fill", "gui_view_fill_k3.png")

# 改一个部件颜色（改色后必须显式刷新画布, 否则窗口截图仍是旧帧）
app.fill_state.order_override = 0
app.fill_state.set_part_color(0, "#d35400")
shot_view("fill", "gui_view_fill.png")  # 覆盖为改色后的版本
app.view = "fill"
app.view_var.set("fill")
app._refresh_view()          # 确保画布 widget 也用新颜色重绘
app.update_idletasks()
app.update()

# 完整窗口 UI 截图: ImageGrab 抓屏幕区域会被遮挡窗口污染。
# 用 Windows PrintWindow API 直接抓窗口自身位图（被遮挡也能抓到）。
def _grab_window():
    import ctypes
    import numpy as np
    from PIL import Image
    hwnd = int(app.winfo_id(), 0) if isinstance(app.winfo_id(), str) else app.winfo_id()
    # 顶层窗口句柄: winfo_id 返回的是 client 区, 需要 GetParent 到顶层
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    top = user32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
    w = app.winfo_width(); h = app.winfo_height()
    hdc = user32.GetWindowDC(top)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    # PW_RENDERFULLCONTENT = 2 (Win 8.1+, 让 DirectUI 内容也渲染)
    user32.PrintWindow(top, memdc, 2)
    buf = np.empty((h, w, 4), dtype=np.uint8)
    gdi32.GetBitmapBits(bmp, buf.size, buf.ctypes.data_as(ctypes.POINTER(ctypes.c_char)))
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(memdc); user32.ReleaseDC(top, hdc)
    # GetBitmapBits 输出为 BGR序 + 自底向上行序: 先倒行, 再 BGR→RGB
    bgr = buf[:, :, :3][::-1]
    rgb = bgr[:, :, ::-1]
    Image.fromarray(np.ascontiguousarray(rgb)).save(r"{out}/gui_window_full.png")
    app.after(300, app.quit)

app.after(800, _grab_window)
app.mainloop()

# 导出（绕过 filedialog, 直接调用底层）
from fcp.gui.fill import render_fill
render_fill(app.fill_state, size=1024).save(r"{out}/gui_export_fill.png")
dec = app.fill_state.decomposition
spec = dec.to_pattern(
    colors=[app.fill_state.color_of(i) for i in range(len(dec.parts))],
    name="gui_demo").to_spec()
Path(r"{out}/gui_spec.json").write_text(spec.to_json(), encoding="utf-8")

print(json.dumps(dict(parts=n_parts, status=app.status_var.get())))
app.destroy()
"""

driver_path = OUT / "_driver.py"
driver_path.write_text(
    DRIVER.format(root=str(ROOT).replace("\\", "/"), out=str(OUT).replace("\\", "/")),
    encoding="utf-8",
)

proc = subprocess.run(
    [sys.executable, "-X", "utf8", str(driver_path)],
    capture_output=True, text=True, timeout=180,
)
print(proc.stdout.strip())
if proc.returncode != 0:
    print("STDERR:", proc.stderr[-2000:])
    sys.exit(1)

# 校验产物
for name in ("gui_view_original.png", "gui_view_mask.png",
             "gui_view_lines.png", "gui_view_fill.png",
             "gui_view_fill_k3.png", "gui_export_fill.png",
             "gui_window_full.png"):
    p = OUT / name
    assert p.exists() and p.stat().st_size > 1000, f"缺失: {name}"
    print(f"ok {name} ({p.stat().st_size // 1024}KB)")
import hashlib
md5s = {n: hashlib.md5((OUT / n).read_bytes()).hexdigest()
        for n in ("gui_view_original.png", "gui_view_mask.png",
                  "gui_view_lines.png", "gui_view_fill.png",
                  "gui_view_fill_k3.png")}
assert len(set(md5s.values())) == 5, f"视图截图重复: {md5s}"
print("ok 5 张视图截图互不相同")
spec = json.loads((OUT / "gui_spec.json").read_text(encoding="utf-8"))
assert len(spec["placements"]) == 21
print(f"ok gui_spec.json ({len(spec['placements'])} placements)")
driver_path.unlink()
print("GUI 全流程实操验证通过")
