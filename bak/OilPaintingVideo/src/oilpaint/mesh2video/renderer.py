"""3D 动态白膜渲染器。

将一个（可能带动画的）三角网格在相机序列下渲染为三路图像序列：

* ``clay``   —— 平光白膜灰模，仅表达几何与运动，供 LTXVAddGuide 等结构引导使用。
* ``depth``  —— 线性深度图，供 Wan2.1 depth ControlNet 等几何控制使用。
* ``normal`` —— 视空间法线图，可作为辅助几何信号。

实现策略
--------
为了让框架在 **无 GPU、无 OpenGL 上下文** 的离线环境也能跑，这里采用基于
``trimesh`` 的 *软件光栅化*：每帧把三角面投影到像素，按 z 排序后写入深度缓冲与
着色缓冲。复杂网格（>50k 三角面）会比较慢；如需更高速可换用 pyrender / Blender
或 ComfyUI 内置的 ``RenderMesh`` 节点——本渲染器输出与它们格式完全兼容
（PNG 序列 / MP4），可平滑替换。

所有输出帧统一为 ``uint8 HxWx3`` 的 RGB 图像，深度图按近远线性映射到 0-255。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import logging

import numpy as np

logger = logging.getLogger(__name__)


class RenderPass(str, Enum):
    CLAY = "clay"
    DEPTH = "depth"
    NORMAL = "normal"


@dataclass
class WhiteMeshRenderer:
    """软件白膜渲染器。

    Parameters
    ----------
    width, height : 输出分辨率。
    bg_color : 背景色（RGB 0-255）。
    clay_color : 白膜基色（RGB 0-255），默认浅灰 200。
    """

    width: int = 768
    height: int = 512
    bg_color: tuple[int, int, int] = (15, 15, 15)
    clay_color: tuple[int, int, int] = (200, 200, 200)

    # ------------------------------------------------------------------
    def render(
        self,
        mesh,
        camera,
        passes: tuple[RenderPass, ...] = (RenderPass.CLAY, RenderPass.DEPTH, RenderPass.NORMAL),
    ) -> dict[RenderPass, np.ndarray]:
        """渲染单帧。

        Parameters
        ----------
        mesh : trimesh.Trimesh，世界坐标下的网格（已施加本帧形变）。
        camera : Camera，本帧相机。
        passes : 需要的输出通道。

        Returns
        -------
        dict[RenderPass, np.ndarray]  每路 HxWx3 uint8。
        """
        import trimesh  # 延迟导入，避免无 trimesh 环境加载本模块失败

        if isinstance(mesh, trimesh.Scene):
            mesh = next(iter(mesh.geometry.values()))

        verts = np.asarray(mesh.vertices, dtype=np.float64)  # (V,3)
        faces = np.asarray(mesh.faces, dtype=np.int64)       # (F,3)
        normals = np.asarray(mesh.vertex_normals, dtype=np.float64) if mesh.vertex_normals is not None else None

        # ---- 顶点 → 相机空间 ----
        V = camera.view_matrix()
        P = camera.projection_matrix()
        verts_h = np.hstack([verts, np.ones((verts.shape[0], 1))])  # (V,4)
        verts_cam = (V @ verts_h.T).T[:, :3]                          # (V,3) 相机空间，相机看 -z
        verts_clip = (P @ V @ verts_h.T).T                            # (V,4)
        w = verts_clip[:, 3:4]
        w = np.where(np.abs(w) < 1e-9, 1e-9, w)
        verts_ndc = verts_clip[:, :3] / w                              # (V,3)

        # 屏幕坐标
        sx = (verts_ndc[:, 0] * 0.5 + 0.5) * self.width
        sy = (1.0 - (verts_ndc[:, 1] * 0.5 + 0.5)) * self.height
        depth_cam = -verts_cam[:, 2]                                   # 相机空间 z 取反 → 正值=前方

        H, W = self.height, self.width
        out: dict[RenderPass, np.ndarray] = {}
        # 公共深度缓冲
        depth_buf = np.full((H, W), np.inf, dtype=np.float64)

        # 三角面中心深度，按远→近排序（painter's algorithm，对凸物体近似可用）
        tri_screen = np.stack([sx[faces], sy[faces]], axis=-1)        # (F,3,2)
        tri_depth = depth_cam[faces].mean(axis=1)                     # (F,)
        order = np.argsort(-tri_depth)                                # 远的先画

        # ---- CLAY pass（兰伯特着色 + 深度测试写入）----
        if RenderPass.CLAY in passes:
            img = np.tile(np.array(self.bg_color, dtype=np.float64), (H, W, 1))
            light = np.array([0.3, 0.5, -1.0])
            light /= np.linalg.norm(light)
            base = np.array(self.clay_color, dtype=np.float64)
            for f in order:
                if tri_depth[f] < camera.near:
                    continue
                pts2d = tri_screen[f]
                if np.any(verts_ndc[faces[f], 0] < -1.2) or np.any(verts_ndc[faces[f], 0] > 1.2):
                    pass
                self._raster_triangle(
                    pts2d, depth_buf, tri_depth[f], (W, H)
                )
                # 面法线（相机空间）
                v0, v1, v2 = verts_cam[faces[f]]
                n = np.cross(v1 - v0, v2 - v0)
                nn = np.linalg.norm(n)
                n = n / nn if nn > 1e-9 else np.array([0, 1, 0])
                ndotl = max(0.0, float(n @ light))
                shade = 0.35 + 0.65 * ndotl
                col = base * shade
                self._fill_triangle(img, pts2d, depth_buf, tri_depth[f], col)
            out[RenderPass.CLAY] = np.clip(img, 0, 255).astype(np.uint8)

        # ---- DEPTH pass（深度可视化，近=亮）----
        if RenderPass.DEPTH in passes:
            if not np.isinf(depth_buf).all() and not (RenderPass.CLAY in passes):
                # 单独跑 depth 时需要先填充深度
                for f in order:
                    if tri_depth[f] < camera.near:
                        continue
                    self._raster_triangle(tri_screen[f], depth_buf, tri_depth[f], (W, H))
            d = depth_buf.copy()
            valid = np.isfinite(d)
            if valid.any():
                dmin, dmax = d[valid].min(), d[valid].max()
                if dmax - dmin < 1e-6:
                    dimg = np.zeros_like(d)
                else:
                    dimg = (dmax - d) / (dmax - dmin)  # 近=1
            else:
                dimg = np.zeros_like(d)
            rgb = (np.clip(dimg, 0, 1) * 255).astype(np.uint8)
            out[RenderPass.DEPTH] = np.stack([rgb, rgb, rgb], axis=-1)

        # ---- NORMAL pass（视空间法线 → RGB）----
        if RenderPass.NORMAL in passes:
            img = np.tile(np.array(self.bg_color, dtype=np.float64), (H, W, 1))
            if normals is not None:
                n_cam = (V[:3, :3] @ normals.T).T  # (V,3) 视空间法线
                for f in order:
                    if tri_depth[f] < camera.near:
                        continue
                    pts2d = tri_screen[f]
                    if RenderPass.CLAY not in passes:
                        self._raster_triangle(pts2d, depth_buf, tri_depth[f], (W, H))
                    n = n_cam[faces[f]].mean(axis=0)
                    nn = np.linalg.norm(n)
                    n = n / nn if nn > 1e-9 else np.array([0, 0, 1])
                    col = (n * 0.5 + 0.5) * 255  # -1..1 → 0..1
                    self._fill_triangle(img, pts2d, depth_buf, tri_depth[f], col)
            out[RenderPass.NORMAL] = np.clip(img, 0, 255).astype(np.uint8)

        return out

    # ------------------------------------------------------------------
    def render_sequence(
        self,
        frames: list,
        camera,
        passes: tuple[RenderPass, ...] = (RenderPass.CLAY, RenderPass.DEPTH, RenderPass.NORMAL),
    ) -> dict[RenderPass, np.ndarray]:
        """渲染多帧。

        ``frames[i]`` 是第 i 帧的 mesh（已施加动画形变）；``camera`` 可以是单个
        Camera（静态）或等长的 Camera 列表。
        Returns: dict[pass -> np.ndarray (T,H,W,3) uint8]。
        """
        from .camera import Camera

        n = len(frames)
        cams = camera if isinstance(camera, (list, tuple)) else [camera] * n
        if len(cams) != n:
            raise ValueError(f"相机数 ({len(cams)}) != 帧数 ({n})")
        out: dict[RenderPass, list[np.ndarray]] = {p: [] for p in passes}
        for i, (m, c) in enumerate(zip(frames, cams)):
            r = self.render(m, c, passes=passes)
            for p in passes:
                out[p].append(r[p])
            if (i + 1) % 10 == 0:
                logger.info("渲染进度 %d/%d", i + 1, n)
        return {p: np.stack(v, axis=0) for p, v in out.items()}

    # ------------------------------------------------------------------
    @staticmethod
    def _raster_triangle(pts2d, depth_buf, tri_depth, shape) -> None:
        """把三角形覆盖的像素在 depth_buf 中标记（保留更近的深度）。"""
        W, H = shape
        xs, ys = pts2d[:, 0], pts2d[:, 1]
        x0, x1 = max(0, int(np.floor(xs.min()))), min(W - 1, int(np.ceil(xs.max())))
        y0, y1 = max(0, int(np.floor(ys.min()))), min(H - 1, int(np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            return
        # 重心坐标判断
        v0, v1, v2 = pts2d
        denom = (v1[1] - v2[1]) * (v0[0] - v2[0]) + (v2[0] - v1[0]) * (v0[1] - v2[1])
        if abs(denom) < 1e-9:
            return
        ys_grid, xs_grid = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
        w0 = ((v1[1] - v2[1]) * (xs_grid - v2[0]) + (v2[0] - v1[0]) * (ys_grid - v2[1])) / denom
        w1 = ((v2[1] - v0[1]) * (xs_grid - v2[0]) + (v0[0] - v2[0]) * (ys_grid - v2[1])) / denom
        w2 = 1 - w0 - w1
        mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not mask.any():
            return
        sub = depth_buf[y0 : y1 + 1, x0 : x1 + 1]
        sub[mask & (tri_depth < sub)] = tri_depth

    @staticmethod
    def _fill_triangle(img, pts2d, depth_buf, tri_depth, color) -> None:
        """在 img 中按 depth_buf 写入三角形像素（带深度测试）。"""
        H, W = img.shape[:2]
        xs, ys = pts2d[:, 0], pts2d[:, 1]
        x0, x1 = max(0, int(np.floor(xs.min()))), min(W - 1, int(np.ceil(xs.max())))
        y0, y1 = max(0, int(np.floor(ys.min()))), min(H - 1, int(np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            return
        v0, v1, v2 = pts2d
        denom = (v1[1] - v2[1]) * (v0[0] - v2[0]) + (v2[0] - v1[0]) * (v0[1] - v2[1])
        if abs(denom) < 1e-9:
            return
        ys_grid, xs_grid = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
        w0 = ((v1[1] - v2[1]) * (xs_grid - v2[0]) + (v2[0] - v1[0]) * (ys_grid - v2[1])) / denom
        w1 = ((v2[1] - v0[1]) * (xs_grid - v2[0]) + (v0[0] - v2[0]) * (ys_grid - v2[1])) / denom
        w2 = 1 - w0 - w1
        mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) & (depth_buf[y0 : y1 + 1, x0 : x1 + 1] >= tri_depth - 1e-6)
        if not mask.any():
            return
        img[y0 : y1 + 1, x0 : x1 + 1][mask] = color


# --------------------------------------------------------------------
def save_frames(frames: np.ndarray, out_dir: Path, prefix: str, ext: str = "png") -> list[Path]:
    """把 (T,H,W,3) uint8 序列写到 out_dir/{prefix}_%05d.{ext}。"""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, f in enumerate(frames):
        p = out_dir / f"{prefix}_{i:05d}.{ext}"
        Image.fromarray(f).save(p)
        paths.append(p)
    return paths
