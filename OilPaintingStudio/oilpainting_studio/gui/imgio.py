"""cv2 中文路径兼容层（Windows 下 imread/imwrite 不支持非 ASCII 路径）。

所有 GUI 后端的图像读写统一走 imdecode_/imencode_，绕开 cv2 的
路径解码问题；ASCII 路径同样可用。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """cv2.imread 的路径安全版。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path: str | Path, img: np.ndarray) -> bool:
    """cv2.imwrite 的路径安全版。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    path.write_bytes(buf.tobytes())
    return True
