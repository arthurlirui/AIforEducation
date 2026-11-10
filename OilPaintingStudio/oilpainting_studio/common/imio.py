"""cv2 中文路径兼容层（Windows 下 imread/imwrite 不支持非 ASCII 路径）。

cv2.imread/imwrite 在 Windows 上不支持非 ASCII 路径（项目目录名可为
中文, 如 projects/星月夜/）。全部图像文件读写统一走 imread_/imwrite_
（imdecode/imencode 实现绕开路径解码问题）；ASCII 路径同样可用。

revive/_imio.py 与 gui/imgio.py 均为兼容别名, 新代码请统一 import 本模块。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """cv2.imread 的路径安全版（读失败/空文件返回 None）。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_(path: str | Path, img: np.ndarray) -> bool:
    """cv2.imwrite 的路径安全版（自动创建父目录）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    path.write_bytes(buf.tobytes())
    return True


def imread_required(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """路径安全读图, 读不到时抛带路径的明确错误（不裸崩 AttributeError）。"""
    img = imread_(path, flags)
    if img is None:
        raise FileNotFoundError(f"无法读取图像: {path}")
    return img
