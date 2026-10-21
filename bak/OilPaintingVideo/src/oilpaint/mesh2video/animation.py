"""动画驱动接口。

把"时间 t → 一帧 mesh"这件事抽象成统一接口，方便对接不同来源的动画：

* ``StaticDriver``        —— 不形变，只让相机绕静态网格运动（最简单的"动态白膜"）。
* ``MorphDriver``         —— 在多个关键 mesh 之间线性插值形变（顶点数需一致）。
* ``CallableDriver``      —— 用户传入 ``t -> trimesh.Trimesh`` 回调，自定义形变。

更复杂的骨骼动画（Mixamo / FBX rig）建议先用 Blender 烘焙成顶点序列再喂给
``MorphDriver``，以避免在 Python 里重实现骨骼蒙皮。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import numpy as np


@dataclass
class AnimationDriver:
    """动画驱动基类。子类实现 :meth:`frame`。"""

    num_frames: int = 49

    def frame(self, t: int) -> "trimesh.Trimesh":  # noqa: F821
        raise NotImplementedError

    def frames(self) -> list:
        return [self.frame(t) for t in range(self.num_frames)]


@dataclass
class StaticDriver(AnimationDriver):
    """静态网格 + 相机运动。最简单的动态白膜。"""

    mesh: object = None  # trimesh.Trimesh

    def frame(self, t: int):
        return self.mesh


@dataclass
class MorphDriver(AnimationDriver):
    """在关键帧 mesh 间线性插值（顶点数需一致）。

    Parameters
    ----------
    key_meshes : list[trimesh.Trimesh]，顶点数必须相同；faces 取第一个的。
    key_times : 对应关键帧时间索引（升序，0..num_frames-1），默认均匀分布。
    """

    key_meshes: list = field(default_factory=list)
    key_times: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.key_meshes:
            raise ValueError("key_meshes 不能为空")
        n = len(self.key_meshes)
        if not self.key_times:
            self.key_times = [round(i * (self.num_frames - 1) / max(1, n - 1)) for i in range(n)]
        if len(self.key_times) != n:
            raise ValueError("key_times 长度需与 key_meshes 一致")
        v0 = np.asarray(self.key_meshes[0].vertices).shape
        for km in self.key_meshes[1:]:
            if np.asarray(km.vertices).shape != v0:
                raise ValueError("所有关键 mesh 顶点数需一致")
        self._key_verts = [np.asarray(km.vertices, dtype=np.float64) for km in self.key_meshes]
        self._faces = np.asarray(self.key_meshes[0].faces, dtype=np.int64)

    def frame(self, t: int):
        import trimesh

        if t <= self.key_times[0]:
            verts = self._key_verts[0]
        elif t >= self.key_times[-1]:
            verts = self._key_verts[-1]
        else:
            for i in range(len(self.key_times) - 1):
                t0, t1 = self.key_times[i], self.key_times[i + 1]
                if t0 <= t <= t1:
                    a = (t - t0) / max(1e-9, (t1 - t0))
                    verts = (1 - a) * self._key_verts[i] + a * self._key_verts[i + 1]
                    break
        return trimesh.Trimesh(vertices=verts, faces=self._faces, process=False)


@dataclass
class CallableDriver(AnimationDriver):
    """自定义回调驱动。

    Parameters
    ----------
    fn : ``int t -> trimesh.Trimesh``，返回第 t 帧的 mesh（世界坐标）。
    """

    fn: Callable[[int], object] = None

    def frame(self, t: int):
        if self.fn is None:
            raise ValueError("未提供动画回调 fn")
        return self.fn(t)
