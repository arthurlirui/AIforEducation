"""cv2 中文路径兼容层（Windows 下 imread/imwrite 不支持非 ASCII 路径）。

实现已上移到 common 层（oilpainting_studio.common.imio）；
本模块保留 GUI 侧惯用短名（imread/imwrite）作为兼容别名。
"""
from __future__ import annotations

from ..common.imio import imread_, imwrite_  # noqa: F401

# GUI 侧历史短名
imread = imread_
imwrite = imwrite_
