"""test_grid.py — ops/grid.py GridHash 直接单元测试.

G1 回归: far_enough 的查询半径可大于 cell (调用方 stipple_pure 最大
1.5×cell, learned 最大约 3.6×cell), 搜索环必须按 ceil(r/cell) 扩展,
否则最小间距约束在稀疏区被系统性漏检.
"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotartkit.ops.grid import GridHash  # noqa: E402


class TestFarEnough:
    def test_r_equal_cell(self):
        """r = cell: 基础 3×3 场景 (修复前也正确)."""
        g = GridHash(10.0)
        g.add(5.0, 5.0)
        assert not g.far_enough(14.0, 5.0, 10.0)   # 距离 9 < 10
        assert g.far_enough(15.0, 5.0, 10.0)       # 距离 10 ≥ 10

    def test_r_above_cell_neighbor_bucket(self):
        """r = 1.5×cell, 违反点在相邻桶 (修复前 3×3 可查到的场景)."""
        g = GridHash(10.0)
        g.add(9.9, 5.0)             # 桶 (0, 0)
        assert not g.far_enough(11.0, 5.0, 15.0)   # 距离 1.1 < 15

    def test_r_above_cell_two_buckets_away(self):
        """r = 2.5×cell, 违反点在 2 桶之外 (修复前 3×3 漏检的场景)."""
        g = GridHash(10.0)
        g.add(5.0, 5.0)             # 桶 (0, 0)
        # 查询点 24.0 在桶 (2, 0), 违反点在桶 (0, 0) — 相距 2 桶
        assert not g.far_enough(24.0, 5.0, 25.0), \
            "G1 回归: r > cell 时 3×3 邻域漏检 2 桶外的违反点"

    def test_far_point_accepted(self):
        """足够远的点必须被接受 (扩展搜索环不产生误拒)."""
        g = GridHash(10.0)
        g.add(5.0, 5.0)
        assert g.far_enough(100.0, 100.0, 25.0)

    def test_adversarial_dense_insert(self):
        """对抗性: 密集随机插入后, 任意两点距 ≥ r (G1 建议的测法).

        cell 固定, 查询半径按 learned.py 的密度自适应式取
        local_min = cell + r_here*0.6 (最大 3.6×cell), 全程满足约束.
        """
        rng = np.random.default_rng(42)
        cell = 5.0
        g = GridHash(cell)
        pts = []
        for _ in range(400):
            for _try in range(200):
                x, y = rng.uniform(0, 200), rng.uniform(0, 200)
                # 半径与 learned.py 同式: 查询半径随局部半径增大
                r_here = rng.uniform(1.0, 10.0)
                local_min = cell + r_here * 0.6
                if g.far_enough(x, y, local_min):
                    g.add(x, y)
                    pts.append((x, y, local_min))
                    break
        assert len(pts) > 20, "对抗性测试应插入足够多的点"
        # 全量两两校验: 每个点与所有先插入点的距离 ≥ 其 local_min
        arr = np.array(pts)
        for i in range(len(arr)):
            if i == 0:
                continue
            d = np.linalg.norm(arr[:i, :2] - arr[i, :2], axis=1)
            # local_min 是插入时的约束; 双向取 min 更严格:
            # 两点间距需 ≥ min(两者 local_min) — far_enough 只保证
            # 后插入者对先插入者的距离约束, 取两边约束的较小值校验.
            bound = np.minimum(arr[:i, 2], arr[i, 2])
            assert (d >= bound - 1e-9).all(), \
                f"点 {i} 与先插入点距离违反 min-dist 约束 (G1)"

    def test_len(self):
        g = GridHash(3.0)
        assert len(g) == 0
        g.add(1.0, 1.0)
        g.add(1.5, 1.5)     # 同桶
        g.add(10.0, 10.0)
        assert len(g) == 3
