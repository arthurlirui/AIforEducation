"""contour: 从二值掩膜中提取有序封闭边界（Moore 邻域追踪）.

真实纹样素材往往是扫描图/分割掩膜。本模块把掩膜中的每个连通区域
的边界提取成有序点列，供 FourierCurve.from_contour 使用。

约定:
    mask 中前景为 True (或 >0)。像素 (r, c) 的"角点"坐标取
    (c + 0.5, r + 0.5)，即像素中心，使轮廓落在像素中心连线上。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["extract_contours", "resample_contour"]


# 8 邻域，按顺时针排列（从正上开始），用于 Moore 追踪
_NEIGHBORS = [
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
]


def _trace_boundary(mask: np.ndarray, start: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Moore 边界追踪: 从已知边界像素出发走一圈，返回有序边界像素序列。"""
    r0, c0 = start
    n_rows, n_cols = mask.shape
    boundary = [(r0, c0)]

    def is_fg(r: int, c: int) -> bool:
        return 0 <= r < n_rows and 0 <= c < n_cols and bool(mask[r, c])

    if not is_fg(r0, c0):
        raise ValueError("起点不是前景像素")

    # Jacob's stopping criterion: 找到"进入"起点时来自的背景方向
    # 从起点左侧的背景开始顺时针找第一个前景邻居作为第二点
    first_dir = None
    for i, (dr, dc) in enumerate(_NEIGHBORS):
        if is_fg(r0 + dr, c0 + dc):
            first_dir = i
            break
    if first_dir is None:
        # 孤立单像素区域
        return boundary

    prev_dir = first_dir
    cr, cc = r0 + _NEIGHBORS[first_dir][0], c0 + _NEIGHBORS[first_dir][1]
    boundary.append((cr, cc))

    max_steps = 4 * (n_rows + n_cols) * 8  # 防御性上限
    for _ in range(max_steps):
        if (cr, cc) == (r0, c0):
            break
        # 从"来时方向"反向开始顺时针搜索下一格
        back = (prev_dir + 4) % 8
        found = None
        for i in range(8):
            d = (back + 1 + i) % 8
            dr, dc = _NEIGHBORS[d]
            if is_fg(cr + dr, cc + dc):
                found = d
                break
        if found is None:
            break  # 单像素或异常
        prev_dir = found
        cr, cc = cr + _NEIGHBORS[found][0], cc + _NEIGHBORS[found][1]
        boundary.append((cr, cc))
    # 去掉重复的收尾起点
    if len(boundary) > 1 and boundary[0] == boundary[-1]:
        boundary.pop()
    return boundary


def extract_contours(
    mask: Sequence[Sequence[bool]],
    min_area: int = 12,
) -> List[np.ndarray]:
    """提取二值掩膜中所有连通区域的有序边界点列。

    Args:
        mask: 二值掩膜，前景为 True / >0。
        min_area: 小于该像素数的连通区域被忽略（去噪）。

    Returns:
        边界点列列表，每个为 (N, 2) 数组，坐标为像素中心
        (x=c+0.5, y=r+0.5)，顺时针方向。
    """
    m = np.asarray(mask)
    if m.ndim != 2:
        raise ValueError("mask 必须是二维数组")
    bin_mask = m != 0 if m.dtype != bool else m

    # 连通域标记 (4-连通前景, 简单两遍 BFS)
    labels = np.zeros(bin_mask.shape, dtype=np.int32)
    label_id = 0
    contours: List[np.ndarray] = []
    n_rows, n_cols = bin_mask.shape
    visited = np.zeros(bin_mask.shape, dtype=bool)
    for r in range(n_rows):
        for c in range(n_cols):
            if not bin_mask[r, c] or visited[r, c]:
                continue
            # BFS 收集该连通域
            label_id += 1
            stack = [(r, c)]
            visited[r, c] = True
            area = 0
            top_left = (r, c)
            while stack:
                rr, cc = stack.pop()
                area += 1
                labels[rr, cc] = label_id
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = rr + dr, cc + dc
                    if (
                        0 <= nr < n_rows and 0 <= nc < n_cols
                        and bin_mask[nr, nc] and not visited[nr, nc]
                    ):
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            if area < min_area:
                continue
            # 在连通域内找"最上最左"的边界像素作为起点
            # (top_left 已是扫描序第一个像素，它上方必是背景)
            boundary_px = _trace_boundary(bin_mask, top_left)
            if len(boundary_px) < 3:
                continue
            pts = np.array(
                [(c + 0.5, r + 0.5) for (r, c) in boundary_px], dtype=float
            )
            contours.append(pts)
    return contours


def resample_contour(points: np.ndarray, num_samples: int = 256) -> np.ndarray:
    """按弧长把点列重采样为固定数量的均匀分布点。"""
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
        raise ValueError("points 应为 (N,2) 且 N>=3")
    seg = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])  # (N+1,) 末点回到起点
    total = cum[-1]
    if total <= 1e-12:
        raise ValueError("轮廓弧长为零")
    t = np.linspace(0.0, total, num_samples, endpoint=False)
    # xp 有 N+1 个弧长刻度, fp 需补上闭合回起点的坐标
    x = np.interp(t, cum, np.append(pts[:, 0], pts[0, 0]))
    y = np.interp(t, cum, np.append(pts[:, 1], pts[0, 1]))
    return np.column_stack([x, y])
