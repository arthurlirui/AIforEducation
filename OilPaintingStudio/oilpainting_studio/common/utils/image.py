"""图像与视频工具函数。"""
from __future__ import annotations

import logging
from pathlib import Path

from ..imio import imread_required, imwrite_  # 路径安全版 (cv2 不读中文路径)

logger = logging.getLogger(__name__)


def frames_to_video(frames_dir: Path, output_path: Path, fps: int) -> None:
    """将帧序列合成为 MP4 视频（读图失败显式报错, 支持中文路径）。"""
    import cv2

    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        # 尝试其他命名
        frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise FileNotFoundError(f"无帧图像: {frames_dir}")

    first = imread_required(frames[0])
    h, w = first.shape[:2]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
    try:
        for f in frames:
            writer.write(imread_required(f))
    finally:
        writer.release()
    logger.info("视频已合成: %s (%d 帧 @ %d fps)", output_path, len(frames), fps)
