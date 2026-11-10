"""DotArtKit 冒烟测试.

纯 numpy 模式全部覆盖: 输出尺寸 / 非空 / seed 确定性.
DL 模式 (kusama_depth) 仅在 ultralytics 可用时跑; learned 走无 torch 回退路径.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image

from dotartkit import (
    MODES,
    generate,
    has_scipy,
    has_torch,
    has_ultralytics,
    list_modes,
    mode_info,
)


@pytest.fixture(scope="module")
def tiny_image() -> Image.Image:
    """120x90 渐变 + 噪声测试图."""
    h, w = 90, 120
    arr = np.tile(np.linspace(30, 225, w, dtype=np.uint8), (h, 1))
    arr = np.stack([arr, arr // 2, 255 - arr], axis=-1)
    rng = np.random.default_rng(0)
    noise = rng.integers(-20, 20, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


PURE_MODES = ["seurat", "benday", "warp", "stipple", "vogel"]


class TestRegistry:
    def test_eight_modes_registered(self):
        assert len(MODES) == 8
        for m in ("seurat", "benday", "warp", "stipple", "vogel",
                  "kusama_basic", "kusama_depth", "learned"):
            assert m in list_modes()

    def test_mode_info_covers_all(self):
        for m in list_modes():
            assert "desc" in mode_info(m)

    def test_unknown_mode_raises(self, tiny_image):
        with pytest.raises(ValueError, match="unknown mode"):
            generate("nope", tiny_image)


class TestPureModes:
    @pytest.mark.parametrize("mode", PURE_MODES)
    def test_output_shape_and_nonblank(self, mode, tiny_image):
        out = generate(mode, tiny_image, seed=0)
        assert isinstance(out, Image.Image)
        assert out.size == tiny_image.size
        arr = np.array(out.convert("L"))
        # 有内容: 不是纯背景
        assert arr.std() > 1.0

    @pytest.mark.parametrize("mode", PURE_MODES)
    def test_seed_determinism(self, mode, tiny_image):
        a = np.array(generate(mode, tiny_image, seed=7))
        b = np.array(generate(mode, tiny_image, seed=7))
        assert np.array_equal(a, b)


class TestKusamaBasic:
    def test_render(self, tiny_image):
        out = generate("kusama_basic", tiny_image, seed=0)
        assert out.size == tiny_image.size

    def test_scipy_probe_no_crash(self):
        # 探测函数不抛异常即可 (True/False 均合法, 退化路径不报警是已知待办)
        assert isinstance(has_scipy(), bool)

    def test_ndarray_core_matches_path_wrapper(self, tiny_image, tmp_path):
        """S4 回归: PIL 适配 (ndarray 核心, 零磁盘 I/O) 与路径薄包装输出逐位一致."""
        from dotartkit.styles.kusama_basic import kusama_polka, kusama_polka_core
        kw = dict(seed=5, n_points=400, n_iter=3, r_max=3.0,
                  palette="yellow_black")
        out_pil = generate("kusama_basic", tiny_image, **kw)   # PIL → ndarray 核心
        # 路径薄包装: 读 PNG → 核心 → 写 PNG
        inp = tmp_path / "in.png"
        tiny_image.save(inp)
        outp = tmp_path / "out.png"
        canvas = kusama_polka(str(inp), str(outp), **kw)
        # ndarray 核心: 同输入 (imread) 同 seed → 与包装返回的 canvas 逐位相等
        img_bgr = cv2.imread(str(inp))
        assert np.array_equal(kusama_polka_core(img_bgr, **kw), canvas)
        # PIL 适配输出与包装写出的 PNG 逐位相等 (同 seed 同输入)
        assert np.array_equal(np.array(out_pil.convert("RGB")),
                              np.array(Image.open(outp).convert("RGB")))
        # 无临时文件残留: 目录里只应有输入/输出两个文件
        assert sorted(p.name for p in tmp_path.iterdir()) == ["in.png", "out.png"]


class TestKusamaDepthAdapters:
    """S4 回归: kusama_depth 的 PIL 适配与路径包装走同一 ndarray 核心.

    mock 掉模型加载 (_get_model), 无需 ultralytics/权重即可在任何环境运行;
    伪分割把右半置为前景类, 覆盖双色绘制路径.
    """

    def test_ndarray_core_matches_path_wrapper(self, monkeypatch, tiny_image,
                                               tmp_path):
        import dotartkit.styles.kusama_depth as kd

        class FakeDepth:
            def predict(self, img):
                h, w = img.shape[:2]
                return np.tile(np.linspace(0.5, 2.5, w, dtype=np.float32), (h, 1))

        class FakeSem:
            def predict(self, img):
                h, w = img.shape[:2]
                seg = np.zeros((h, w), np.uint8)
                seg[:, w // 2:] = 11      # person → 前景, 覆盖双色绘制
                return seg

        monkeypatch.setattr(kd, "_get_model",
                            lambda kind, path, device:
                            FakeDepth() if kind == "depth" else FakeSem())
        monkeypatch.setattr(kd, "has_ultralytics", lambda: True)

        kw = dict(seed=5, n_points=300, r_max=6.0, overlap_gap=3.0)
        out_pil = kd.generate_kusama_depth(tiny_image, **kw)   # PIL → ndarray 核心
        inp = tmp_path / "in.png"
        tiny_image.save(inp)
        outp = tmp_path / "out.png"
        stats = kd.depth_kusama_polka(str(inp), str(outp), **kw)  # 路径薄包装
        assert stats["n_total_dots"] > 0
        assert stats["output"] == str(outp)
        # PIL 适配输出与包装写出的 PNG 逐位相等 (同 seed 同输入)
        assert np.array_equal(np.array(out_pil.convert("RGB")),
                              np.array(Image.open(outp).convert("RGB")))
        # 无临时文件残留: 目录里只应有输入/输出两个文件
        assert sorted(p.name for p in tmp_path.iterdir()) == ["in.png", "out.png"]


class TestLearned:
    def test_render_fallback(self, tiny_image):
        """无 model/ckpt 时走固定幂律回退, 无 torch 也能渲染."""
        out = generate("learned", tiny_image, n_dots=800, seed=0)
        assert out.size == tiny_image.size
        assert np.array(out.convert("L")).std() > 1.0

    def test_seed_determinism(self, tiny_image):
        a = np.array(generate("learned", tiny_image, n_dots=500, seed=3))
        b = np.array(generate("learned", tiny_image, n_dots=500, seed=3))
        assert np.array_equal(a, b)

    def test_torch_probe(self):
        assert isinstance(has_torch(), bool)


class TestDepsProbes:
    def test_ultralytics_probe(self):
        assert isinstance(has_ultralytics(), bool)


@pytest.mark.skipif(not has_ultralytics(), reason="需 ultralytics + YOLO26 权重")
class TestKusamaDepth:
    def test_render(self, tiny_image):
        out = generate("kusama_depth", tiny_image, seed=0)
        assert isinstance(out, Image.Image)
