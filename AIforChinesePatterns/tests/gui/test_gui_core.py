"""GUI 核心逻辑测试: imio / pipeline 预处理 / fill 填色 / 集成链路.

不启动 tkinter 主循环——只测 GUI 背后的纯函数与状态对象;
app.py 的 PatternApp 用无头实例化冒烟（ withdrawn 窗口）。
"""

import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from fcp.gui.imio import imread_, imwrite_, imread_required
from fcp.gui.pipeline import PreprocessParams, preprocess, THRESH_MODES
from fcp.gui.fill import FillState, render_fill, PALETTES, _darken
from fcp.decompose import decompose_mask


# ----------------------------------------------------------------------
# 测试素材: 白底黑线"团花"线稿（模拟真实扫描线稿, 与宝相花同构但用
# 描边线而非实心块——因为 EFD 分解的是实心部件, 预处理需先闭运算把
# 线条围合的区域填实; 这里直接造实心版 + 线稿版两份）
# ----------------------------------------------------------------------
def _baoxiang_parts(size=320, line=False, line_w=3):
    """生成宝相花图。line=True 时输出白底黑线稿, False 输出白底实心部件。

    线稿模式在更大的画布上画同样几何（部件间隙 > 2*line_w, 腐蚀后
    描边才是真正的环）, 两种模式返回的参考掩膜几何一致。
    """
    k = size / 256.0
    if line:
        size = size + 2 * (line_w * 4)
        k = k * size / (size - 2 * (line_w * 4))  # 保持部件几何不变
    mask = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    r = np.hypot(xx - cx, yy - cy)
    mask[r < 30 * k] = True
    for ang in range(0, 360, 45):
        a = math.radians(ang)
        px, py = cx + 58 * k * math.cos(a), cy + 58 * k * math.sin(a)
        dx, dy = xx - px, yy - py
        la = math.radians(-ang)
        ux = dx * math.cos(la) - dy * math.sin(la)
        uy = dx * math.sin(la) + dy * math.cos(la)
        mask |= (ux / (22 * k)) ** 2 + (uy / (12 * k)) ** 2 <= 1
    for ang in range(22, 360, 45):
        a = math.radians(ang)
        px, py = cx + 100 * k * math.cos(a), cy + 100 * k * math.sin(a)
        mask |= np.hypot(xx - px, yy - py) < 9 * k
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        px, py = cx + 104 * k * math.cos(a), cy + 104 * k * math.sin(a)
        mask |= np.hypot(xx - px, yy - py) < 16 * k
    if not line:
        img = np.full((size, size, 3), 255, np.uint8)
        img[mask] = (40, 40, 40)
        return img, mask
    # 线稿: 实心区域收缩出描边（腐蚀核半径 line_w; 部件间隙须 > 2*line_w）
    inner = cv2.erode(
        mask.astype(np.uint8), np.ones((line_w * 2 + 1,) * 2, np.uint8))
    outline = mask & ~inner.astype(bool)
    img = np.full((size, size, 3), 255, np.uint8)
    img[outline] = (30, 30, 30)
    return img, mask


class TestImio:
    def test_round_trip_chinese_path(self, tmp_path: Path):
        """中文路径读写（Windows cv2.imread 的经典坑）。"""
        img = np.full((16, 16, 3), 128, np.uint8)
        p = tmp_path / "纹样目录" / "团花.png"
        assert imwrite_(p, img)
        got = imread_(p)
        assert got is not None and got.shape == (16, 16, 3)
        assert np.array_equal(got, img)

    def test_read_missing(self, tmp_path):
        assert imread_(tmp_path / "nope.png") is None
        with pytest.raises(FileNotFoundError):
            imread_required(tmp_path / "nope.png")

    def test_read_empty_file(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        assert imread_(p) is None


class TestPipeline:
    def test_solid_parts_inverted(self):
        """实心部件图（白底深色部件）: invert 后部件成为前景。"""
        img, mask_ref = _baoxiang_parts()
        m = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                             blur_kind="none"))
        # 前景应基本等于参考部件掩膜（Otsu 阈值可能吃掉抗锯齿边缘, 宽松比对）
        inter = (m & mask_ref).sum()
        union = (m | mask_ref).sum()
        assert inter / union > 0.9

    def test_solid_parts_direct(self):
        """实心部件图不反色: 前景=白背景, IoU 仍应稳定（模式对偶）。"""
        img, mask_ref = _baoxiang_parts()
        m = preprocess(img, PreprocessParams(invert=False, thresh_mode="otsu",
                                             blur_kind="none"))
        # 不反色 → 前景是大背景; 只要互为补集即可
        assert (m == ~mask_ref).mean() > 0.9

    def test_line_art_needs_fill_holes(self):
        """线稿（白底黑描边）: 孔洞填充把描边围合区域补实后才可分解。

        闭运算只能补 ≤核尺寸的小缝, 环内几十像素的大洞必须用
        flood-fill 孔洞填充; 这是线稿工作流与实心图工作流的关键差异。
        """
        img, mask_ref = _baoxiang_parts(line=True)
        # 无处理: 前景只是描边环（面积 ~20% 参考值）
        m_raw = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                                 blur_kind="none"))
        assert m_raw.sum() < mask_ref.sum() * 0.5
        # 闭运算补不了大洞
        m_closed = preprocess(img, PreprocessParams(
            invert=True, thresh_mode="otsu", blur_kind="none", morph_close=7))
        assert m_closed.sum() < mask_ref.sum() * 0.5
        # 孔洞填充: 围合区域补实
        m_filled = preprocess(img, PreprocessParams(
            invert=True, thresh_mode="otsu", blur_kind="none", fill_holes=True))
        inter = (m_filled & mask_ref).sum()
        union = (m_filled | mask_ref).sum()
        assert inter / union > 0.85

    def test_fill_holes_noop_on_solid(self):
        """实心图开孔洞填充不应改变结果（无洞可填）。"""
        img, mask_ref = _baoxiang_parts(size=160)
        a = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                             blur_kind="none"))
        b = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                             blur_kind="none", fill_holes=True))
        assert np.array_equal(a, b)

    def test_strip_border_cuts_edge_contact(self):
        """边框剥离: 贴边像素带清零, 中央区域不受影响。"""
        img, mask_ref = _baoxiang_parts(size=200)
        raw = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                               blur_kind="none"))
        stripped = preprocess(img, PreprocessParams(
            invert=True, thresh_mode="otsu", blur_kind="none",
            strip_border=10, strip_title=0.12))
        assert not stripped[:10, :].any()          # 四带清零
        assert not stripped[-10:, :].any()
        assert not stripped[:, :10].any()
        assert not stripped[:, -10:].any()
        assert not stripped[:24, :].any()          # 标题栏(200*0.12=24)
        # 中央区域保留
        h, w = stripped.shape
        assert np.array_equal(stripped[h//4:3*h//4, w//4:3*w//4],
                              raw[h//4:3*h//4, w//4:3*w//4])

    def test_strip_validation(self):
        img = np.full((32, 32, 3), 255, np.uint8)
        with pytest.raises(ValueError):
            preprocess(img, PreprocessParams(strip_border=-1))
        with pytest.raises(ValueError):
            preprocess(img, PreprocessParams(strip_title=0.6))

    def test_thresh_modes_all_work(self):
        img, _ = _baoxiang_parts(size=128)
        for mode in THRESH_MODES:
            m = preprocess(img, PreprocessParams(
                invert=True, thresh_mode=mode, blur_kind="none"))
            assert m.dtype == bool
            assert 0 < m.sum() < m.size

    def test_max_side_downscale(self):
        img, _ = _baoxiang_parts(size=256)
        m = preprocess(img, PreprocessParams(invert=True, thresh_mode="otsu",
                                             blur_kind="none", max_side=100))
        assert max(m.shape) == 100

    def test_gray_and_alpha_input(self):
        gray = np.full((64, 64), 255, np.uint8)
        gray[20:40, 20:40] = 30
        m = preprocess(gray, PreprocessParams(invert=True, thresh_mode="otsu"))
        assert m[30, 30] and not m[5, 5]
        rgba = np.dstack([np.full((64, 64), 255, np.uint8)] * 3 +
                         [np.full((64, 64), 255, np.uint8)])
        rgba[20:40, 20:40, :3] = 30
        m2 = preprocess(rgba, PreprocessParams(invert=True, thresh_mode="otsu"))
        assert m2[30, 30]

    def test_validation(self):
        img = np.full((32, 32, 3), 255, np.uint8)
        with pytest.raises(ValueError):
            preprocess(img, PreprocessParams(thresh_mode="bogus"))
        with pytest.raises(ValueError):
            preprocess(img, PreprocessParams(threshold=999))
        with pytest.raises(ValueError):
            preprocess(img, PreprocessParams(morph_open=-1))
        with pytest.raises(ValueError):
            preprocess(np.zeros((5,)), None)


class TestFillState:
    def _state(self, size=128, **kw):
        img, mask = _baoxiang_parts(size=size)
        dec = decompose_mask(mask, max_order=12, tol=1.5)
        return FillState(decomposition=dec, **kw), mask

    def test_default_palette_rotation(self):
        state, _ = self._state()
        colors = [state.color_of(i) for i in range(10)]
        assert colors[0] == colors[6]  # 6 色轮转
        assert state.color_of(0) in PALETTES["敦煌"]

    def test_set_part_color_overrides(self):
        state, _ = self._state()
        state.set_part_color(0, "#ff0000")
        assert state.color_of(0) == "#ff0000"
        assert state.color_of(1) != "#ff0000"

    def test_order_override(self):
        state, _ = self._state()
        part0 = state.decomposition.parts[0]
        auto = state.effective_curve(0)
        assert auto.order == part0.order
        state.order_override = 5
        over = state.effective_curve(0)
        assert over.order == 5

    def test_render_modes(self):
        for mode in ("lines", "fill", "both"):
            state, _ = self._state(size=96, mode=mode)
            img = render_fill(state, size=128, supersample=1)
            assert img.size == (128, 128)
            assert np.asarray(img).std() > 5

    def test_render_empty_raises(self):
        from fcp.decompose import Decomposition
        state = FillState(decomposition=Decomposition())
        with pytest.raises(ValueError):
            render_fill(state)

    def test_darken(self):
        got = _darken("#ffffff", 0.5)
        assert got == "#7f7f7f" or got == "#808080"  # HLS 往返的 1 LSB 差


class TestIntegration:
    """端到端: 图片 → 预处理 → 分解 → 填色 → 导出（GUI 回调背后的链路）。"""

    def test_full_chain(self, tmp_path: Path):
        img, mask_ref = _baoxiang_parts(size=160)
        params = PreprocessParams(invert=True, thresh_mode="otsu",
                                  blur_kind="gauss")
        mask = preprocess(img, params)
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        assert len(dec.parts) == 21

        state = FillState(decomposition=dec, palette_name="青花", mode="both")
        out = tmp_path / "填色结果" / "团花.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        render_fill(state, size=256).save(out)
        assert out.exists() and out.stat().st_size > 1000

        # 中文路径再读回（imio 兜底）
        assert imread_(out) is not None

        # Spec 导出
        spec = dec.to_pattern(
            colors=[state.color_of(i) for i in range(len(dec.parts))],
            name="gui_test").to_spec()
        spec_path = tmp_path / "团花_spec.json"
        spec_path.write_text(spec.to_json(), encoding="utf-8")
        obj = json.loads(spec_path.read_text(encoding="utf-8"))
        assert len(obj["placements"]) == 21

    def test_order_override_visual_effect(self, tmp_path):
        """全局阶数覆盖应改变渲染（低阶 vs 自动阶差异可测）。"""
        img, mask = _baoxiang_parts(size=128)
        dec = decompose_mask(mask, max_order=16, tol=1.0)
        auto = FillState(decomposition=dec, mode="fill")
        low = FillState(decomposition=dec, mode="fill", order_override=3)
        a = np.asarray(render_fill(auto, size=192, supersample=1))
        b = np.asarray(render_fill(low, size=192, supersample=1))
        # 低阶重建更平滑 → 两图必有可见差异
        assert np.abs(a.astype(int) - b.astype(int)).mean() > 1.0


class TestAppSmoke:
    """PatternApp 无头冒烟: 实例化 + 全链路状态方法（不进 mainloop）。"""

    def test_app_headless(self, tmp_path):
        pytest.importorskip("tkinter")
        try:
            from fcp.gui.app import PatternApp
        except Exception:
            pytest.skip("无显示环境")
        img, _ = _baoxiang_parts(size=128)
        img_path = tmp_path / "纹样.png"
        cv2.imencode(".png", img[:, :, ::-1])[1].tofile(str(img_path))
        try:
            app = PatternApp()
        except tk.TclError:
            pytest.skip("无显示环境")
        app.withdraw()
        app.load_image(str(img_path))
        assert app.image_bgr is not None
        # 实心部件图（白底深色部件）: 勾反色让部件成为前景
        app.invert_var.set(True)
        app.on_apply_preprocess()
        assert app.mask is not None
        app.on_decompose()
        assert app.fill_state is not None
        assert len(app.fill_state.decomposition.parts) == 21
        # 对称归并: 8 花瓣 + 圆点 + 角叶 + 中心 → 母题数远小于部件数
        app.merge_var.set(True)
        app._on_merge_toggle()
        assert app.merged_pattern is not None
        n_motifs = len(app.merged_pattern.motifs)
        assert n_motifs < 21
        n_inst = len(app.merged_pattern.instances())
        assert n_inst == 21                    # 摆放数 = 部件数
        # 归并渲染可用
        app.view = "fill"
        assert app._current_image() is not None
        # 视图切换
        for view in ("mask", "lines", "fill", "original"):
            app.view = view
            assert app._current_image() is not None
        app.destroy()


import tkinter as tk  # noqa: E402  (TestAppSmoke 顶部需要, 但放底部避免影响收集)


# ----------------------------------------------------------------------
# 2026-11 审阅回归: 归并模式的改色同步 / 阶数覆盖 / 模式锁 / 状态还原
# ----------------------------------------------------------------------
def _make_app():
    pytest.importorskip("tkinter")
    from fcp.gui.app import PatternApp
    last = None
    # 连续创建/销毁 Tk 根窗口在 Windows 上偶发 TclError（资源回收竞态）,
    # 短重试避免把可恢复的瞬态当成"无显示环境"跳过
    for _ in range(3):
        try:
            app = PatternApp()
            app.withdraw()
            return app
        except tk.TclError as e:
            last = e
    pytest.skip(f"无显示环境: {last}")


def _make_merged_app(tmp_path):
    """构造已完成分解+开归并的 app（21 部件宝相花）。"""
    app = _make_app()
    img, _ = _baoxiang_parts(size=128)
    p = tmp_path / "纹样.png"
    cv2.imencode(".png", img[:, :, ::-1])[1].tofile(str(p))
    app.load_image(str(p))
    app.invert_var.set(True)
    app.on_decompose()
    app.merge_var.set(True)
    app._on_merge_toggle()
    assert app.merged_pattern is not None
    return app


class TestMergeGuiFeatures:
    def test_recolor_syncs_merged_pattern(self, tmp_path):
        """点击改色须同步归并 Pattern 的对应摆放（修复前: 归并模式下
        改色只进 fill_state, 渲染/导出仍用旧色, 改色静默失效）。"""
        app = _make_merged_app(tmp_path)
        try:
            app._recolor_part(0, "#123456")
            assert app.fill_state.color_of(0) == "#123456"
            assert app.merged_pattern.placements[0].color == "#123456"
            # 其余部件不受影响
            assert app.merged_pattern.placements[1].color != "#123456"
        finally:
            app.destroy()

    def test_order_override_applies_to_motifs(self, tmp_path):
        """全局阶数覆盖在归并模式下应作用于共享母题（修复前: 滑块在
        归并模式是无效操作）。"""
        app = _make_merged_app(tmp_path)
        try:
            originals = {n: c.order for n, c in
                         app.merged_pattern.motifs.items()}
            app.order_override_var.set(4)
            app._on_order_override()
            assert all(c.order == 4
                       for c in app.merged_pattern.motifs.values())
            # 归零还原自动阶数
            app.order_override_var.set(0)
            app._on_order_override()
            assert {n: c.order for n, c in
                    app.merged_pattern.motifs.items()} == originals
        finally:
            app.destroy()

    def test_mode_combo_locked_in_merge(self, tmp_path):
        """归并模式下渲染模式不适用（render_pattern 无 both 态）, 下拉
        应禁用; 取消归并恢复。"""
        app = _make_merged_app(tmp_path)
        try:
            assert "disabled" in app.mode_combo.state()
            app.merge_var.set(False)
            app._on_merge_toggle()
            assert "disabled" not in app.mode_combo.state()
        finally:
            app.destroy()

    def test_lines_view_restores_filled_on_render_error(
            self, tmp_path, monkeypatch):
        """线条视图临时置 filled=False 须有 finally 保护（修复前: 渲染
        抛异常则摆放永久停留线条态, 填色视图与 PNG 导出一起退化）。"""
        app = _make_merged_app(tmp_path)
        try:
            import fcp.render

            def boom(pattern, size=512, **kw):
                raise RuntimeError("渲染失败")

            monkeypatch.setattr(fcp.render, "render_pattern", boom)
            app.view = "lines"
            with pytest.raises(RuntimeError):
                app._current_image()
            assert all(pl.filled for pl in app.merged_pattern.placements)
        finally:
            app.destroy()

    def test_load_image_resets_merge_state(self, tmp_path):
        """换图后上一张的归并 Pattern/信息标签不能泄漏（修复前:
        load_image 只重置 fill_state, 不重置 merged_pattern）。"""
        app = _make_merged_app(tmp_path)
        try:
            img, _ = _baoxiang_parts(size=128)
            p2 = tmp_path / "第二张.png"
            cv2.imencode(".png", img[:, :, ::-1])[1].tofile(str(p2))
            app.load_image(str(p2))
            assert app.merged_pattern is None
            assert app._merge_motif_canonicals is None
            assert app.merge_info.cget("text") == ""
        finally:
            app.destroy()

    def test_collect_params_strip_title_knob(self, tmp_path):
        """标题栏剥离比例是独立旋钮（修复前: 0.12 硬编码绑定边框勾选,
        主体进入顶部 12% 的素材会被静默裁掉且无法关闭）。"""
        app = _make_app()
        try:
            app.strip_border_var.set(False)
            app.strip_title_var.set(15)
            assert app._collect_params().strip_title == 0.0
            app.strip_border_var.set(True)
            assert app._collect_params().strip_title == 0.15
            app.strip_title_var.set(0)
            assert app._collect_params().strip_title == 0.0
            assert app._collect_params().strip_border == int(
                app.strip_band_var.get())
        finally:
            app.destroy()
