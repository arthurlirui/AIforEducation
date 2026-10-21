"""评估钩子：风格一致性 / 边缘对齐度 / 深度结构忠实度。"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..schemas import Stage3Output, Stage4Output

logger = logging.getLogger(__name__)


def eval_style_consistency(
    output_video: Path,
    painting_path: Path,
) -> float:
    """笔触风格一致性：输出视频帧与原画的颜色直方图余弦相似度。"""
    cap = cv2.VideoCapture(str(output_video))
    if not cap.isOpened():
        return 0.0
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return 0.0

    painting = cv2.imread(str(painting_path))
    if painting is None:
        return 0.0

    hist_out = cv2.calcHist([frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256]).flatten()
    hist_paint = cv2.calcHist([painting], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256]).flatten()
    cos = float(np.dot(hist_out, hist_paint) / (np.linalg.norm(hist_out) * np.linalg.norm(hist_paint) + 1e-8))
    return cos


def eval_edge_alignment(stage3: Stage3Output) -> float:
    """边缘对齐度：各物体重定位后的平均边缘 IoU。"""
    if not stage3.transforms:
        return 0.0
    return float(np.mean([t.edge_iou for t in stage3.transforms]))


def eval_depth_fidelity(stage4: Stage4Output) -> float:
    """深度结构忠实度：关键帧深度图方差。"""
    variances = []
    for kf in stage4.keyframes:
        d = cv2.imread(str(kf.depth_path), cv2.IMREAD_UNCHANGED)
        if d is not None:
            variances.append(float(np.var(d.astype(np.float32) / 65535.0)))
    return float(np.mean(variances)) if variances else 0.0


def run_evaluation(
    painting_path: Path,
    stage3: Stage3Output,
    stage4: Stage4Output,
) -> dict[str, float]:
    """运行全部评估钩子。"""
    metrics = {
        "style_consistency": eval_style_consistency(stage4.final_video_path, painting_path),
        "edge_alignment": eval_edge_alignment(stage3),
        "depth_fidelity": eval_depth_fidelity(stage4),
    }
    logger.info("评估指标: %s", {k: round(v, 4) for k, v in metrics.items()})
    return metrics
