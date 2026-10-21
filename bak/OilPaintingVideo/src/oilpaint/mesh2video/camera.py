"""针孔相机模型与轨迹生成。

只实现渲染白膜所需的最小子集：相机内参、look-at 视图矩阵、绕目标环绕轨迹。
保持依赖最小（仅 numpy），以便在无 PyTorch / 无 GPU 的环境也能离线渲染。
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class Camera:
    """针孔相机。

    参数采用像素单位，方便直接渲染到指定分辨率的图像。
    """

    width: int
    height: int
    f_x: float            # 水平焦距（像素）
    f_y: float            # 垂直焦距（像素）
    c_x: float            # 主点 x（像素）
    c_y: float            # 主点 y（像素）
    near: float = 0.05    # 近裁剪面（米）
    far: float = 100.0    # 远裁剪面（米）

    # 外参（世界 → 相机）
    eye: np.ndarray = None      # 相机位置 (3,)
    target: np.ndarray = None   # 注视点 (3,)
    up: np.ndarray = None       # 上方向 (3,)

    def __post_init__(self) -> None:
        if self.eye is None:
            self.eye = np.array([0.0, 0.0, 3.0])
        if self.target is None:
            self.target = np.array([0.0, 0.0, 0.0])
        if self.up is None:
            self.up = np.array([0.0, 1.0, 0.0])
        self.eye = np.asarray(self.eye, dtype=np.float64)
        self.target = np.asarray(self.target, dtype=np.float64)
        self.up = np.asarray(self.up, dtype=np.float64)

    # ------------------------------------------------------------------
    @classmethod
    def from_fov(
        cls,
        width: int,
        height: int,
        fov_y_deg: float = 50.0,
        near: float = 0.05,
        far: float = 100.0,
        *,
        eye=None,
        target=None,
        up=None,
    ) -> "Camera":
        """由垂直视场角构造（水平 FOV 由宽高比自动决定）。

        可选的 ``eye``/``target``/``up`` 直接作为外参传入，避免调用方
        再做一次 ``__post_init__`` 覆盖。
        """
        f_y = 0.5 * height / np.tan(np.radians(fov_y_deg) / 2.0)
        f_x = f_y  # 方形像素
        return cls(
            width=width,
            height=height,
            f_x=f_x,
            f_y=f_y,
            c_x=width / 2.0,
            c_y=height / 2.0,
            near=near,
            far=far,
            eye=eye if eye is not None else np.array([0.0, 0.0, 3.0]),
            target=target if target is not None else np.array([0.0, 0.0, 0.0]),
            up=up if up is not None else np.array([0.0, 1.0, 0.0]),
        )

    # ------------------------------------------------------------------
    def view_matrix(self) -> np.ndarray:
        """4x4 世界→相机 矩阵（OpenGL 风格，相机看向 -z）。"""
        forward = self.target - self.eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, self.up)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)

        R = np.eye(4)
        R[0, :3] = right
        R[1, :3] = up
        R[2, :3] = -forward
        T = np.eye(4)
        T[:3, 3] = -self.eye
        return R @ T

    def projection_matrix(self) -> np.ndarray:
        """4x4 透视投影矩阵（OpenGL 风格，NDC z∈[-1,1]）。"""
        f, n = self.far, self.near
        return np.array(
            [
                [2 * self.f_x / self.width, 0, 1 - 2 * self.c_x / self.width, 0],
                [0, 2 * self.f_y / self.height, 2 * self.c_y / self.height - 1, 0],
                [0, 0, -(f + n) / (f - n), -2 * f * n / (f - n)],
                [0, 0, -1, 0],
            ],
            dtype=np.float64,
        )


def orbit_camera(
    target: np.ndarray,
    radius: float,
    num_frames: int,
    *,
    height_offset: float = 0.5,
    num_turns: float = 1.0,
    fov_y_deg: float = 50.0,
    width: int = 768,
    height: int = 512,
    tilt_deg: float = 15.0,
) -> list[Camera]:
    """生成一组绕 target 环绕的相机序列。

    Parameters
    ----------
    target : 环绕中心（世界坐标）。
    radius : 相机到中心的距离。
    num_frames : 帧数。
    num_turns : 总共绕几圈。
    tilt_deg : 相机俯仰角（>0 俯视）。
    """
    target = np.asarray(target, dtype=np.float64)
    tilt = np.radians(tilt_deg)
    cams: list[Camera] = []
    for i in range(num_frames):
        t = i / max(1, num_frames - 1)
        theta = 2 * np.pi * num_turns * t
        eye = target + radius * np.array(
            [
                np.cos(tilt) * np.cos(theta),
                np.sin(tilt) + height_offset,
                np.cos(tilt) * np.sin(theta),
            ]
        )
        cams.append(
            Camera.from_fov(width, height, fov_y_deg, eye=eye, target=target)
        )
    return cams
