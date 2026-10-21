"""图像与视频工具函数。"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


def frames_to_video(frames_dir: Path, output_path: Path, fps: int) -> None:
    """将帧序列合成为 MP4 视频。"""
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        # 尝试其他命名
        frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise FileNotFoundError(f"无帧图像: {frames_dir}")

    first = cv2.imread(str(frames[0]))
    h, w = first.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
    for f in frames:
        writer.write(cv2.imread(str(f)))
    writer.release()
    logger.info("视频已合成: %s (%d 帧 @ %d fps)", output_path, len(frames), fps)
