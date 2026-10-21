"""grid.py — O(1) 近邻最小距离查询.

固定 cell = min_dist 的网格哈希, 替代 ``scipy.spatial.cKDTree``.
本机 scipy 1.x 与 numpy 2.x 二进制不兼容, 纯 numpy 路径必须使用本类.

典型用法::

    grid = GridHash(min_dist_px)
    for x, y in candidates:
        if grid.far_enough(x, y, min_dist_px):
            grid.add(x, y)
"""

from __future__ import annotations


class GridHash:
    """固定 cell 大小的网格哈希, 用于 O(1) 近邻最小距离约束."""

    def __init__(self, cell: float) -> None:
        self.cell = max(cell, 1e-3)
        self.buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return int(x // self.cell), int(y // self.cell)

    def far_enough(self, x: float, y: float, r: float) -> bool:
        """查询 (x,y) 是否与已加入点的距离都 ≥ r."""
        cx, cy = self._key(x, y)
        r2 = r * r
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py in self.buckets.get((cx + dx, cy + dy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r2:
                        return False
        return True

    def add(self, x: float, y: float) -> None:
        """加入一个新点到网格."""
        self.buckets.setdefault(self._key(x, y), []).append((x, y))

    def __len__(self) -> int:
        return sum(len(b) for b in self.buckets.values())
