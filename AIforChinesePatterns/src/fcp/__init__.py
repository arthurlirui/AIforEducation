"""fcp: Fourier Contour Patterns — 用椭圆傅里叶描述子表达与组合传统纹样."""

from .fourier_curve import FourierCurve
from .contour import extract_contours, resample_contour
from .pattern import Placement, Pattern, PatternSpec, CurveLibrary
from .render import render_pattern
from .decompose import (
    Part,
    Decomposition,
    decompose_mask,
    pattern_from_decomposition,
)

__all__ = [
    "FourierCurve",
    "extract_contours",
    "resample_contour",
    "Placement",
    "Pattern",
    "PatternSpec",
    "CurveLibrary",
    "render_pattern",
    "Part",
    "Decomposition",
    "decompose_mask",
    "pattern_from_decomposition",
]
