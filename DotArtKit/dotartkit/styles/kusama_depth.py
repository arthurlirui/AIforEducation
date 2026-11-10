"""kusama_depth.py — 草间弥生风格波点 (深度感知版, YOLO26 + 三层架构).

整合 YOLO26 单目深度估计与语义分割, 用场景深度调制波点大小
(近=大点, 远=小点), 实现三维深度感知的草间风格波点艺术.

**核心数学**::

    r(x,y) = r_min + (r_max - r_min) · (1 - d̂)^α · (1 + ε),  ε ~ N(0, σ²)
    ρ(x,y) = (1 - d̂)^β · γ(I_gray)

**三层架构**:

1. Fine stipple (r=1-5px): 密集小点, 深度调制密度, 基础纹理
2. Depth-emphasis (r=5-r_max): 仅近景大点, 承载深度信号
3. Edge + Background: Canny 边缘 + horror vacui 填充

跨层重叠剪枝防止大点与细点粘连成块.

**可选依赖**: ``ultralytics`` (YOLO26), GPU 推荐. 无 ultralytics 时
``generate_kusama_depth`` 会抛 ImportError.
"""

from __future__ import annotations

import os
import time
import numpy as np
import cv2
from PIL import Image

from ..ops.depth import (
    DepthEstimator,
    SemanticSegmentor,
    DEPTH_PALETTES,
    normalize_depth,
    normalize_depth_foreground,
    depth_to_density,
    depth_aware_stipple,
    get_foreground_mask,
    has_ultralytics,
)

# 模块级模型缓存: (model_path, device) → 已加载模型, 避免 api.generate
# 路径每次调用都从磁盘重载 (与 polka_document.ensure_depth 行为一致).
_MODEL_CACHE: dict = {}


def _get_model(kind: str, model_path: str, device: str):
    """按 (kind, path, device) 缓存 DepthEstimator / SemanticSegmentor."""
    key = (kind, model_path, device)
    if key not in _MODEL_CACHE:
        cls = DepthEstimator if kind == "depth" else SemanticSegmentor
        _MODEL_CACHE[key] = cls(model_path, device=device)
    return _MODEL_CACHE[key]


# ---------------------------------------------------------------------------
# 渲染辅助
# ---------------------------------------------------------------------------

def draw_dots_dualcolor(canvas: np.ndarray,
                         points: np.ndarray,
                         radii: np.ndarray,
                         fg_mask: np.ndarray,
                         fg_color: tuple,
                         bg_color: tuple) -> None:
    """语义感知双色绘制: 前景点用 fg_color, 背景点用 bg_color. 就地修改."""
    H, W = fg_mask.shape
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        if 0 <= xi < W and 0 <= yi < H:
            color = fg_color if fg_mask[yi, xi] else bg_color
        else:
            color = bg_color
        if rr < 1:
            if 0 <= xi < W and 0 <= yi < H:
                canvas[yi, xi] = color
        else:
            cv2.circle(canvas, (xi, yi), rr, color, -1, lineType=cv2.LINE_4)


def draw_dots_singlecolor(canvas: np.ndarray,
                           points: np.ndarray,
                           radii: np.ndarray,
                           color: tuple) -> None:
    """单色绘制 (背景填充 / 边缘). 就地修改."""
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        if rr < 1:
            if 0 <= xi < canvas.shape[1] and 0 <= yi < canvas.shape[0]:
                canvas[yi, xi] = color
        else:
            cv2.circle(canvas, (xi, yi), rr, color, -1, lineType=cv2.LINE_4)


def _save_intermediates(output_dir: str, d_norm: np.ndarray,
                        seg: np.ndarray, density: np.ndarray, fg_mask: np.ndarray,
                        W: int, H: int) -> None:
    """保存中间可视化 (归一化深度 / 分割图 / 密度场 / 前景掩码)."""
    inter_dir = os.path.join(output_dir, "intermediates")
    os.makedirs(inter_dir, exist_ok=True)

    depth_vis = cv2.applyColorMap((d_norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    cv2.imwrite(os.path.join(inter_dir, "depth_normalized.png"), depth_vis)

    seg_vis = np.zeros((H, W, 3), dtype=np.uint8)
    colors = np.random.default_rng(42).integers(50, 255, (20, 3))
    for cls_id in np.unique(seg):
        # 取模防越界: 分割模型类别数超过调色板时循环复用颜色
        seg_vis[seg == cls_id] = colors[cls_id % len(colors)]
    cv2.imwrite(os.path.join(inter_dir, "semantic_seg.png"), seg_vis)

    density_vis = cv2.applyColorMap((density * 255).astype(np.uint8), cv2.COLORMAP_VIRIDIS)
    cv2.imwrite(os.path.join(inter_dir, "density_field.png"), density_vis)

    fg_vis = np.zeros((H, W, 3), dtype=np.uint8)
    fg_vis[fg_mask > 0] = (0, 255, 0)
    cv2.imwrite(os.path.join(inter_dir, "foreground_mask.png"), fg_vis)


# ---------------------------------------------------------------------------
# 跨层重叠剪枝 (纯 numpy, 可独立单测)
# ---------------------------------------------------------------------------

def prune_fine_against_large(pts_fine: np.ndarray,
                             rad_fine: np.ndarray,
                             pts_large: np.ndarray,
                             rad_large: np.ndarray,
                             gap: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """跨层剪枝: 移除落入大点范围内的细点. 返回 (pts_fine, rad_fine) 保留子集.

    细点 i 被移除, 当存在大点 j 使 ``|p_i - q_j| < r_i + R_j + gap``.
    纯 numpy 向量化 (大点仅数十至数百个, 广播一次即完成), 无
    scipy / ultralytics 依赖, 可直接单测.
    """
    if len(pts_fine) == 0 or len(pts_large) == 0:
        return pts_fine, rad_fine
    # (n_fine, n_large) 距离矩阵; n_large 通常 < n_points/6
    d = np.linalg.norm(pts_fine[:, None, :] - pts_large[None, :, :], axis=2)
    overlap = d < rad_fine[:, None] + rad_large[None, :] + gap
    keep = ~overlap.any(axis=1)
    return pts_fine[keep], rad_fine[keep]


# ---------------------------------------------------------------------------
# 完整深度感知 pipeline
# ---------------------------------------------------------------------------

def _imread_bgr(path: str) -> np.ndarray:
    """读图像为 BGR ndarray. cv2 失败 (如 16bit png) 时回退 PIL."""
    img = cv2.imread(path)
    if img is None:
        pil = Image.open(path).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


def depth_kusama_polka_core(img: np.ndarray,
                            palette: str = "black_red",
                            depth_model_path: str = "models/yolo26x-depth.pt",
                            sem_model_path: str = "models/yolo26x-sem.pt",
                            device: str = "0",
                            n_points: int = 20000,
                            n_iter: int = 8,
                            r_min: float = 1.0,
                            r_max: float = 18.0,
                            alpha: float = 1.5,
                            beta: float = 0.6,
                            sigma: float = 0.15,
                            gamma: float = 1.2,
                            pos_jitter: float = 0.3,
                            overlap_gap: float = 2.5,
                            percentile_clip: float = 2.0,
                            multi_scale: bool = True,
                            edge_enhance: bool = True,
                            bg_fill: bool = True,
                            bg_spacing: float = 20.0,
                            semantic_aware: bool = True,
                            target_long_edge: int = 1024,
                            seed: int = 42,
                            save_intermediates: bool = False,
                            intermediates_dir: str | None = None
                            ) -> tuple[np.ndarray, dict]:
    """渲染深度感知草间弥生波点 (核心管线, ndarray 进出).

    Parameters
    ----------
    img : 输入图像, BGR uint8 ndarray
    palette : :data:`~dotartkit.ops.depth.DEPTH_PALETTES` 键
    alpha : 深度→半径衰减指数 (>1 强深度强调)
    beta : 深度→密度指数 (<1 远景仍有点)
    sigma : 半径高斯噪声标准差 (有机变化)
    semantic_aware : True 前景/背景用不同点色
    save_intermediates : 额外保存深度图/分割图/密度场可视化到
        ``intermediates_dir`` (可选调试输出, 与主图渲染路径无关)

    Returns
    -------
    (canvas, stats) : canvas 为 BGR uint8 ndarray;
        stats 含点数 / 深度范围 / 耗时 (无 ``output`` 键, 由路径包装补充).
    """
    t_start = time.time()
    rng = np.random.default_rng(seed)

    H0, W0 = img.shape[:2]
    scale = target_long_edge / max(H0, W0)
    if scale < 1.0:
        img = cv2.resize(img, (int(W0 * scale), int(H0 * scale)),
                         interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Stage 1: 深度估计
    t0 = time.time()
    depth_estimator = _get_model("depth", depth_model_path, device)
    depth = depth_estimator.predict(img)
    t_depth = time.time() - t0

    # Stage 2: 语义分割
    t0 = time.time()
    segmentor = _get_model("sem", sem_model_path, device)
    seg = segmentor.predict(img)
    fg_mask = get_foreground_mask(seg) if semantic_aware else np.ones((H, W), dtype=np.uint8)
    t_seg = time.time() - t0

    # Stage 2b: 前景感知深度归一化
    if semantic_aware and fg_mask.mean() > 0.005:
        d_norm = normalize_depth_foreground(depth, fg_mask, percentile_clip=percentile_clip)
    else:
        d_norm = normalize_depth(depth, percentile_clip=percentile_clip)

    # Stage 3: 复合密度场
    density = depth_to_density(d_norm, gray, gamma=gamma, beta=beta)

    t0 = time.time()

    # Layer 1: Fine stipple (小点, 深度调制密度)
    fine_r_max = min(5.0, r_max * 0.35)
    pts_fine, rad_fine = depth_aware_stipple(
        density, d_norm,
        n_points=n_points, n_iter=n_iter,
        r_min=r_min, r_max=fine_r_max,
        alpha=alpha * 0.6, sigma=sigma,
        pos_jitter=pos_jitter, overlap_gap=1.0, seed=seed)

    # Layer 2: Depth-emphasis (大点, 仅近景)
    depth_emphasis_pts = np.empty((0, 2))
    depth_emphasis_rads = np.empty((0,))
    if multi_scale:
        near_threshold = 0.55
        near_mask = ((d_norm < near_threshold) & (fg_mask > 0)).astype(np.float32)
        near_density = near_mask * density
        nd_max = near_density.max()
        if nd_max > 1e-9:
            near_density /= nd_max
            n_large = max(n_points // 6, 400)
            pts_large, rad_large = depth_aware_stipple(
                near_density, d_norm,
                n_points=n_large, n_iter=max(n_iter - 2, 4),
                r_min=fine_r_max * 1.5, r_max=r_max,
                alpha=alpha, sigma=sigma,
                pos_jitter=pos_jitter, overlap_gap=overlap_gap, seed=seed + 1)

            # 跨层剪枝: 移除落入大点范围内的细点
            if len(pts_large) > 0 and len(pts_fine) > 0:
                pts_fine, rad_fine = prune_fine_against_large(
                    pts_fine, rad_fine, pts_large, rad_large, gap=1.0)

            depth_emphasis_pts = pts_large
            depth_emphasis_rads = rad_large

    # Layer 3: 边缘增强
    edge_pts = np.empty((0, 2))
    edge_rads = np.empty((0,))
    if edge_enhance:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 80, 160)
        ys, xs = np.where(edges > 0)
        if len(xs) > 0:
            step = 4
            xs = xs[::step].astype(np.float64)
            ys = ys[::step].astype(np.float64)
            xs += rng.normal(0, 1.2, xs.shape)
            ys += rng.normal(0, 1.2, ys.shape)
            edge_pts = np.column_stack([xs, ys])
            edge_rads = np.full(len(edge_pts), 1.3, dtype=np.float64)

    # Layer 4: Horror vacui 背景填充
    bg_pts = np.empty((0, 2))
    bg_rads = np.empty((0,))
    if bg_fill:
        bxs = np.arange(bg_spacing / 2, W, bg_spacing)
        bys = np.arange(bg_spacing / 2, H, bg_spacing)
        bgx, bgy = np.meshgrid(bxs, bys)
        bgp = np.column_stack([bgx.ravel(), bgy.ravel()]).astype(np.float64)
        bgp += rng.normal(0, 3.0, bgp.shape)
        bgr = np.full(len(bgp), 1.0, dtype=np.float64) * rng.uniform(0.7, 1.3, len(bgp))
        bxi = np.clip(bgp[:, 0].astype(int), 0, W - 1)
        byi = np.clip(bgp[:, 1].astype(int), 0, H - 1)
        bg_keep = density[byi, bxi] < 0.25
        if bg_keep.any():
            bg_pts = bgp[bg_keep]
            bg_rads = bgr[bg_keep]

    t_stipple = time.time() - t0

    # Stage 5: 合并 + 渲染
    pal = DEPTH_PALETTES[palette]
    bg_color = pal["bg"]
    fg_dot_color = pal["fg_dot"]
    bg_dot_color = pal["bg_dot"]

    canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)
    # 绘制顺序: bg → fine → edge → depth-emphasis (最上层)
    if len(bg_pts):
        draw_dots_singlecolor(canvas, bg_pts, bg_rads, bg_dot_color)
    if len(pts_fine):
        if semantic_aware:
            draw_dots_dualcolor(canvas, pts_fine, rad_fine, fg_mask, fg_dot_color, bg_dot_color)
        else:
            draw_dots_singlecolor(canvas, pts_fine, rad_fine, fg_dot_color)
    if len(edge_pts):
        draw_dots_singlecolor(canvas, edge_pts, edge_rads, fg_dot_color)
    if len(depth_emphasis_pts):
        if semantic_aware:
            draw_dots_dualcolor(canvas, depth_emphasis_pts, depth_emphasis_rads,
                                fg_mask, fg_dot_color, bg_dot_color)
        else:
            draw_dots_singlecolor(canvas, depth_emphasis_pts, depth_emphasis_rads, fg_dot_color)

    if save_intermediates and intermediates_dir is not None:
        _save_intermediates(intermediates_dir, d_norm, seg, density, fg_mask, W, H)

    t_total = time.time() - t_start

    n_total = (len(pts_fine) + len(depth_emphasis_pts) + len(edge_pts) + len(bg_pts))
    all_radii = np.concatenate([rad_fine, depth_emphasis_rads, edge_rads, bg_rads]) \
        if n_total > 0 else np.array([0.0])
    stats = {
        "image_size": (W, H),
        "depth_range_m": (float(depth.min()), float(depth.max())),
        "depth_norm_range": (float(d_norm.min()), float(d_norm.max())),
        "n_fine_dots": len(pts_fine),
        "n_depth_emphasis_dots": len(depth_emphasis_pts),
        "n_edge_dots": len(edge_pts),
        "n_bg_dots": len(bg_pts),
        "n_total_dots": n_total,
        "radius_range": (float(all_radii.min()), float(all_radii.max())),
        "semantic_classes": sorted(np.unique(seg).tolist()),
        "fg_pixel_ratio": float(fg_mask.mean()),
        "timing": {"depth": t_depth, "seg": t_seg, "stipple": t_stipple, "total": t_total},
    }
    return canvas, stats


def depth_kusama_polka(input_path: str,
                       output_path: str,
                       palette: str = "black_red",
                       depth_model_path: str = "models/yolo26x-depth.pt",
                       sem_model_path: str = "models/yolo26x-sem.pt",
                       device: str = "0",
                       n_points: int = 20000,
                       n_iter: int = 8,
                       r_min: float = 1.0,
                       r_max: float = 18.0,
                       alpha: float = 1.5,
                       beta: float = 0.6,
                       sigma: float = 0.15,
                       gamma: float = 1.2,
                       pos_jitter: float = 0.3,
                       overlap_gap: float = 2.5,
                       percentile_clip: float = 2.0,
                       multi_scale: bool = True,
                       edge_enhance: bool = True,
                       bg_fill: bool = True,
                       bg_spacing: float = 20.0,
                       semantic_aware: bool = True,
                       target_long_edge: int = 1024,
                       seed: int = 42,
                       save_intermediates: bool = False,
                       output_dir: str = "outputs") -> dict:
    """路径入口 (薄包装): 读文件 → :func:`depth_kusama_polka_core` → 写 PNG.

    保留供按路径调用的脚本使用; PIL 路径请走 :func:`generate_kusama_depth`
    (直接走 ndarray 核心, 无临时文件).

    Returns
    -------
    stats : dict (点数 / 深度范围 / 耗时, 含 ``output`` 路径)
    """
    img = _imread_bgr(input_path)
    canvas, stats = depth_kusama_polka_core(
        img, palette=palette,
        depth_model_path=depth_model_path,
        sem_model_path=sem_model_path,
        device=device,
        n_points=n_points,
        n_iter=n_iter,
        r_min=r_min,
        r_max=r_max,
        alpha=alpha,
        beta=beta,
        sigma=sigma,
        gamma=gamma,
        pos_jitter=pos_jitter,
        overlap_gap=overlap_gap,
        percentile_clip=percentile_clip,
        multi_scale=multi_scale,
        edge_enhance=edge_enhance,
        bg_fill=bg_fill,
        bg_spacing=bg_spacing,
        semantic_aware=semantic_aware,
        target_long_edge=target_long_edge,
        seed=seed,
        save_intermediates=save_intermediates,
        intermediates_dir=output_dir if save_intermediates else None)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    stats["output"] = output_path

    W, H = stats["image_size"]
    print(f"[depth_kusama] {output_path}  ({W}x{H}, palette={palette})")
    print(f"  Depth: {stats['depth_range_m'][0]:.2f}-{stats['depth_range_m'][1]:.2f} m  "
          f"| Dots: {stats['n_total_dots']} (fine={stats['n_fine_dots']}, "
          f"depth_emphasis={stats['n_depth_emphasis_dots']}, "
          f"edge={stats['n_edge_dots']}, bg={stats['n_bg_dots']})")
    t = stats["timing"]
    print(f"  Radius: {stats['radius_range'][0]:.1f}-{stats['radius_range'][1]:.1f} px  "
          f"| FG ratio: {stats['fg_pixel_ratio']:.1%}  "
          f"| Time: {t['total']:.1f}s (depth={t['depth']:.1f}s, "
          f"seg={t['seg']:.1f}s, stipple={t['stipple']:.1f}s)")
    return stats


# ---------------------------------------------------------------------------
# PIL 接口 (供 api.generate 统一调用)
# ---------------------------------------------------------------------------

def generate_kusama_depth(
    image: Image.Image,
    palette: str = "black_red",
    depth_model_path: str = "models/yolo26x-depth.pt",
    sem_model_path: str = "models/yolo26x-sem.pt",
    device: str = "0",
    n_points: int = 20000,
    r_max: float = 14.0,
    alpha: float = 1.5,
    sigma: float = 0.15,
    overlap_gap: float = 4.0,
    semantic_aware: bool = True,
    target_long_edge: int = 1024,
    seed: int = 42,
    **kwargs,
) -> Image.Image:
    """PIL 接口的深度感知草间生成.

    直接走 ndarray 核心 (PIL → BGR → :func:`depth_kusama_polka_core` → RGB),
    无临时文件 / 磁盘 I/O. 需要 ``ultralytics`` + YOLO26 权重,
    无 ultralytics 时抛 ImportError.
    """
    if not has_ultralytics():
        raise ImportError(
            "generate_kusama_depth 需要 ultralytics + YOLO26 权重. "
            "激活 polkadot-art conda 环境或 pip install ultralytics."
        )
    img = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    canvas, _stats = depth_kusama_polka_core(
        img, palette=palette,
        depth_model_path=depth_model_path,
        sem_model_path=sem_model_path,
        device=device,
        n_points=n_points,
        r_max=r_max, alpha=alpha, sigma=sigma,
        overlap_gap=overlap_gap,
        semantic_aware=semantic_aware,
        target_long_edge=target_long_edge,
        seed=seed)
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
