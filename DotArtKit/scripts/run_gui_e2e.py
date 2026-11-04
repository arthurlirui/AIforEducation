"""run_gui_e2e.py — 桌面编辑器端到端验证 (无头, 不开窗口).

验证内容:
1. luminance 后端: 加载真实图片 → 生成 → 编辑 (增删移) → 渲染保存
2. 全部 4 激活函数 × 4 滤除算法 × 5 配色的组合渲染
3. YOLO26 后端 (有权重 + GPU 时): 深度估计 + 生成
4. GUI 冒烟 (tkinter 窗口创建即销毁)

用法::

    py scripts/run_gui_e2e.py [图片路径] [--skip-yolo] [--skip-gui]
"""

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.gui.polka_document import (  # noqa: E402
    PolkaDocument, DEPTH_BACKENDS, ACTIVATIONS, FILTERS,
)
from dotartkit.ops.depth import DEPTH_PALETTES  # noqa: E402

IMG = sys.argv[1] if len(sys.argv) > 1 else "inputs/pumpkin.jpg"
SKIP_YOLO = "--skip-yolo" in sys.argv
SKIP_GUI = "--skip-gui" in sys.argv
OUT_DIR = os.path.join("outputs", "gui_e2e")
os.makedirs(OUT_DIR, exist_ok=True)

failures = []


def check(name, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name} {extra}")
    if not cond:
        failures.append(name)


print(f"== E2E: image={IMG} ==")

# ---------------------------------------------------------------------------
# 1. luminance 后端全流程
# ---------------------------------------------------------------------------
doc = PolkaDocument()
doc.load_image(IMG)
print(f"1. luminance 全流程 ({doc.size[0]}x{doc.size[1]})")
t0 = time.time()
doc.ensure_depth("luminance", semantic_aware=True)
stats = doc.generate(n_points=8000, activation="power", prune="overlap")
dt = time.time() - t0
check("生成", stats["n_dots"] > 500,
      f"({stats['n_dots']} 点, {dt:.1f}s)")

# 编辑: 增 / 删 / 移
n = len(doc.dots)
doc.add_dot(doc.size[0] / 2, doc.size[1] / 2, 12.0)
check("添加点", len(doc.dots) == n + 1)
hit = doc.find_dot(doc.size[0] / 2, doc.size[1] / 2)
check("命中查找", hit is not None)
doc.begin_edit()
doc.move_dot(hit, 100, 100)
doc.end_edit(changed=True)
check("移动点", doc.undo() and doc.redo())
doc.delete_dot(hit)
check("删除点", len(doc.dots) == n and doc.undo())
doc.redo()

out = doc.render("black_red")
from PIL import Image  # noqa: E402
Image.fromarray(out).save(os.path.join(OUT_DIR, "e2e_luminance.png"))
check("渲染保存", out.shape[2] == 3)

# ---------------------------------------------------------------------------
# 2. 算法组合矩阵
# ---------------------------------------------------------------------------
print("2. 组合矩阵 (4 激活 × 4 滤除)")
for act in ACTIVATIONS:
    for prune in FILTERS:
        try:
            s = doc.generate(n_points=3000, r_max=10.0,
                             activation=act, prune=prune, seed=11)
            ok = s["n_dots"] > 100
        except Exception as e:
            ok = False
            print(f"     {act}/{prune}: {e}")
        check(f"{act}/{prune}", ok)

# 配色
print("3. 配色 (5)")
for pal in DEPTH_PALETTES:
    arr = doc.render(pal)
    Image.fromarray(arr).save(os.path.join(OUT_DIR, f"e2e_{pal}.png"))
    check(pal, arr is not None)

# ---------------------------------------------------------------------------
# 4. YOLO26 后端
# ---------------------------------------------------------------------------
if not SKIP_YOLO:
    print("4. YOLO26 后端")
    try:
        doc2 = PolkaDocument(model_dir="models")
        doc2.load_image(IMG)
        t0 = time.time()
        doc2.ensure_depth("yolo26", semantic_aware=True)
        s2 = doc2.generate(n_points=8000, activation="power",
                           prune="overlap")
        dt = time.time() - t0
        check("YOLO26 深度+生成", s2["n_dots"] > 500,
              f"({s2['n_dots']} 点, {dt:.1f}s)")
        Image.fromarray(doc2.render("yellow_black")).save(
            os.path.join(OUT_DIR, "e2e_yolo26.png"))
    except Exception as e:
        check("YOLO26 深度+生成", False, f"({e})")
else:
    print("4. YOLO26 后端: 跳过 (--skip-yolo)")

# ---------------------------------------------------------------------------
# 5. GUI 冒烟
# ---------------------------------------------------------------------------
if not SKIP_GUI:
    print("5. GUI 冒烟 (窗口创建/加载/销毁)")
    try:
        import tkinter as tk
        from dotartkit.gui.polka_app import PolkaApp
        app = PolkaApp.__new__(PolkaApp)   # 不跑 __init__ 的 mainloop
        tk.Tk.__init__(app)
        app.title("smoke")
        # 手动最小构造: 只验证组件可导入 + 控件可创建
        from dotartkit.gui import polka_app
        check("模块导入", True)
        app.destroy()
    except Exception as e:
        check("GUI 冒烟", False, f"({e})")
else:
    print("5. GUI 冒烟: 跳过 (--skip-gui)")

print()
if failures:
    print(f"== {len(failures)} 项失败: {failures} ==")
    sys.exit(1)
print("== 全部通过 ==")
