"""kusama_basic.py — 草间弥生风格波点 (基础版, 无深度感知).

基于 Secord Weighted Voronoi Stippling, 通过亮度密度调制点大小,
再加 Kusama 签名笔法:

- 高饱和双色板 (黑/红, 黄/黑, 白/红, 红/白, 品红/黑, 黄/红)
- horror vacui 背景全面覆盖
- 多尺度点 (主层 + 反密度装饰层)
- Canny 边缘增强
- 硬边实心圆 (无 AA, 风格正确且防止桥接)

**与 :mod:`kusama_depth` 的区别**: 本模块仅用亮度密度, 不引入 YOLO26
深度/语义; 适合无 GPU / 快速预览.
"""

from __future__ import annotations

import os
import numpy as np
import cv2
from PIL import Image

from ..ops.color import KUSAMA_PALETTES
from ..ops.voronoi import compute_density, stipple, has_scipy


# ---------------------------------------------------------------------------
# 边缘增强
# ---------------------------------------------------------------------------

def canny_edges(gray: np.ndarray, low: int = 80, high: int = 160) -> np.ndarray:
    """Canny 边缘检测, 返回二值边缘掩码 (255 = 边缘)."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    return cv2.Canny(blurred, low, high)


def edge_points(edges: np.ndarray, step: int = 4, jitter: float = 1.5,
                rng: np.random.Generator | None = None,
                r: float = 1.2) -> tuple[np.ndarray, np.ndarray]:
    """沿 Canny 边缘采样小点."""
    if rng is None:
        rng = np.random.default_rng()
    ys, xs = np.where(edges > 0)
    if len(xs) == 0:
        return np.empty((0, 2)), np.empty((0,))
    xs = xs[::step].astype(np.float64)
    ys = ys[::step].astype(np.float64)
    if jitter > 0:
        xs += rng.normal(0, jitter, xs.shape)
        ys += rng.normal(0, jitter, ys.shape)
    pts = np.column_stack([xs, ys])
    radii = np.full(len(pts), r, dtype=np.float64)
    return pts, radii


# ---------------------------------------------------------------------------
# Horror vacui 背景填充
# ---------------------------------------------------------------------------

def background_fill_points(W: int, H: int, spacing: float = 18.0,
                           r: float = 1.0, jitter: float = 3.0,
                           seed: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """稀疏抖动网格小点, 填充空白背景 (horror vacui)."""
    rng = np.random.default_rng(seed)
    xs = np.arange(spacing / 2, W, spacing)
    ys = np.arange(spacing / 2, H, spacing)
    gx, gy = np.meshgrid(xs, ys)
    pts = np.column_stack([gx.ravel(), gy.ravel()]).astype(np.float64)
    if jitter > 0:
        pts += rng.normal(0, jitter, pts.shape)
    radii = np.full(len(pts), r, dtype=np.float64) * rng.uniform(0.7, 1.3, len(pts))
    return pts, radii


# ---------------------------------------------------------------------------
# 硬边圆点绘制 (cv2)
# ---------------------------------------------------------------------------

def draw_dots_cv2(canvas: np.ndarray, points: np.ndarray, radii: np.ndarray,
                  color_bgr: tuple[int, int, int]) -> None:
    """硬边实心圆 (无 AA, 风格正确且防止相邻点桥接). 就地修改 canvas."""
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        if rr < 1:
            if 0 <= xi < canvas.shape[1] and 0 <= yi < canvas.shape[0]:
                canvas[yi, xi] = color_bgr
        else:
            cv2.circle(canvas, (xi, yi), rr, color_bgr, -1, lineType=cv2.LINE_4)


# ---------------------------------------------------------------------------
# 完整草间基础版 pipeline
# ---------------------------------------------------------------------------

def _imread_bgr(path: str) -> np.ndarray:
    """读图像为 BGR ndarray. cv2 失败 (如 16bit png) 时回退 PIL."""
    img = cv2.imread(path)
    if img is None:
        pil = Image.open(path).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


def kusama_polka_core(img: np.ndarray,
                      palette: str = "black_red",
                      n_points: int = 20000,
                      n_iter: int = 10,
                      r_min: float = 1.0, r_max: float = 5.0,
                      gamma: float = 1.2,
                      size_jitter: float = 0.15,
                      pos_jitter: float = 0.3,
                      min_dist: float = 0.0,
                      overlap_gap: float = 2.0,
                      edge_step: int = 4, edge_r: float = 1.3,
                      bg_spacing: float = 20.0, bg_r: float = 1.0,
                      multi_scale: bool = True,
                      target_long_edge: int = 1024,
                      seed: int = 42) -> np.ndarray:
    """渲染草间弥生风格波点 (核心管线, ndarray 进出, 零磁盘 I/O).

    Parameters
    ----------
    img : 输入图像, BGR uint8 ndarray
    palette : :data:`~dotartkit.ops.color.KUSAMA_PALETTES` 键
    multi_scale : True 加第二层反密度装饰点
    target_long_edge : 大图下采样到此长边 (Voronoi 计算量正比点数)

    Returns
    -------
    canvas : BGR uint8 ndarray (与缩放后的输入同尺寸)
    """
    rng = np.random.default_rng(seed)

    H0, W0 = img.shape[:2]
    scale = target_long_edge / max(H0, W0)
    if scale < 1.0:
        img = cv2.resize(img, (int(W0 * scale), int(H0 * scale)),
                         interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    density = compute_density(gray, gamma=gamma, invert=True)
    bg_color, dot_color = KUSAMA_PALETTES[palette]

    pts1, rad1 = stipple(density, n_points=n_points, n_iter=n_iter,
                         r_min=r_min, r_max=r_max,
                         size_jitter=size_jitter, pos_jitter=pos_jitter,
                         min_dist=min_dist, overlap_gap=overlap_gap,
                         seed=seed)
    all_pts = [pts1]
    all_rads = [rad1]

    if multi_scale:
        n2 = max(n_points // 5, 600)
        inv_density = 1.0 - density
        pts2, rad2 = stipple(inv_density, n_points=n2, n_iter=n_iter,
                             r_min=r_max * 0.8, r_max=r_max * 1.5,
                             size_jitter=size_jitter, pos_jitter=pos_jitter,
                             min_dist=min_dist, overlap_gap=overlap_gap * 1.2,
                             seed=seed + 1)
        all_pts.append(pts2)
        all_rads.append(rad2)

    edges = canny_edges(gray)
    epts, erad = edge_points(edges, step=edge_step, jitter=1.2, rng=rng, r=edge_r)
    if len(epts):
        all_pts.append(epts)
        all_rads.append(erad)

    bg_pts, bg_rads = background_fill_points(W, H, spacing=bg_spacing,
                                              r=bg_r, jitter=3.0, seed=seed + 2)
    bxi = np.clip(bg_pts[:, 0].astype(int), 0, W - 1)
    byi = np.clip(bg_pts[:, 1].astype(int), 0, H - 1)
    bg_keep = density[byi, bxi] < 0.25
    if bg_keep.any():
        all_pts.append(bg_pts[bg_keep])
        all_rads.append(bg_rads[bg_keep])

    canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)
    # 绘制顺序: bg → main → multi → edge
    draw_order = [3, 0, 1, 2]
    for idx in draw_order:
        if idx < len(all_pts) and len(all_pts[idx]):
            draw_dots_cv2(canvas, all_pts[idx], all_rads[idx], dot_color)
    return canvas


def kusama_polka(input_path: str, output_path: str,
                 palette: str = "black_red",
                 n_points: int = 20000,
                 n_iter: int = 10,
                 r_min: float = 1.0, r_max: float = 5.0,
                 gamma: float = 1.2,
                 size_jitter: float = 0.15,
                 pos_jitter: float = 0.3,
                 min_dist: float = 0.0,
                 overlap_gap: float = 2.0,
                 edge_step: int = 4, edge_r: float = 1.3,
                 bg_spacing: float = 20.0, bg_r: float = 1.0,
                 multi_scale: bool = True,
                 target_long_edge: int = 1024,
                 seed: int = 42) -> np.ndarray:
    """路径入口 (薄包装): 读文件 → :func:`kusama_polka_core` → 写 PNG.

    保留供按路径调用的脚本使用; PIL 路径请走 :func:`generate_kusama_basic`
    (直接走 ndarray 核心, 无临时文件).

    Returns
    -------
    canvas : BGR uint8 ndarray (与写出的 PNG 一致)
    """
    img = _imread_bgr(input_path)
    canvas = kusama_polka_core(
        img, palette=palette, n_points=n_points, n_iter=n_iter,
        r_min=r_min, r_max=r_max, gamma=gamma,
        size_jitter=size_jitter, pos_jitter=pos_jitter,
        min_dist=min_dist, overlap_gap=overlap_gap,
        edge_step=edge_step, edge_r=edge_r,
        bg_spacing=bg_spacing, bg_r=bg_r,
        multi_scale=multi_scale, target_long_edge=target_long_edge,
        seed=seed)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    H, W = canvas.shape[:2]
    print(f"Saved: {output_path}  ({W}x{H}, palette={palette})")
    return canvas


# ---------------------------------------------------------------------------
# PIL 接口 (供 api.generate 统一调用)
# ---------------------------------------------------------------------------

def generate_kusama_basic(
    image: Image.Image,
    palette: str = "black_red",
    n_points: int = 20000,
    n_iter: int = 10,
    r_min: float = 1.0,
    r_max: float = 5.0,
    gamma: float = 1.2,
    overlap_gap: float = 2.0,
    multi_scale: bool = True,
    target_long_edge: int = 1024,
    seed: int = 42,
    **kwargs,
) -> Image.Image:
    """PIL 接口的草间基础版生成.

    直接走 ndarray 核心 (PIL → BGR → :func:`kusama_polka_core` → RGB),
    无临时文件 / 磁盘 I/O.
    """
    img = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    canvas = kusama_polka_core(
        img, palette=palette, n_points=n_points, n_iter=n_iter,
        r_min=r_min, r_max=r_max, gamma=gamma,
        overlap_gap=overlap_gap, multi_scale=multi_scale,
        target_long_edge=target_long_edge, seed=seed)
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
