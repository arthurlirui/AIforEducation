"""test_gui_polka.py — 桌面编辑器核心层 (PolkaDocument) 单元测试.

不依赖 tkinter / 显示器; 全部测试用合成图像, 不加载 YOLO26 权重
(深度后端用 luminance 伪深度), 保证可在任何环境运行.
YOLO26 后端仅做注册表存在性检查.
"""

import os
import sys
import cv2
import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.gui.polka_document import (  # noqa: E402
    PolkaDocument, Dot, DEPTH_BACKENDS, ACTIVATIONS, FILTERS,
)
from dotartkit.ops.depth import DEPTH_PALETTES  # noqa: E402


@pytest.fixture
def doc():
    """合成测试图: 左半暗 (近) 右半亮 (远) 的渐变."""
    d = PolkaDocument()
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    # x 方向亮度渐变: 暗=近 (luminance 后端), 亮=远
    grad = np.linspace(10, 240, 160).astype(np.uint8)
    img[:] = grad[None, :, None]
    d.load_image(img)
    return d


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

class TestRegistries:
    def test_depth_backends(self):
        assert set(DEPTH_BACKENDS) == {"yolo26", "luminance"}
        assert DEPTH_BACKENDS["yolo26"][1] is True       # needs DL
        assert DEPTH_BACKENDS["luminance"][1] is False

    def test_activations(self):
        # 4 经典 + 2 几何感知 (曲率) + 4 再编辑映射 (log/cosine/step/inverse) = 10
        assert set(ACTIVATIONS) == {"power", "linear", "sigmoid", "sqrt",
                                    "curvature", "depth_curv",
                                    "log", "cosine", "step", "inverse"}
        for key, (desc, fn) in ACTIVATIONS.items():
            assert callable(fn) and desc

    def test_filters(self):
        assert set(FILTERS) == {"none", "overlap", "min_dist", "density"}


# ---------------------------------------------------------------------------
# 图像加载与深度
# ---------------------------------------------------------------------------

class TestLoadAndDepth:
    def test_load_ndarray(self, doc):
        assert doc.size == (160, 120)
        assert doc.image is not None and doc.gray is not None

    def test_load_from_path(self, tmp_path):
        p = tmp_path / "t.png"
        Image.fromarray(np.full((40, 50, 3), 128, np.uint8)).save(p)
        d = PolkaDocument()
        d.load_image(str(p))
        assert d.size == (50, 40)

    def test_load_resizes_long_edge(self):
        d = PolkaDocument()
        big = np.zeros((2000, 3000, 3), np.uint8)
        d.load_image(big, target_long_edge=512)
        assert max(d.size) <= 512

    def test_ensure_depth_luminance(self, doc):
        doc.ensure_depth("luminance", semantic_aware=True)
        assert doc.d_norm is not None and doc.density is not None
        assert doc.fg_mask is not None
        # 伪深度: 暗(左, x≈0)应近 → d_norm 小
        assert doc.d_norm[60, 5] < 0.3
        assert doc.d_norm[60, 155] > 0.7

    def test_ensure_depth_cached(self, doc):
        doc.ensure_depth("luminance")
        d1 = doc.depth_raw
        doc.ensure_depth("luminance")   # 第二次应跳过重算
        assert doc.depth_raw is d1

    def test_unknown_backend(self, doc):
        with pytest.raises(ValueError):
            doc.ensure_depth("miDaS_v3")

    def test_no_image_raises(self):
        with pytest.raises(RuntimeError):
            PolkaDocument().ensure_depth("luminance")


# ---------------------------------------------------------------------------
# 生成 (四类算法全组合)
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_basic_generate(self, doc):
        doc.ensure_depth("luminance")
        stats = doc.generate(n_points=800, r_max=3.0,
                             activation="power", prune="none")
        assert stats["n_dots"] == len(doc.dots) > 100
        assert stats["r_min"] >= 0.3
        assert stats["r_max"] <= 3.0 * 1.1 + 1e-6
        # 暗侧 (近) 的点应比亮侧 (远) 大
        left = [d.r for d in doc.dots if d.x < 80 and d.role == "fg"]
        right = [d.r for d in doc.dots if d.x >= 80 and d.role == "fg"]
        if left and right:
            assert np.mean(left) > np.mean(right)

    @pytest.mark.parametrize("activation", list(ACTIVATIONS))
    def test_all_activations(self, doc, activation):
        doc.ensure_depth("luminance")
        stats = doc.generate(n_points=500, r_max=3.0,
                             activation=activation, seed=7)
        assert stats["n_dots"] > 50

    @pytest.mark.parametrize("prune", list(FILTERS))
    def test_all_filters(self, doc, prune):
        doc.ensure_depth("luminance")
        stats = doc.generate(n_points=600, r_max=3.0, prune=prune,
                             prune_gap=1.0, seed=7)
        assert stats["n_dots"] > 50

    def test_overlap_prune_reduces_dots(self, doc):
        doc.ensure_depth("luminance")
        n_none = doc.generate(n_points=800, prune="none")["n_dots"]
        n_pruned = doc.generate(n_points=800, prune="overlap",
                                prune_gap=2.0)["n_dots"]
        assert n_pruned < n_none

    def test_roles_after_filter(self, doc):
        # 滤除后 roles 必须与点对齐 (长度一致且取值合法)
        doc.ensure_depth("luminance")
        doc.generate(n_points=600, r_max=3.0, prune="min_dist", prune_gap=3.0)
        assert all(d.role in ("fg", "bg", "edge") for d in doc.dots)

    def test_edge_and_bg_dots(self, doc):
        # 渐变底图无边缘 → 画一个亮方块制造 Canny 边缘
        doc.image[40:80, 60:100] = 255
        doc.gray = cv2.cvtColor(doc.image, cv2.COLOR_RGB2GRAY)
        doc.ensure_depth("luminance")
        doc.generate(n_points=300, r_max=2.0, edge_dots=True, bg_fill=True,
                     bg_spacing=6.0)
        roles = {d.role for d in doc.dots}
        assert "edge" in roles
        assert "bg" in roles

    def test_seed_determinism(self, doc):
        doc.ensure_depth("luminance")
        a = doc.generate(n_points=400, seed=123)["n_dots"]
        pts_a = [(round(d.x, 3), round(d.y, 3), round(d.r, 3))
                 for d in doc.dots]
        doc.generate(n_points=400, seed=123)
        pts_b = [(round(d.x, 3), round(d.y, 3), round(d.r, 3))
                 for d in doc.dots]
        assert pts_a == pts_b

    def test_generate_without_depth_raises(self, doc):
        with pytest.raises(RuntimeError):
            doc.generate()


# ---------------------------------------------------------------------------
# 编辑操作 + undo/redo
# ---------------------------------------------------------------------------

class TestEditing:
    def _ready(self, doc):
        doc.ensure_depth("luminance")
        doc.generate(n_points=400, seed=3)

    def test_find_dot_hit(self, doc):
        self._ready(doc)
        d = doc.dots[10]
        assert doc.find_dot(d.x, d.y) == 10
        assert doc.find_dot(d.x + d.r * 0.5, d.y) == 10

    def test_find_dot_miss(self, doc):
        self._ready(doc)
        assert doc.find_dot(-100, -100) is None

    def test_delete_dot(self, doc):
        self._ready(doc)
        n = len(doc.dots)
        doc.delete_dot(0)
        assert len(doc.dots) == n - 1
        assert doc.undo() and len(doc.dots) == n
        assert doc.redo() and len(doc.dots) == n - 1

    def test_delete_dots_in_circle(self, doc):
        self._ready(doc)
        n = len(doc.dots)
        removed = doc.delete_dots_in_circle(80, 60, 20)
        assert removed > 0 and len(doc.dots) == n - removed
        assert doc.undo() and len(doc.dots) == n

    def test_move_and_commit(self, doc):
        self._ready(doc)
        doc.add_dot(50, 60, 2.0)          # 加一个标记点 (索引 = -1)
        old = (50.0, 60.0)
        doc.begin_edit()                  # 交互编辑开始: 快照
        doc.move_dot(-1, 10, 10)
        doc.end_edit(changed=True)        # 提交
        assert (doc.dots[-1].x, doc.dots[-1].y) == (10, 10)
        assert doc.undo()                 # 回到移动前
        assert (doc.dots[-1].x, doc.dots[-1].y) == old
        assert doc.redo()
        assert (doc.dots[-1].x, doc.dots[-1].y) == (10, 10)

    def test_resize_dot(self, doc):
        self._ready(doc)
        doc.resize_dot(0, 9.5)
        assert doc.dots[0].r == 9.5
        doc.resize_dot(0, -5)             # clamp
        assert doc.dots[0].r == 0.3

    def test_set_dot_role(self, doc):
        self._ready(doc)
        doc.set_dot_role(0, "bg")
        assert doc.dots[0].role == "bg"
        doc.set_dot_role(0, "bogus")      # 非法角色被忽略
        assert doc.dots[0].role == "bg"

    def test_add_dot(self, doc):
        self._ready(doc)
        n = len(doc.dots)
        doc.add_dot(33, 44, 5.0, "fg")
        assert len(doc.dots) == n + 1
        last = doc.dots[-1]
        assert (last.x, last.y, last.r, last.role) == (33, 44, 5.0, "fg")
        assert doc.undo() and len(doc.dots) == n

    def test_undo_redo_stacks(self, doc):
        self._ready(doc)
        doc.undo()   # 撤销 _ready 的 generate 记录, 使栈底为空
        doc._undo_stack.clear()
        n0 = len(doc.dots)
        doc.add_dot(1, 1, 2)
        doc.add_dot(2, 2, 2)
        assert len(doc.dots) == n0 + 2
        assert doc.undo() and doc.undo()
        assert len(doc.dots) == n0
        assert not doc.undo()             # 栈空
        assert doc.redo() and doc.redo()
        assert len(doc.dots) == n0 + 2
        assert not doc.redo()

    def test_edit_after_generate_history(self, doc):
        # generate 会 push 历史 → undo 回到生成前的点集
        self._ready(doc)
        n = len(doc.dots)
        doc.generate(n_points=200, seed=9)
        assert len(doc.dots) != n
        assert doc.undo() and len(doc.dots) == n


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

class TestRender:
    def _ready(self, doc):
        doc.ensure_depth("luminance")
        doc.generate(n_points=400, seed=5)

    @pytest.mark.parametrize("palette", list(DEPTH_PALETTES))
    def test_all_palettes(self, doc, palette):
        self._ready(doc)
        out = doc.render(palette=palette)
        assert out.shape == (120, 160, 3)
        assert out.dtype == np.uint8
        pal = DEPTH_PALETTES[palette]
        bg_rgb = pal["bg"][::-1]
        # 画布背景色必须出现 (未被点完全覆盖)
        assert (out == np.array(bg_rgb)).any()

    def test_render_respects_delete(self, doc):
        self._ready(doc)
        out_before = doc.render()
        # 找一个非背景像素的点删掉, 该处应变回背景色 (大概率)
        doc.delete_dot(0)
        out_after = doc.render()
        assert not np.array_equal(out_before, out_after)

    def test_render_role_visibility(self, doc):
        self._ready(doc)
        full = doc.render()
        part = doc.render(dot_roles_visible={"fg"})
        # 只画 fg 时, 被删角色覆盖的像素应为背景色
        pal = DEPTH_PALETTES["black_red"]
        bg_rgb = np.array(pal["bg"][::-1])
        assert (part == bg_rgb).all(axis=2).sum() >= \
               (full == bg_rgb).all(axis=2).sum()

    def test_render_no_image_raises(self):
        with pytest.raises(RuntimeError):
            PolkaDocument().render()


# ---------------------------------------------------------------------------
# YOLO26 后端 (仅注册检查, 不加载权重)
# ---------------------------------------------------------------------------

class TestYoloBackend:
    def test_registered_but_not_required(self):
        assert "yolo26" in DEPTH_BACKENDS
        # 不实际调用 ensure_depth("yolo26") — 需要权重文件与 GPU,
        # 端到端验证由 scripts/run_gui_e2e.py 覆盖.
