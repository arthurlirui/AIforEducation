"""app.py — 中国传统纹样傅里叶分解编辑器 (tkinter, 论文 Demo 软件).

布局::

    +----------------------------------------------------------+
    | 工具栏: 打开 | 预处理参数 | 分解 | 填色模式 | 导出         |
    +---------------+------------------------------------------+
    | 参数面板       |  画布 (三视图切换: 原图/掩膜/线条/填色)    |
    |  预处理        |                                          |
    |  分解参数      |                                          |
    |  填色/调色板   |                                          |
    +---------------+------------------------------------------+
    | 状态栏: 部件数 / 阶数 / 耗时 / 提示                        |
    +----------------------------------------------------------+

工作流: 打开图片 → 调预处理(线稿需勾"反色") → 分解(自动选阶)
       → 拖动全局阶数滑块看谐波收敛 → 选调色板/填色模式 → 导出 PNG+Spec

运行::

    py -m fcp.gui          # 或
    py -m fcp.gui.app 图片路径
"""

from __future__ import annotations

import json
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

from .imio import imread_
from .pipeline import PreprocessParams, preprocess, THRESH_MODES
from .fill import FillState, render_fill, PALETTES
from ..decompose import decompose_mask
from ..fourier_curve import FourierCurve

_APP_TITLE = "傅里叶纹样 · 中国传统纹样分解编辑器"


class PatternApp(tk.Tk):
    # 画布视图
    VIEW_ORIGINAL = "original"
    VIEW_MASK = "mask"
    VIEW_LINES = "lines"
    VIEW_FILL = "fill"

    def __init__(self, image_path: str | None = None):
        super().__init__()
        self.title(_APP_TITLE)
        self.geometry("1280x820")

        # ---- 状态 ----
        self.image_bgr: np.ndarray | None = None      # 原图 (缩放后)
        self.image_rgb: Image.Image | None = None
        self.mask: np.ndarray | None = None           # 预处理结果
        self.params = PreprocessParams()
        self.fill_state: FillState | None = None
        self.view = self.VIEW_FILL
        self._photo: ImageTk.PhotoImage | None = None
        self._decompose_ms = 0.0

        self._build_ui()
        self._refresh_view()

        if image_path:
            self.load_image(image_path)

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self) -> None:
        self._build_toolbar()
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        self._build_panel(body)
        self._build_canvas(body)
        self._build_statusbar()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=4, pady=3)
        ttk.Button(bar, text="打开图片", command=self.on_open).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="应用预处理", command=self.on_apply_preprocess).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="傅里叶分解", command=self.on_decompose).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(bar, text="视图:").pack(side=tk.LEFT)
        self.view_var = tk.StringVar(value=self.view)
        for text, val in (("原图", self.VIEW_ORIGINAL), ("掩膜", self.VIEW_MASK),
                          ("线条", self.VIEW_LINES), ("填色", self.VIEW_FILL)):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.view_var,
                            command=self._refresh_view).pack(side=tk.LEFT, padx=1)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="导出填色 PNG", command=self.on_export_png).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="导出 Spec JSON", command=self.on_export_spec).pack(side=tk.LEFT, padx=2)

    def _build_panel(self, parent) -> None:
        panel = ttk.Frame(parent, width=300)
        panel.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=4)
        panel.pack_propagate(False)

        # ---------- 预处理参数 ----------
        pp = ttk.LabelFrame(panel, text="OpenCV 预处理")
        pp.pack(fill=tk.X, padx=4, pady=4)

        self.invert_var = tk.BooleanVar(value=self.params.invert)
        ttk.Checkbutton(pp, text="反色（白底黑线稿必勾）",
                        variable=self.invert_var).pack(anchor=tk.W, padx=6, pady=2)

        row = ttk.Frame(pp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="阈值模式").pack(side=tk.LEFT)
        self.thresh_mode_var = tk.StringVar(value=self.params.thresh_mode)
        ttk.Combobox(row, textvariable=self.thresh_mode_var, state="readonly",
                     values=list(THRESH_MODES), width=8).pack(side=tk.RIGHT)

        self.thresh_var = tk.IntVar(value=self.params.threshold)
        ttk.Label(pp, text="手动阈值").pack(anchor=tk.W, padx=6)
        ttk.Scale(pp, from_=0, to=255, variable=self.thresh_var,
                  orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6)

        row = ttk.Frame(pp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="模糊").pack(side=tk.LEFT)
        self.blur_kind_var = tk.StringVar(value=self.params.blur_kind)
        ttk.Combobox(row, textvariable=self.blur_kind_var, state="readonly",
                     values=("none", "gauss", "median"), width=8).pack(side=tk.RIGHT)
        self.blur_ksize_var = tk.IntVar(value=self.params.blur_ksize)
        ttk.Label(pp, text="模糊核").pack(anchor=tk.W, padx=6)
        ttk.Scale(pp, from_=1, to=15, variable=self.blur_ksize_var,
                  orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6)

        self.morph_open_var = tk.IntVar(value=self.params.morph_open)
        ttk.Label(pp, text="开运算核（去噪, 0=关）").pack(anchor=tk.W, padx=6)
        ttk.Scale(pp, from_=0, to=15, variable=self.morph_open_var,
                  orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6)
        self.morph_close_var = tk.IntVar(value=self.params.morph_close)
        ttk.Label(pp, text="闭运算核（补缝, 0=关）").pack(anchor=tk.W, padx=6)
        ttk.Scale(pp, from_=0, to=15, variable=self.morph_close_var,
                  orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6)

        self.fill_holes_var = tk.BooleanVar(value=self.params.fill_holes)
        ttk.Checkbutton(pp, text="孔洞填充（线稿描边区域补实）",
                        variable=self.fill_holes_var).pack(anchor=tk.W, padx=6, pady=2)

        # ---------- 分解参数 ----------
        dp = ttk.LabelFrame(panel, text="傅里叶分解")
        dp.pack(fill=tk.X, padx=4, pady=4)

        row = ttk.Frame(dp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="最大阶数").pack(side=tk.LEFT)
        self.max_order_var = tk.IntVar(value=24)
        ttk.Spinbox(row, from_=4, to=64, textvariable=self.max_order_var,
                    width=5).pack(side=tk.RIGHT)

        row = ttk.Frame(dp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="误差阈值 px").pack(side=tk.LEFT)
        self.tol_var = tk.DoubleVar(value=0.8)
        ttk.Spinbox(row, from_=0.1, to=5.0, increment=0.1,
                    textvariable=self.tol_var, width=5).pack(side=tk.RIGHT)

        ttk.Label(dp, text="全局阶数覆盖（0=自动）",
                  ).pack(anchor=tk.W, padx=6, pady=(4, 0))
        self.order_override_var = tk.IntVar(value=0)
        self.order_scale = ttk.Scale(
            dp, from_=0, to=64, variable=self.order_override_var,
            orient=tk.HORIZONTAL, command=self._on_order_override)
        self.order_scale.pack(fill=tk.X, padx=6)

        # ---------- 填色 ----------
        fp = ttk.LabelFrame(panel, text="填色")
        fp.pack(fill=tk.X, padx=4, pady=4)

        row = ttk.Frame(fp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="调色板").pack(side=tk.LEFT)
        self.palette_var = tk.StringVar(value="敦煌")
        ttk.Combobox(fp, textvariable=self.palette_var, state="readonly",
                     values=list(PALETTES), width=10).pack(anchor=tk.E, padx=6)
        self.palette_var.trace_add("write", self._on_palette_change)

        row = ttk.Frame(fp); row.pack(fill=tk.X, padx=6)
        ttk.Label(row, text="渲染模式").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="both")
        ttk.Combobox(row, textvariable=self.mode_var, state="readonly",
                     values=("lines", "fill", "both"), width=8).pack(side=tk.RIGHT)
        self.mode_var.trace_add("write", self._on_mode_change)

        ttk.Label(fp, text="点击部件改色: 在填色视图下点击部件弹选色器",
                  wraplength=260).pack(anchor=tk.W, padx=6, pady=4)

    def _build_canvas(self, parent) -> None:
        self.canvas = tk.Canvas(parent, bg="#202020", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 4), pady=4)
        self.canvas.bind("<Configure>", lambda e: self._refresh_view())
        self.canvas.bind("<Button-1>", self._on_canvas_click)

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="打开一张纹样图片开始")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    # ==================================================================
    # 事件处理
    # ==================================================================
    def load_image(self, path: str) -> None:
        img = imread_(path)
        if img is None:
            messagebox.showerror("错误", f"无法读取图像:\n{path}")
            return
        # 最长边限缩（性能）
        import cv2
        p = self.params
        if p.max_side and max(img.shape[:2]) > p.max_side:
            s = p.max_side / max(img.shape[:2])
            img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                             interpolation=cv2.INTER_AREA)
        self.image_bgr = img
        self.image_rgb = Image.fromarray(img[:, :, ::-1].copy())
        self.mask = None
        self.fill_state = None
        self.view = self.VIEW_ORIGINAL
        self.view_var.set(self.view)
        self._set_status(f"已加载 {Path(path).name} "
                         f"({img.shape[1]}x{img.shape[0]}) — 调预处理后点『傅里叶分解』")
        self._refresh_view()

    def on_open(self) -> None:
        path = filedialog.askopenfilename(
            title="打开纹样图片",
            filetypes=[("图像", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.load_image(path)

    def _collect_params(self) -> PreprocessParams:
        return PreprocessParams(
            invert=self.invert_var.get(),
            threshold=int(self.thresh_var.get()),
            thresh_mode=self.thresh_mode_var.get(),
            blur_kind=self.blur_kind_var.get(),
            blur_ksize=max(1, int(self.blur_ksize_var.get())),
            morph_open=int(self.morph_open_var.get()),
            morph_close=int(self.morph_close_var.get()),
            fill_holes=self.fill_holes_var.get(),
            max_side=self.params.max_side,
        )

    def on_apply_preprocess(self) -> None:
        if self.image_bgr is None:
            messagebox.showinfo("提示", "请先打开图片")
            return
        self.params = self._collect_params()
        self.mask = preprocess(self.image_bgr, self.params)
        n_fg = int(self.mask.sum())
        self._set_status(f"预处理完成: 前景 {n_fg}px ({n_fg / self.mask.size:.1%})")
        if self.view == self.VIEW_ORIGINAL:
            self.view = self.VIEW_MASK
            self.view_var.set(self.view)
        self._refresh_view()

    def on_decompose(self) -> None:
        if self.image_bgr is None:
            messagebox.showinfo("提示", "请先打开图片")
            return
        if self.mask is None:
            self.params = self._collect_params()
            self.mask = preprocess(self.image_bgr, self.params)
        t0 = time.perf_counter()
        try:
            dec = decompose_mask(
                self.mask,
                max_order=max(4, int(self.max_order_var.get())),
                tol=max(0.1, float(self.tol_var.get())),
            )
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("分解失败", str(e))
            return
        self._decompose_ms = (time.perf_counter() - t0) * 1000
        if not dec.parts:
            messagebox.showwarning("提示", "没有检测到部件——试着勾选反色或调阈值")
            return
        self.fill_state = FillState(
            decomposition=dec,
            palette_name=self.palette_var.get(),
            mode=self.mode_var.get(),
        )
        self.order_scale.configure(to=max(8, int(self.max_order_var.get())))
        orders = sorted({p.order for p in dec.parts})
        self._set_status(
            f"分解 {len(dec.parts)} 部件 · 自动阶数 {orders} · {self._decompose_ms:.0f}ms")
        self.view = self.VIEW_FILL
        self.view_var.set(self.view)
        self._refresh_view()

    def _on_order_override(self, _value: str = "") -> None:
        if self.fill_state is None:
            return
        # 滑块拖动时实时更新（tkinter 变量在同一线程读取, 安全）
        self.fill_state.order_override = int(self.order_override_var.get())
        if self.view in (self.VIEW_LINES, self.VIEW_FILL):
            self._refresh_view()

    def _on_palette_change(self, *_):
        if self.fill_state is not None:
            self.fill_state.palette_name = self.palette_var.get()
            self.fill_state.part_colors = []
            if self.view in (self.VIEW_LINES, self.VIEW_FILL):
                self._refresh_view()

    def _on_mode_change(self, *_):
        if self.fill_state is not None:
            self.fill_state.mode = self.mode_var.get()
            if self.view in (self.VIEW_LINES, self.VIEW_FILL):
                self._refresh_view()

    def _on_canvas_click(self, event) -> None:
        """填色视图下点击部件 → 弹选色器改色。"""
        if self.fill_state is None or self.view != self.VIEW_FILL:
            return
        state = self.fill_state
        parts = state.decomposition.parts
        # 画布坐标 → 文档坐标（复用 render_fill 的缩放体系逆推）
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        img = self._current_image()
        if img is None:
            return
        iw, ih = img.size
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        ox, oy = (w - dw) / 2, (h - dh) / 2
        if not (ox <= event.x <= ox + dw and oy <= event.y <= oy + dh):
            return
        px = (event.x - ox) / scale
        py = (event.y - oy) / scale
        # 命中测试: 点在哪个部件多边形内（用 matplotlib 路径太重, 直接射线法）
        hit = -1
        for i, part in enumerate(parts):
            pts = state.effective_curve(i).to_contour(192)
            if _point_in_polygon(px, py, pts):
                hit = i
        if hit < 0:
            return
        from tkinter import colorchooser
        color = colorchooser.askcolor(
            initialcolor=state.color_of(hit), title=f"部件 {hit} 颜色")[1]
        if color:
            state.set_part_color(hit, color)
            self._refresh_view()

    # ==================================================================
    # 导出
    # ==================================================================
    def on_export_png(self) -> None:
        if self.fill_state is None:
            messagebox.showinfo("提示", "请先完成分解")
            return
        path = filedialog.asksaveasfilename(
            title="导出填色 PNG", defaultextension=".png",
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        render_fill(self.fill_state, size=1024).save(path)
        self._set_status(f"已导出 {path}")

    def on_export_spec(self) -> None:
        if self.fill_state is None:
            messagebox.showinfo("提示", "请先完成分解")
            return
        path = filedialog.asksaveasfilename(
            title="导出 PatternSpec", defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        dec = self.fill_state.decomposition
        spec = dec.to_pattern(
            colors=[self.fill_state.color_of(i) for i in range(len(dec.parts))],
            name=Path(path).stem,
        ).to_spec()
        Path(path).write_text(spec.to_json(), encoding="utf-8")
        self._set_status(f"已导出 {path}")

    # ==================================================================
    # 视图渲染
    # ==================================================================
    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _current_image(self) -> Image.Image | None:
        if self.view == self.VIEW_ORIGINAL:
            return self.image_rgb
        if self.view == self.VIEW_MASK and self.mask is not None:
            m = np.where(self.mask, 100, 235).astype(np.uint8)
            return Image.fromarray(m).convert("RGB")
        if self.view == self.VIEW_LINES and self.fill_state is not None:
            saved = self.fill_state.mode
            self.fill_state.mode = "lines"
            img = render_fill(self.fill_state, size=768)
            self.fill_state.mode = saved
            return img
        if self.view == self.VIEW_FILL and self.fill_state is not None:
            return render_fill(self.fill_state, size=768)
        return self.image_rgb

    def _refresh_view(self) -> None:
        img = self._current_image()
        if img is None:
            return
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        scale = min(w / img.width, h / img.height)
        disp = img.resize((max(1, int(img.width * scale)),
                           max(1, int(img.height * scale))), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(
            (w - disp.width) // 2, (h - disp.height) // 2,
            image=self._photo, anchor=tk.NW)


def _point_in_polygon(px: float, py: float, poly: np.ndarray) -> bool:
    """射线法点在多边形内判定。"""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            x_cross = xi + (py - yi) * (xj - xi) / (yj - yi)
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    app = PatternApp(image_path=path)
    app.mainloop()


if __name__ == "__main__":
    main()
