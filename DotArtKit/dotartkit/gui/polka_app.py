"""polka_app.py — 桌面端波点艺术编辑器 (tkinter).

布局::

    +--------------------------------------------------+
    | 工具栏: 打开 | 生成 | 撤销 | 重做 | 保存 | 工具  |
    +------------+-------------------------------------+
    | 参数面板    |  画布 (缩放平移 + 点编辑)            |
    |  深度后端   |                                     |
    |  激活函数   |                                     |
    |  滤除算法   |                                     |
    |  配色方案   |                                     |
    |  滑块...    |                                     |
    +------------+-------------------------------------+
    | 状态栏: 点数 / 缩放 / 耗时 / 提示                  |
    +--------------------------------------------------+

编辑工具:
- 选择/移动 (V): 点击选中, 拖拽移动, 选中后滚轮或拖柄改半径, Delete 删除
- 添加 (A):    点击空白处按当前笔刷半径加点 (Shift=背景色角色)
- 删除 (E):    点击删除命中点; 按住拖动连续擦除

运行::

    py -m dotartkit.gui        # 或
    py -m dotartkit.gui.polka_app inputs/pumpkin.jpg
"""

from __future__ import annotations

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import cv2
from PIL import Image, ImageTk

from .polka_document import (
    PolkaDocument,
    DEPTH_BACKENDS,
    ACTIVATIONS,
    FEATURES,
    FILTERS,
)
from ..ops.depth import DEPTH_PALETTES

_APP_TITLE = "DotArtKit 波点艺术编辑器"


class CanvasView(tk.Canvas):
    """画布视图: 平移/缩放 + 波点编辑交互.

    坐标约定: 文档坐标 (doc x, y) ↔ 屏幕坐标 = doc * zoom + pan.
    """

    HIT_TOL = 4.0          # 命中容差 (屏幕像素)

    def __init__(self, master, app, **kw):
        super().__init__(master, bg="#202020", highlightthickness=0, **kw)
        self.app = app
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._photo = None
        self._img_item = None
        self._overlay_ids: list[int] = []
        self._press = None          # (sx, sy, button, mode)
        self._last_mouse = None     # 最近鼠标位置 (笔刷预览)
        self._region_press = None   # Ctrl+拖拽选区起点 (doc 坐标)
        self._drag_dot = None       # 拖拽中的点索引
        self._drag_moved = False
        # 事件绑定
        self.bind("<Button-1>", self._on_left)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-3>", self._on_right_pan)      # 右键/中键平移
        self.bind("<B3-Motion>", self._on_right_drag)
        self.bind("<Button-2>", self._on_right_pan)
        self.bind("<B2-Motion>", self._on_right_drag)
        self.bind("<MouseWheel>", self._on_wheel)        # Windows 滚轮
        self.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 0.8))
        self.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.25))

    # ------------------------------------------------------------------
    # 坐标变换
    # ------------------------------------------------------------------

    def to_screen(self, dx: float, dy: float) -> tuple[float, float]:
        return dx * self.zoom + self.pan_x, dy * self.zoom + self.pan_y

    def to_doc(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.pan_x) / self.zoom, (sy - self.pan_y) / self.zoom

    # ------------------------------------------------------------------
    # 显示
    # ------------------------------------------------------------------

    def fit_image(self):
        """缩放平移使图像适配画布."""
        doc = self.app.doc
        W, H = doc.size
        if W == 0:
            return
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw < 50 or ch < 50:
            # 窗口尚未布局完成: 用应用窗口尺寸兜底, 并延迟重试
            cw = max(self.app.winfo_width() - 320, 400)
            ch = max(self.app.winfo_height() - 80, 300)
            self.after(80, self.fit_image)
        self.zoom = min(cw / W, ch / H) * 0.95
        self.pan_x = (cw - W * self.zoom) / 2
        self.pan_y = (ch - H * self.zoom) / 2
        self.refresh()

    def refresh(self):
        """重绘底图 (文档渲染结果) + 编辑覆盖层."""
        doc = self.app.doc
        self.delete("all")
        self._overlay_ids.clear()
        if doc.image is None:
            return
        # 底图 (缓存: app.render_cache)
        arr = self.app.get_render()
        rgb = arr if arr is not None else np.zeros((10, 10, 3), np.uint8)
        h, w = rgb.shape[:2]
        pil = Image.fromarray(rgb)
        pil = pil.resize((max(1, int(w * self.zoom)),
                          max(1, int(h * self.zoom))), Image.NEAREST)
        self._photo = ImageTk.PhotoImage(pil)
        self._img_item = self.create_image(
            self.pan_x, self.pan_y, anchor="nw", image=self._photo)
        self._draw_overlay()

    def _draw_overlay(self):
        """选中框 / 笔刷预览 / 删除高亮."""
        app = self.app
        if app.selected_dot is not None and app.selected_dot < len(app.doc.dots):
            d = app.doc.dots[app.selected_dot]
            sx, sy = self.to_screen(d.x, d.y)
            sr = max(d.r * self.zoom, 2.0)
            self._overlay_ids.append(self.create_oval(
                sx - sr, sy - sr, sx + sr, sy + sr,
                outline="#00ff88", width=2))
            # 半径拖柄 (右侧)
            hx, hy = self.to_screen(d.x + d.r, d.y)
            self._overlay_ids.append(self.create_oval(
                hx - 5, hy - 5, hx + 5, hy + 5,
                fill="#00ff88", outline=""))
        if app.tool.get() == "add" and app._last_mouse is not None:
            mx, my = app._last_mouse
            sr = app.brush_radius.get() * self.zoom
            self._overlay_ids.append(self.create_oval(
                mx - sr, my - sr, mx + sr, my + sr,
                outline="#ffcc00", dash=(4, 3)))
        # 圆形选区 (局部重映射) 高亮
        if getattr(app, "_region", None):
            rx, ry, rr = app._region
            sx, sy = self.to_screen(rx, ry)
            sr = rr * self.zoom
            self._overlay_ids.append(self.create_oval(
                sx - sr, sy - sr, sx + sr, sy + sr,
                outline="#ff6644", width=2, dash=(6, 4)))

    # ------------------------------------------------------------------
    # 缩放 / 平移
    # ------------------------------------------------------------------

    def _zoom_at(self, sx, sy, factor):
        self.zoom = float(np.clip(self.zoom * factor, 0.05, 20.0))
        # 以 (sx, sy) 为不动点
        dx, dy = self.to_doc(sx, sy)
        self.pan_x = sx - dx * self.zoom
        self.pan_y = sy - dy * self.zoom
        self.refresh()
        self.app.update_status()

    def _on_wheel(self, event):
        # Windows: event.delta = ±120
        if self.app.selected_dot is not None and self.app.tool.get() == "select":
            # 选中状态下滚轮直接改半径（越界防护：擦除/撤销可能已缩短点列表）
            if self.app.selected_dot >= len(self.app.doc.dots):
                self.app.selected_dot = None
                return
            d = self.app.doc.dots[self.app.selected_dot]
            d.r = max(0.3, d.r + 0.25 * (1 if event.delta > 0 else -1))
            self.app.invalidate_render()
            self.refresh()
            return
        self._zoom_at(event.x, event.y, 1.1 if event.delta > 0 else 1 / 1.1)

    def _on_right_pan(self, event):
        self._press = ("pan", event.x, event.y)

    def _on_right_drag(self, event):
        if self._press and self._press[0] == "pan":
            _, px, py = self._press
            self.pan_x += event.x - px
            self.pan_y += event.y - py
            self._press = ("pan", event.x, event.y)
            self.refresh()

    # ------------------------------------------------------------------
    # 编辑交互
    # ------------------------------------------------------------------

    def _on_left(self, event):
        self.app._last_mouse = (event.x, event.y)
        self.focus_set()
        doc = self.app.doc
        if doc.image is None:
            return
        dx, dy = self.to_doc(event.x, event.y)
        if event.state & 0x0004:  # Ctrl+左键: 圆形选区 (用于局部重映射)
            self._region_press = (dx, dy)
            self.app._region = None
            self._press = ("region", event.x, event.y)
            return
        tool = self.app.tool.get()
        if tool == "select":
            hit = doc.find_dot(dx, dy, tol_extra=self.HIT_TOL / self.zoom)
            self.app.selected_dot = hit
            if hit is not None:
                self._drag_dot = hit
                self._drag_moved = False
                self.app.doc.begin_edit()
            self.refresh()
        elif tool == "add":
            role = "bg" if (event.state & 0x0001) else "fg"  # Shift
            doc.add_dot(dx, dy, self.app.brush_radius.get(), role)
            self.app.invalidate_render()
            self.app.after_edit()
        elif tool == "erase":
            hit = doc.find_dot(dx, dy, tol_extra=self.HIT_TOL / self.zoom)
            if hit is not None:
                doc.delete_dot(hit)
                self.app.selected_dot = None
                self.app.invalidate_render()
                self.app.after_edit()
            self._press = ("erase", event.x, event.y)

    def _on_drag(self, event):
        self.app._last_mouse = (event.x, event.y)
        doc = self.app.doc
        if doc.image is None:
            return
        if self._press and self._press[0] == "region":
            # Ctrl 拖拽: 实时更新圆形选区
            dx0, dy0 = self._region_press
            dx, dy = self.to_doc(event.x, event.y)
            self.app._region = (dx0, dy0, float(np.hypot(dx - dx0, dy - dy0)))
            self._press = ("region", event.x, event.y)
            self.refresh()
            return
        if self._press and self._press[0] == "erase":
            _, px, py = self._press
            if abs(event.x - px) + abs(event.y - py) > 6:
                dx, dy = self.to_doc(event.x, event.y)
                n = doc.delete_dots_in_circle(dx, dy, 6.0 / self.zoom)
                if n:
                    self.app.invalidate_render()
                    self.app.after_edit()
                self._press = ("erase", event.x, event.y)
            return
        if self._drag_dot is not None and self._drag_dot < len(doc.dots):
            dx, dy = self.to_doc(event.x, event.y)
            doc.move_dot(self._drag_dot, dx, dy)
            self._drag_moved = True
            self.app.invalidate_render()
            self.refresh()

    def _on_release(self, event):
        doc = self.app.doc
        if self._drag_dot is not None:
            doc.end_edit(changed=self._drag_moved)
            if self._drag_moved:
                self.app.after_edit()
        self._drag_dot = None
        self._drag_moved = False
        self._press = None

    def on_delete_key(self, event):
        app = self.app
        if app.selected_dot is not None and app.selected_dot < len(app.doc.dots):
            app.doc.delete_dot(app.selected_dot)
            app.selected_dot = None
            app.invalidate_render()
            app.after_edit()


class PolkaApp(tk.Tk):
    """主应用窗口."""

    def __init__(self, initial_image: str | None = None,
                 model_dir: str = "models"):
        super().__init__()
        self.title(_APP_TITLE)
        self.geometry("1280x820")
        self.doc = PolkaDocument(model_dir=model_dir)
        self._render_cache: np.ndarray | None = None
        self._render_dirty = True
        self.selected_dot: int | None = None
        self._last_mouse = None
        self._region: tuple | None = None    # 圆形选区 (doc 坐标)
        self._gen_thread = None
        self._gen_result = None
        self._build_ui()
        self.bind("<Control-z>", lambda e: self.do_undo())
        self.bind("<Control-y>", lambda e: self.do_redo())
        self.bind("<Delete>", lambda e: None)  # 画布 focus 时由 CanvasView 处理
        if initial_image and os.path.exists(initial_image):
            self.load_image_file(initial_image)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        # --- 顶部工具栏 ---
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=4, pady=3)
        ttk.Button(bar, text="打开图片", command=self.open_image).pack(side="left", padx=2)
        ttk.Button(bar, text="重新生成", command=self.start_generate).pack(side="left", padx=2)
        ttk.Button(bar, text="撤销", command=self.do_undo).pack(side="left", padx=2)
        ttk.Button(bar, text="重做", command=self.do_redo).pack(side="left", padx=2)
        ttk.Button(bar, text="保存PNG", command=self.save_image).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="工具:").pack(side="left")
        self.tool = tk.StringVar(value="select")
        for key, label in (("select", "选择/移动(V)"),
                           ("add", "添加(A)"),
                           ("erase", "擦除(E)")):
            ttk.Radiobutton(bar, text=label, value=key,
                            variable=self.tool,
                            command=self._on_tool_change).pack(side="left", padx=2)
        ttk.Label(bar, text="笔刷半径:").pack(side="left", padx=(12, 2))
        self.brush_radius = tk.DoubleVar(value=6.0)
        ttk.Spinbox(bar, from_=0.5, to=60, increment=0.5, width=5,
                    textvariable=self.brush_radius).pack(side="left")

        # --- 主区域: 左参数面板 + 右画布 ---
        main = ttk.Frame(self)
        main.pack(side="top", fill="both", expand=True)
        panel = ttk.Frame(main, width=290)
        panel.pack(side="left", fill="y", padx=(6, 2), pady=2)
        panel.pack_propagate(False)
        self.canvas = CanvasView(main, self)
        self.canvas.pack(side="left", fill="both", expand=True)

        self._build_panel(panel)

        # --- 底部状态栏 ---
        self.status_var = tk.StringVar(value="打开一张图片开始")
        status = ttk.Label(self, textvariable=self.status_var,
                           relief="sunken", anchor="w")
        status.pack(side="bottom", fill="x")
        # 键盘: V/A/E 工具切换 (画布 focus)
        self.canvas.bind("<v>", lambda e: (self.tool.set("select"), self._on_tool_change()))
        self.canvas.bind("<a>", lambda e: (self.tool.set("add"), self._on_tool_change()))
        self.canvas.bind("<e>", lambda e: (self.tool.set("erase"), self._on_tool_change()))
        self.canvas.bind("<Delete>", self.canvas.on_delete_key)

    def _build_panel(self, panel):
        pad = {"padx": 6, "pady": 2}
        ttk.Label(panel, text="— 深度估计 —").pack(anchor="w", padx=6, pady=(8, 0))
        self.depth_backend = tk.StringVar(value="luminance")
        for key, (desc, needs_dl) in DEPTH_BACKENDS.items():
            ttk.Radiobutton(panel, text=desc, value=key,
                            variable=self.depth_backend).pack(anchor="w", **pad)

        ttk.Label(panel, text="— 尺寸映射函数 (10 种) —").pack(anchor="w", padx=6, pady=(8, 0))
        self.activation = tk.StringVar(value="power")
        self._act_combo = ttk.Combobox(panel, state="readonly",
                                       values=list(ACTIVATIONS.keys()),
                                       textvariable=self.activation)
        self._act_combo.pack(fill="x", **pad)
        ttk.Label(panel, textvariable=self._act_desc_var(),
                  wraplength=260, foreground="#666").pack(anchor="w", **pad)

        ttk.Label(panel, text="— 映射特征通道 (6 种) —").pack(anchor="w", padx=6, pady=(8, 0))
        self.feature = tk.StringVar(value="depth")
        feat_combo = ttk.Combobox(panel, state="readonly",
                                  values=list(FEATURES.keys()),
                                  textvariable=self.feature)
        feat_combo.pack(fill="x", **pad)
        ttk.Label(panel, textvariable=self._feat_desc_var(),
                  wraplength=260, foreground="#666").pack(anchor="w", **pad)

        ttk.Label(panel, text="— 波点滤除算法 —").pack(anchor="w", padx=6, pady=(8, 0))
        self.prune = tk.StringVar(value="overlap")
        for key, desc in FILTERS.items():
            ttk.Radiobutton(panel, text=desc, value=key,
                            variable=self.prune).pack(anchor="w", **pad)

        ttk.Label(panel, text="— 配色方案 —").pack(anchor="w", padx=6, pady=(8, 0))
        self.palette = tk.StringVar(value="black_red")
        pal_combo = ttk.Combobox(panel, state="readonly",
                                  values=list(DEPTH_PALETTES.keys()),
                                  textvariable=self.palette)
        pal_combo.pack(fill="x", **pad)
        pal_combo.bind("<<ComboboxSelected>>",
                       lambda e: (self.invalidate_render(),
                                  self.canvas.refresh()))

        ttk.Label(panel, text="— 生成参数 —").pack(anchor="w", padx=6, pady=(10, 0))
        self._sliders = {}
        for key, label, lo, hi, default in (
                ("n_points", "点数", 1000, 40000, 12000),
                ("alpha", "深度衰减 α", 0.2, 3.0, 1.5),
                ("sigma", "半径噪声 σ", 0.0, 0.4, 0.15),
                ("r_max", "最大半径 (px)", 4.0, 30.0, 14.0),
                ("prune_gap", "滤除间距 gap", 0.0, 8.0, 1.5),
                ("bg_spacing", "背景点间距", 8.0, 60.0, 20.0)):
            row = ttk.Frame(panel)
            row.pack(fill="x", **pad)
            ttk.Label(row, text=label, width=12).pack(side="left")
            var = tk.DoubleVar(value=default)
            self._sliders[key] = var
            ttk.Scale(row, from_=lo, to=hi, variable=var,
                      length=120).pack(side="left", fill="x", expand=True)
            ttk.Label(row, width=5,
                      textvariable=self._fmt_var(var, hi)).pack(side="left")
        # 整数显示绑定
        self._sliders["n_points"].trace_add(
            "write", lambda *_: None)
        # 开关
        self.edge_dots = tk.BooleanVar(value=True)
        self.bg_fill = tk.BooleanVar(value=True)
        self.semantic_aware = tk.BooleanVar(value=True)
        ttk.Checkbutton(panel, text="边缘增强点", variable=self.edge_dots).pack(anchor="w", **pad)
        ttk.Checkbutton(panel, text="Horror-vacui 背景填充", variable=self.bg_fill).pack(anchor="w", **pad)
        ttk.Checkbutton(panel, text="语义感知 (前景/背景双色)", variable=self.semantic_aware).pack(anchor="w", **pad)
        # seed
        row = ttk.Frame(panel)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="随机种子", width=12).pack(side="left")
        self.seed = tk.IntVar(value=42)
        ttk.Spinbox(row, from_=0, to=99999, width=7,
                    textvariable=self.seed).pack(side="left")
        ttk.Button(panel, text="重新生成 (应用参数)",
                   command=self.start_generate).pack(fill="x", padx=6, pady=8)
        ttk.Label(panel, text="— 再编辑: 重映射半径 —",
                  foreground="#844").pack(anchor="w", padx=6, pady=(6, 0))
        ttk.Button(panel, text="全部点重映射 (不重采样)",
                   command=self.remap_all).pack(fill="x", padx=6, pady=2)
        ttk.Button(panel, text="选区重映射 (Ctrl+拖框)",
                   command=self.remap_region).pack(fill="x", padx=6, pady=2)

    # 小工具: 描述/数值联动
    def _act_desc_var(self):
        var = tk.StringVar()
        def update(*_):
            var.set(ACTIVATIONS.get(self.activation.get(), ("", None))[0])
        self.activation.trace_add("write", update)
        update()
        return var

    def _feat_desc_var(self):
        var = tk.StringVar()
        def update(*_):
            var.set(FEATURES.get(self.feature.get(), ""))
        self.feature.trace_add("write", update)
        update()
        return var

    @staticmethod
    def _fmt_var(var, hi):
        label = tk.StringVar()
        def update(*_):
            v = var.get()
            label.set(f"{int(v)}" if hi >= 1000 else f"{v:.2f}")
        var.trace_add("write", update)
        update()
        return label

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[
            ("图片", "*.jpg *.jpeg *.png *.bmp *.webp"), ("所有文件", "*.*")])
        if path:
            self.load_image_file(path)

    def load_image_file(self, path):
        try:
            self.doc.load_image(path)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return
        self.selected_dot = None
        self.invalidate_render()
        self.after(50, self.canvas.fit_image)
        self.update_status(f"已加载 {os.path.basename(path)} — 点击「重新生成」")
        # 自动用亮度后端生成一版 (秒级, 无需模型)
        self.start_generate()

    def save_image(self):
        if self.doc.image is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        arr = self.get_render()
        Image.fromarray(arr).save(path)
        self.update_status(f"已保存 {path}")

    # ------------------------------------------------------------------
    # 再编辑: 半径重映射 (不重采样)
    # ------------------------------------------------------------------

    def _remap_common(self, region=None) -> None:
        if self.doc.image is None:
            messagebox.showinfo("提示", "请先打开一张图片")
            return
        try:
            n = self.doc.remap_radii(
                activation=self.activation.get(),
                feature=self.feature.get(),
                r_min=1.0,
                r_max=self._sliders["r_max"].get(),
                alpha=self._sliders["alpha"].get(),
                sigma=self._sliders["sigma"].get(),
                region=region,
                seed=self.seed.get())
        except Exception as e:
            messagebox.showerror("重映射失败", str(e))
            return
        self.invalidate_render()
        self.canvas.refresh()
        self.update_status(f"已重映射 {n} 点半径 "
                           f"({self.activation.get()} / {self.feature.get()}) — Ctrl+Z 撤销")

    def remap_all(self):
        """全部点按当前映射函数+特征重算半径 (保留位置与手动编辑)."""
        self._remap_common(region=None)

    def remap_region(self):
        """选区重映射: 无选区时提示先框选."""
        if not self._region:
            messagebox.showinfo("提示", "请先在画布上 Ctrl+左键拖出一个圆形选区")
            return
        self._remap_common(region=self._region)

    # ------------------------------------------------------------------
    # 生成 (后台线程, 防卡 UI)
    # ------------------------------------------------------------------

    def start_generate(self):
        if self.doc.image is None:
            messagebox.showinfo("提示", "请先打开一张图片")
            return
        if self._gen_thread and self._gen_thread.is_alive():
            return
        # tkinter 变量非线程安全: 在 UI 线程一次性抓取参数快照
        params = {
            "depth_backend": self.depth_backend.get(),
            "semantic_aware": self.semantic_aware.get(),
            "n_points": int(self._sliders["n_points"].get()),
            "r_max": self._sliders["r_max"].get(),
            "alpha": self._sliders["alpha"].get(),
            "sigma": self._sliders["sigma"].get(),
            "activation": self.activation.get(),
            "feature": self.feature.get(),
            "prune": self.prune.get(),
            "prune_gap": self._sliders["prune_gap"].get(),
            "edge_dots": self.edge_dots.get(),
            "bg_fill": self.bg_fill.get(),
            "bg_spacing": self._sliders["bg_spacing"].get(),
            "seed": self.seed.get(),
        }
        self._gen_result = None          # (stats, dt) 或 (None, error_msg)
        self.update_status("生成中… (深度估计可能需要数秒)")
        self._gen_thread = threading.Thread(
            target=self._generate_worker, args=(params,), daemon=True)
        self._gen_thread.start()
        self.after(100, self._poll_generate)

    def _poll_generate(self):
        """UI 线程轮询生成结果 (worker 不触碰 tkinter)."""
        if self._gen_thread and self._gen_thread.is_alive():
            self.after(100, self._poll_generate)
            return
        if self._gen_result is not None:
            stats, err = self._gen_result
            if stats is not None:
                self._generate_done(stats, err)   # err 处存放 dt
            else:
                messagebox.showerror("生成失败", err)
                self.update_status("生成失败")

    def _generate_worker(self, params: dict):
        try:
            t0 = time.time()
            self.doc.ensure_depth(
                params["depth_backend"],
                semantic_aware=params["semantic_aware"])
            stats = self.doc.generate(
                n_points=params["n_points"],
                r_max=params["r_max"],
                alpha=params["alpha"],
                sigma=params["sigma"],
                activation=params["activation"],
                feature=params["feature"],
                prune=params["prune"],
                prune_gap=params["prune_gap"],
                edge_dots=params["edge_dots"],
                bg_fill=params["bg_fill"],
                bg_spacing=params["bg_spacing"],
                seed=params["seed"])
            dt = time.time() - t0
            self._gen_result = (stats, dt)
        except Exception as e:
            self._gen_result = (None, str(e))

    def _generate_done(self, stats, dt):
        self.selected_dot = None
        self.invalidate_render()
        self.canvas.refresh()
        self.update_status(
            f"{stats['n_dots']} 点 (fg={stats['n_fg']} bg={stats['n_bg']} "
            f"edge={stats['n_edge']}), 半径 {stats['r_min']:.1f}-{stats['r_max']:.1f}px, "
            f"{dt:.1f}s")

    # ------------------------------------------------------------------
    # 渲染缓存 / 编辑
    # ------------------------------------------------------------------

    def invalidate_render(self):
        self._render_dirty = True

    def get_render(self) -> np.ndarray | None:
        if self.doc.image is None:
            return None
        if self._render_dirty or self._render_cache is None:
            # 渲染在 UI 线程做 (通常 < 0.5s); 点多时 O(n) cv2.circle
            self._render_cache = self.doc.render(
                palette=self.palette.get(),
                semantic_aware=self.semantic_aware.get())
            self._render_dirty = False
        return self._render_cache

    def after_edit(self):
        self.canvas.refresh()
        self.update_status(
            f"{len(self.doc.dots)} 点 | "
            f"可 Ctrl+Z 撤销")

    def do_undo(self):
        if self.doc.undo():
            self.selected_dot = None
            self.invalidate_render()
            self.canvas.refresh()
            self.update_status("已撤销")

    def do_redo(self):
        if self.doc.redo():
            self.selected_dot = None
            self.invalidate_render()
            self.canvas.refresh()
            self.update_status("已重做")

    def _on_tool_change(self):
        self.canvas.refresh()

    def update_status(self, msg: str | None = None):
        if msg:
            self.status_var.set(msg)
        else:
            self.status_var.set(
                f"缩放 {self.canvas.zoom:.0%} | "
                f"{len(self.doc.dots)} 点 | "
                f"工具: {self.tool.get()}")


def main():
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    model_dir = sys.argv[2] if len(sys.argv) > 2 else "models"
    app = PolkaApp(initial_image=initial, model_dir=model_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
