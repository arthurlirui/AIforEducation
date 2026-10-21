"""dotartkit.ops — 底层算子（位置 / 半径 / 颜色）.

本子包提供波点艺术生成器共享的基础设施:

- :mod:`color`  — RGB/HSV 转换、调色板、互补色、亮度
- :mod:`grid`   — O(1) 近邻最小距离查询 (``_GridHash``)
- :mod:`voronoi` — Secord Weighted Voronoi Stippling 核心 (依赖 scipy)
- :mod:`depth`  — YOLO26 单目深度 / 语义分割 (可选依赖 ultralytics)

设计原则: 算子层不做风格化决策, 只提供可复用的数学原语.
"""

from .color import (  # noqa: F401
    to_float01,
    luminance,
    rgb_to_hsv,
    hsv_to_rgb,
    sample_color,
    draw_disks,
)
from .grid import GridHash  # noqa: F401

__all__ = [
    "to_float01",
    "luminance",
    "rgb_to_hsv",
    "hsv_to_rgb",
    "sample_color",
    "draw_disks",
    "GridHash",
]
