"""DotArtKit 冒烟测试.

纯 numpy 模式全部覆盖: 输出尺寸 / 非空 / seed 确定性.
DL 模式 (kusama_depth) 仅在 ultralytics 可用时跑; learned 走无 torch 回退路径.
"""
from __future__ import annotations

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
