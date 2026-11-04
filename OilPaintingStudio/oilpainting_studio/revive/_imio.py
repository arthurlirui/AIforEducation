"""revive 内部共享工具：cv2 中文路径兼容 (Windows)。

cv2.imread/imwrite 在 Windows 上不支持非 ASCII 路径（项目目录名可为
中文, 如 projects/星月夜/）。全部图像文件读写统一走 imread_/imwrite_。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_(path: str | Path, img: np.ndarray) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    path.write_bytes(buf.tobytes())
    return True
