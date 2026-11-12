"""pipeline: 图片 → OpenCV 预处理 → 二值掩膜（GUI 的可测试核心）.

把"图像处理"环节从 tkinter 回调里拆出来做成纯函数管线, 便于单元
测试与参数调节:

    BGR 图 → 灰度 → 模糊去噪 → 阈值化(手动/OTSU/自适应)
           → 反色可选 → 形态学开闭 → 二值掩膜 (前景=True)

设计约定:
- 输入统一为 BGR np.ndarray (cv2 约定); 输出为 bool 掩膜;
- 所有参数打包在 PreprocessParams 中, GUI 滑块直接映射其字段;
- 阈值模式 "otsu" 时 threshold 字段被忽略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

__all__ = ["PreprocessParams", "preprocess", "THRESH_MODES"]


THRESH_MODES = ("manual", "otsu", "adaptive")
_BLUR_KINDS = ("none", "gauss", "median")


@dataclass
class PreprocessParams:
    """预处理参数（GUI 可调项的单一事实来源）。"""

    invert: bool = False            # 反色: 亮线稿(白底黑线)必须开启
    threshold: int = 128            # manual 模式阈值
    thresh_mode: str = "otsu"       # manual / otsu / adaptive
    blur_kind: str = "gauss"        # none / gauss / median
    blur_ksize: int = 3             # 模糊核（奇数, ≥1）
    morph_open: int = 0             # 开运算核（0=关闭; 去小白噪）
    morph_close: int = 0            # 闭运算核（0=关闭; 补小缝）
    fill_holes: bool = False        # 孔洞填充: 线稿描边围合区域补实
    max_side: int = 1024            # 加载时最长边缩放（0=不缩）

    def validate(self) -> None:
        if self.thresh_mode not in THRESH_MODES:
            raise ValueError(f"未知阈值模式: {self.thresh_mode}")
        if self.blur_kind not in _BLUR_KINDS:
            raise ValueError(f"未知模糊方式: {self.blur_kind}")
        if not 0 <= self.threshold <= 255:
            raise ValueError("threshold 需在 [0,255]")
        if self.blur_ksize < 1:
            raise ValueError("blur_ksize 至少为 1")
        if self.morph_open < 0 or self.morph_close < 0:
            raise ValueError("形态学核不能为负")
        if self.max_side < 0:
            raise ValueError("max_side 不能为负")


def _odd(k: int) -> int:
    """把核尺寸规范成 ≥1 的奇数。"""
    k = max(1, int(k))
    return k if k % 2 == 1 else k + 1


def preprocess(
    image_bgr: np.ndarray,
    params: Optional[PreprocessParams] = None,
) -> np.ndarray:
    """BGR 图 → 二值掩膜 (bool, 前景=True)。

    Args:
        image_bgr: BGR 图像。
        params: 预处理参数; None 用默认值。

    Returns:
        bool 掩膜, 与（缩放后）图像同尺寸。
    """
    p = params or PreprocessParams()
    p.validate()

    img = np.asarray(image_bgr)
    if img.ndim == 2:                     # 已是灰度
        gray = img
    elif img.ndim == 3 and img.shape[2] in (3, 4):
        if img.shape[2] == 4:             # 去 alpha
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(f"不支持的图像形状: {img.shape}")

    # 最长边缩放（性能保护, 大扫描图没必要 4000px 做分解）
    if p.max_side and max(gray.shape) > p.max_side:
        scale = p.max_side / max(gray.shape)
        gray = cv2.resize(
            gray, (int(gray.shape[1] * scale), int(gray.shape[0] * scale)),
            interpolation=cv2.INTER_AREA,
        )

    # 模糊去噪
    k = _odd(p.blur_ksize)
    if p.blur_kind == "gauss":
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    elif p.blur_kind == "median":
        gray = cv2.medianBlur(gray, k)

    # 阈值化
    if p.thresh_mode == "otsu":
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif p.thresh_mode == "adaptive":
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, max(3, _odd(k)), 5,
        )
    else:
        _, binary = cv2.threshold(gray, p.threshold, 255, cv2.THRESH_BINARY)

    # 语义: 掩膜前景 = "要分解的部件"。白底黑线的线稿阈值化后线条是
    # 黑(0)、背景白(255) → 需要 invert 让线条成为前景。
    if p.invert:
        binary = cv2.bitwise_not(binary)

    # 形态学: 开(去白噪) → 闭(补小缝)
    if p.morph_open > 0:
        ko = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (_odd(p.morph_open),) * 2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, ko)
    if p.morph_close > 0:
        kc = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (_odd(p.morph_close),) * 2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kc)

    # 孔洞填充: 闭运算只能补 ≤核尺寸的小缝, 线稿描边围合的是几十像素
    # 的大洞。从四角 flood fill 把"外部背景"标成哨兵值, 其余背景像素
    # 即被围合的孔洞 → 并入前景。
    if p.fill_holes:
        ff = binary.astype(np.uint8) * 255
        h, w = ff.shape
        mask2 = np.zeros((h + 2, w + 2), np.uint8)
        for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if ff[seed[1], seed[0]] == 0:
                cv2.floodFill(ff, mask2, seed, 100)  # 哨兵: 外部背景
        binary = ff != 100

    return binary != 0
