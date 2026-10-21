"""api.py — 统一 API 入口.

所有流派通过 :func:`generate` 分派, 接收 PIL Image, 返回 PIL Image.

    >>> from dotartkit import generate
    >>> from PIL import Image
    >>> img = Image.open("inputs/pumpkin.jpg").convert("RGB")
    >>> out = generate("kusama_basic", img, palette="yellow_black")
    >>> out.save("output.png")

可用模式见 :data:`MODES` 或 :func:`list_modes`.
"""

from __future__ import annotations

from PIL import Image

from .styles import (
    generate_seurat,
    generate_benday,
    generate_warp,
    generate_stipple,
    generate_vogel,
    generate_kusama_basic,
    generate_kusama_depth,
)


# ---------------------------------------------------------------------------
# 模式注册表
# ---------------------------------------------------------------------------

# 无 DL 依赖的流派 (纯 numpy / scipy)
_PURE_MODES = {
    "seurat":       generate_seurat,
    "benday":       generate_benday,
    "warp":         generate_warp,
    "stipple":      generate_stipple,        # 纯 numpy Secord (GridHash)
    "vogel":        generate_vogel,
    "kusama_basic": generate_kusama_basic,    # scipy Voronoi (退化到无 Lloyd)
}

# 需要 ultralytics + YOLO26 权重的流派
_DL_MODES = {
    "kusama_depth": generate_kusama_depth,
}

# 完整模式表
MODES = {**_PURE_MODES, **_DL_MODES}


def list_modes() -> list[str]:
    """返回所有已注册的模式键."""
    return list(MODES.keys())


def list_pure_modes() -> list[str]:
    """返回无 DL 依赖的模式 (纯 numpy / scipy)."""
    return list(_PURE_MODES.keys())


def list_dl_modes() -> list[str]:
    """返回需要深度学习依赖 (ultralytics + YOLO26) 的模式."""
    return list(_DL_MODES.keys())


def mode_info(mode: str) -> dict:
    """返回某个模式的元信息 (依赖 / 简述)."""
    info = {
        "seurat":       {"deps": [],                          "desc": "点彩派: 互补色面积混合 + Bayer 抖动"},
        "benday":       {"deps": [],                          "desc": "Ben-Day 半调 / Lichtenstein 四色波普"},
        "warp":         {"deps": [],                          "desc": "Vasarely Vega 欧普凸起 (径向变形网格)"},
        "stipple":      {"deps": [],                          "desc": "Secord 计算点绘 (纯 numpy GridHash)"},
        "vogel":        {"deps": [],                          "desc": "黄金角叶序 (Vogel phyllotaxis 螺线)"},
        "kusama_basic": {"deps": ["scipy (可选)"],            "desc": "草间弥生基础版: 亮度密度 Voronoi + 多层"},
        "kusama_depth": {"deps": ["ultralytics", "YOLO26 权重", "GPU 推荐"],
                         "desc": "草间弥生深度感知版: YOLO26 深度 + 三层架构 + 语义双色"},
    }
    return info.get(mode, {"deps": [], "desc": "未知模式"})


def generate(mode: str, image: Image.Image, **kwargs) -> Image.Image:
    """统一生成入口.

    Parameters
    ----------
    mode : 模式键, 见 :func:`list_modes`
    image : 输入 PIL Image (RGB)
    **kwargs : 传递给对应流派生成函数的参数

    Returns
    -------
    PIL.Image : 生成的波点艺术图像 (RGB)

    Raises
    ------
    ValueError : 未知模式
    ImportError : DL 模式缺少 ultralytics
    """
    if mode not in MODES:
        raise ValueError(
            f"unknown mode {mode!r}, choose from {list(MODES)}; "
            f"use list_modes() to see all available modes"
        )
    return MODES[mode](image, **kwargs)
