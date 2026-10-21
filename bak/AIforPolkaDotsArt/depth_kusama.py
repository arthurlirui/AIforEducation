"""
Depth-aware polka dot art generation pipeline.

Integrates YOLO26 monocular depth estimation and semantic segmentation with
Weighted Voronoi Stippling to produce Yayoi Kusama--style polka dot art where
dot size encodes scene depth: near objects → large dots, far objects → small
dots, with controlled randomization for organic variation.

Pipeline stages:
    1. YOLO26 depth estimation → metric depth map (H, W)
    2. YOLO26 semantic segmentation → per-pixel class labels (H, W)
    3. Depth-to-density field transformation (inverted: near=dense)
    4. Depth-to-radius mapping with randomization (near=large, far=small)
    5. Semantic-aware multi-layer Voronoi stippling
    6. Kusama stylization (palettes, horror vacui, hard edges)

Mathematical formulation:
    Given depth d(x,y) ∈ [d_min, d_max], define normalized depth:
        d̂(x,y) = (d(x,y) - d_min) / (d_max - d_min)   ∈ [0, 1]
    where d̂=0 is nearest, d̂=1 is farthest.

    Dot radius:
        r(x,y) = [ r_min + (r_max - r_min) · (1 - d̂)^α ] · (1 + ε),   ε ~ N(0, σ²)
    where α controls the depth falloff curvature and σ adds organic randomness.

    Stippling density (drives point placement):
        ρ(x,y) = (1 - d̂)^β · γ(I(x,y))
    where γ(I) is the luminance-based density from the original stippling.

Author: AIforEducation Project
"""

from __future__ import annotations

import os
import time
import argparse
import numpy as np
import cv2
from typing import Optional

from ultralytics import YOLO

from stippling import (
    compute_density,
    rejection_sample,
    lloyd_relax,
    prune_overlapping,
)


# ---------------------------------------------------------------------------
# 1. YOLO26 depth estimation
# ---------------------------------------------------------------------------

class DepthEstimator:
    """Wraps YOLO26 monocular depth estimation model.

    Produces a dense per-pixel metric depth map (in meters) from a single
    RGB image. The depth map is resized to match the original image
    resolution for downstream processing.
    """

    def __init__(self, model_path: str = "yolo26x-depth.pt", device: str = "0"):
        self.model = YOLO(model_path)
        self.device = device

    def predict(self, image: np.ndarray) -> np.ndarray:
        """Run depth estimation on a BGR image.

        Parameters
        ----------
        image : (H, W, 3) BGR uint8

        Returns
        -------
        depth : (H, W) float32, metric depth in meters
        """
        H, W = image.shape[:2]
        results = self.model(image, device=self.device, verbose=False)
        depth = results[0].depth.data.cpu().numpy()  # (H', W') float32
        # resize to original resolution
        if depth.shape != (H, W):
            depth = cv2.resize(depth, (W, H), interpolation=cv2.INTER_CUBIC)
        return depth.astype(np.float32)


# ---------------------------------------------------------------------------
# 2. YOLO26 semantic segmentation
# ---------------------------------------------------------------------------

class SemanticSegmentor:
    """Wraps YOLO26 semantic segmentation model.

    Produces a per-pixel class-label map (Cityscapes 19-class taxonomy).
    The class map enables region-aware rendering: distinct semantic regions
    can receive different dot palettes, densities, or size scales.
    """

    # Cityscapes 19-class taxonomy
    CLASS_NAMES = {
        0: "road", 1: "sidewalk", 2: "building", 3: "wall", 4: "fence",
        5: "pole", 6: "traffic light", 7: "traffic sign", 8: "vegetation",
        9: "terrain", 10: "sky", 11: "person", 12: "rider", 13: "car",
        14: "truck", 15: "bus", 16: "train", 17: "motorcycle", 18: "bicycle",
    }

    def __init__(self, model_path: str = "yolo26x-sem.pt", device: str = "0"):
        self.model = YOLO(model_path)
        self.device = device

    def predict(self, image: np.ndarray) -> np.ndarray:
        """Run semantic segmentation on a BGR image.

        Returns
        -------
        seg : (H, W) uint8, per-pixel class ID
        """
        H, W = image.shape[:2]
        results = self.model(image, device=self.device, verbose=False)
        seg = results[0].semantic_mask.data.cpu().numpy()  # (H', W') uint8
        if seg.shape != (H, W):
            seg = cv2.resize(seg, (W, H), interpolation=cv2.INTER_NEAREST)
        return seg.astype(np.uint8)


# ---------------------------------------------------------------------------
# 3. Depth normalization and field transformations
# ---------------------------------------------------------------------------

def normalize_depth(depth: np.ndarray,
                    d_min: Optional[float] = None,
                    d_max: Optional[float] = None,
                    percentile_clip: float = 2.0) -> np.ndarray:
    """Normalize depth to [0, 1] with optional percentile clipping.

    Returns d̂ where 0 = nearest, 1 = farthest. Percentile clipping
    removes outlier pixels (e.g., sky at infinite depth) that would
    compress the useful depth range.

    Parameters
    ----------
    percentile_clip : clip at this percentile from both ends (0 = no clip)
    """
    if d_min is None:
        d_min = np.percentile(depth, percentile_clip) if percentile_clip > 0 else depth.min()
    if d_max is None:
        d_max = np.percentile(depth, 100 - percentile_clip) if percentile_clip > 0 else depth.max()
    d_max = max(d_max, d_min + 1e-6)
    d_norm = (depth - d_min) / (d_max - d_min)
    return np.clip(d_norm, 0.0, 1.0).astype(np.float32)


def normalize_depth_foreground(depth: np.ndarray,
                               fg_mask: np.ndarray,
                               percentile_clip: float = 2.0) -> np.ndarray:
    """Normalize depth using only the foreground region's depth range.

    This ensures that the full [0, 1] normalized depth range is mapped
    to the depth variation *within foreground objects*, producing finer
    depth detail in dot size modulation. Background pixels are assigned
    d̂ = 1.0 (farthest), so they receive the smallest dots.

    The foreground depth range typically spans a smaller absolute range
    than the full-image depth range (which includes distant sky, road,
    etc.). By normalizing within this narrower range, subtle depth
    differences between parts of the same object---e.g., the nose vs.
    the ears of a cat, or the front vs. back of a pumpkin---are
    amplified into visible dot size differences.

    Parameters
    ----------
    depth : (H, W) float32, metric depth in meters
    fg_mask : (H, W) uint8, 1 = foreground, 0 = background
    percentile_clip : clip at this percentile within the foreground region

    Returns
    -------
    d_norm : (H, W) float32, normalized depth in [0, 1]
             Foreground: 0 = nearest foreground point, 1 = farthest foreground point
             Background: 1.0 (farthest, receives smallest dots)
    """
    fg_depths = depth[fg_mask > 0]
    if len(fg_depths) < 10:
        # too few foreground pixels; fall back to global normalization
        return normalize_depth(depth, percentile_clip=percentile_clip)

    if percentile_clip > 0:
        d_min = np.percentile(fg_depths, percentile_clip)
        d_max = np.percentile(fg_depths, 100 - percentile_clip)
    else:
        d_min = fg_depths.min()
        d_max = fg_depths.max()
    d_max = max(d_max, d_min + 1e-6)

    d_norm = (depth - d_min) / (d_max - d_min)
    d_norm = np.clip(d_norm, 0.0, 1.0).astype(np.float32)
    # background pixels: clamp to 1.0 (farthest) so they get the smallest dots
    d_norm[fg_mask == 0] = 1.0
    return d_norm


def depth_to_radius(d_norm: np.ndarray,
                    r_min: float = 1.0,
                    r_max: float = 25.0,
                    alpha: float = 1.5,
                    sigma: float = 0.12,
                    rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """Map normalized depth to dot radius with randomization.

    Mathematical formulation:
        r(x,y) = r_min + (r_max - r_min) · (1 - d̂)^α · (1 + ε)
        ε ~ N(0, σ²)

    Near objects (d̂→0) get large dots; far objects (d̂→1) get small dots.
    The exponent α controls the depth-size falloff curvature:
        α < 1: concave, gentle size variation (most dots medium)
        α = 1: linear falloff
        α > 1: convex, dramatic size variation (strong depth emphasis)
    The Gaussian noise σ adds organic randomness characteristic of
    Kusama's hand-painted dots which are never perfectly uniform.

    Parameters
    ----------
    d_norm : (H, W) float32, normalized depth in [0, 1]
    r_min, r_max : radius range in pixels
    alpha : depth falloff exponent (default 1.5 for strong depth emphasis)
    sigma : multiplicative Gaussian noise std (default 0.12)
    rng : random generator for reproducibility
    """
    if rng is None:
        rng = np.random.default_rng()
    # depth-weighted radius: near = large, far = small
    depth_weight = np.power(1.0 - d_norm, alpha)
    radii = r_min + (r_max - r_min) * depth_weight
    # multiplicative Gaussian noise for organic variation
    if sigma > 0:
        noise = rng.normal(0, sigma, radii.shape)
        radii *= (1.0 + noise)
    return np.clip(radii, 0.3, r_max * 1.1).astype(np.float32)


def depth_to_density(d_norm: np.ndarray,
                     gray: np.ndarray,
                     gamma: float = 1.2,
                     beta: float = 0.6,
                     invert_luminance: bool = True) -> np.ndarray:
    """Compute a composite density field from depth and luminance.

    The density field drives Voronoi stippling point placement. We combine:
        - Depth density: (1 - d̂)^β — near objects get higher dot density
        - Luminance density: standard stippling convention (dark = dense)

    The final density is the element-wise product:
        ρ(x,y) = (1 - d̂)^β · γ(I(x,y))

    where γ(I) is the gamma-corrected inverted luminance density.

    Parameters
    ----------
    d_norm : (H, W) normalized depth
    gray : (H, W) grayscale image
    gamma : luminance gamma correction (default 1.2, >1 emphasizes dark regions)
    beta : depth density exponent (default 0.6, <1 to keep far regions populated)
    invert_luminance : if True, dark pixels get high density (stippling convention)
    """
    # luminance-based density (from original stippling.py)
    lum_density = compute_density(gray, gamma=gamma, invert=invert_luminance)
    # depth-based density: near = dense, far = sparse
    depth_density = np.power(1.0 - d_norm, beta)
    # composite: geometric mean of both
    density = depth_density * lum_density
    # normalize to [0, 1]
    d_max = density.max()
    if d_max > 1e-9:
        density /= d_max
    return density.astype(np.float32)


# ---------------------------------------------------------------------------
# 4. Depth-aware stippling
# ---------------------------------------------------------------------------

def depth_aware_stipple(density: np.ndarray,
                        d_norm: np.ndarray,
                        n_points: int = 20000,
                        n_iter: int = 10,
                        r_min: float = 1.0,
                        r_max: float = 25.0,
                        alpha: float = 1.5,
                        sigma: float = 0.12,
                        pos_jitter: float = 0.4,
                        overlap_gap: float = 2.0,
                        seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate depth-aware stipple points.

    Combines Voronoi stippling (for blue-noise point distribution) with
    depth-modulated radius assignment. Points are placed according to the
    composite density field, then each point's radius is determined by
    the local depth value with Gaussian randomization.

    Returns
    -------
    points : (n, 2) float (x, y) in image coordinates
    radii : (n,) float
    """
    rng = np.random.default_rng(seed)

    # 1. rejection sampling initialization (density-weighted)
    pts = rejection_sample(density, n_points, rng)

    # 2. Lloyd relaxation for blue-noise distribution
    pts = lloyd_relax(pts, density, n_iter=n_iter, rng=rng)

    # 3. depth-modulated radius assignment
    xi = np.clip(pts[:, 0].astype(int), 0, d_norm.shape[1] - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, d_norm.shape[0] - 1)
    local_d = d_norm[yi, xi]

    # vectorized depth-to-radius with per-point randomization
    depth_weight = np.power(1.0 - local_d, alpha)
    radii = r_min + (r_max - r_min) * depth_weight
    if sigma > 0:
        radii *= (1.0 + rng.normal(0, sigma, radii.shape))
    radii = np.clip(radii, 0.3, r_max * 1.1)

    # 4. position jitter
    if pos_jitter > 0:
        pts = pts + rng.normal(0, pos_jitter, pts.shape)

    # 5. overlap pruning (depth-adaptive: large near dots stay apart,
    #    small far dots pack closely)
    if overlap_gap >= 0:
        pts, radii = prune_overlapping(pts, radii, gap=overlap_gap)

    return pts, radii


# ---------------------------------------------------------------------------
# 5. Semantic region analysis
# ---------------------------------------------------------------------------

def analyze_semantic_regions(seg: np.ndarray) -> list[dict]:
    """Identify connected semantic regions and compute per-region statistics.

    Returns a list of region descriptors sorted by area (descending):
        {class_id, class_name, area, bbox, centroid, mask}
    """
    regions = []
    unique_classes = np.unique(seg)
    for cls_id in unique_classes:
        mask = (seg == cls_id).astype(np.uint8)
        # find connected components within this class
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n_labels):  # skip background (label 0)
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < 100:  # skip tiny regions
                continue
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            cx, cy = centroids[i]
            comp_mask = (labels == i).astype(np.uint8)
            regions.append({
                "class_id": int(cls_id),
                "class_name": SemanticSegmentor.CLASS_NAMES.get(int(cls_id), "unknown"),
                "area": area,
                "bbox": (x, y, w, h),
                "centroid": (cx, cy),
                "mask": comp_mask,
            })
    regions.sort(key=lambda r: r["area"], reverse=True)
    return regions


def get_foreground_mask(seg: np.ndarray, min_area_ratio: float = 0.02) -> np.ndarray:
    """Identify foreground objects (non-background semantic classes).

    Background classes are: road(0), sidewalk(1), building(2), wall(3),
    sky(10), vegetation(8), terrain(9). Everything else is foreground.
    """
    H, W = seg.shape
    background_classes = {0, 1, 2, 3, 8, 9, 10}
    fg = np.ones((H, W), dtype=np.uint8)
    for cls_id in background_classes:
        fg[seg == cls_id] = 0
    # remove small foreground fragments
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    min_area = int(H * W * min_area_ratio)
    fg_clean = np.zeros_like(fg)
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            fg_clean[labels == i] = 1
    return fg_clean


# ---------------------------------------------------------------------------
# 6. Depth-aware Kusama palettes (with semantic awareness)
# ---------------------------------------------------------------------------

# Palettes: (background BGR, foreground dot BGR, background dot BGR)
# Foreground objects get one color, background regions get another.
DEPTH_PALETTES = {
    "black_red": {
        "bg": (0, 0, 0),
        "fg_dot": (0, 0, 220),      # red dots for foreground objects
        "bg_dot": (0, 180, 180),    # cyan-ish dots for background
    },
    "yellow_black": {
        "bg": (0, 215, 255),
        "fg_dot": (0, 0, 0),
        "bg_dot": (0, 0, 180),      # dark red for background
    },
    "white_red": {
        "bg": (255, 255, 255),
        "fg_dot": (0, 0, 220),
        "bg_dot": (200, 200, 0),    # cyan-blue for background
    },
    "magenta_cyan": {
        "bg": (10, 10, 30),         # near-black
        "fg_dot": (220, 0, 220),    # magenta for foreground
        "bg_dot": (220, 180, 0),    # cyan for background
    },
    "red_yellow": {
        "bg": (0, 0, 200),
        "fg_dot": (0, 215, 255),    # yellow dots for foreground
        "bg_dot": (255, 255, 255),  # white for background
    },
}


# ---------------------------------------------------------------------------
# 7. Rendering
# ---------------------------------------------------------------------------

def draw_dots_dualcolor(canvas: np.ndarray,
                         points: np.ndarray,
                         radii: np.ndarray,
                         fg_mask: np.ndarray,
                         fg_color: tuple,
                         bg_color: tuple) -> None:
    """Draw hard-edged dots with semantic-aware coloring.

    Dots whose center falls in the foreground mask get fg_color;
    all others get bg_color. This creates Kusama's signature effect
    of objects "dissolving" into dot fields while maintaining
    semantic distinction through color.
    """
    H, W = fg_mask.shape
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        # determine color by semantic region
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
    """Draw all dots in a single color (for background fill, edges, etc.)."""
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        if rr < 1:
            if 0 <= xi < canvas.shape[1] and 0 <= yi < canvas.shape[0]:
                canvas[yi, xi] = color
        else:
            cv2.circle(canvas, (xi, yi), rr, color, -1, lineType=cv2.LINE_4)


# ---------------------------------------------------------------------------
# 8. Full depth-aware Kusama pipeline
# ---------------------------------------------------------------------------

def _prune_layer(points, radii, gap):
    """Prune overlapping dots within a single layer."""
    if len(points) == 0:
        return points, radii
    return prune_overlapping(points, radii, gap=gap)


def _merge_layers(pts_list, rad_list, inter_gap=1.0):
    """Merge multiple dot layers, pruning overlaps across layers.

    Layers are merged in order; later layers' dots that overlap already-
    placed dots are removed. This prevents large depth-emphasis dots from
    colliding with the fine stipple layer.
    """
    from scipy.spatial import cKDTree
    merged_pts = []
    merged_rad = []
    for pts, rads in zip(pts_list, rad_list):
        if len(pts) == 0:
            continue
        if len(merged_pts) == 0:
            merged_pts = list(pts)
            merged_rad = list(rads)
            continue
        tree = cKDTree(np.array(merged_pts))
        keep = []
        mp = np.array(merged_pts)
        mr = np.array(merged_rad)
        for i in range(len(pts)):
            search_r = rads[i] + mr.max() + inter_gap
            neighbors = tree.query_ball_point(pts[i], search_r)
            ok = True
            for j in neighbors:
                if np.linalg.norm(pts[i] - mp[j]) < rads[i] + mr[j] + inter_gap:
                    ok = False
                    break
            if ok:
                keep.append(i)
        if keep:
            keep = np.array(keep)
            merged_pts.extend(pts[keep])
            merged_rad.extend(rads[keep])
    return np.array(merged_pts), np.array(merged_rad)


def depth_kusama_polka(input_path: str,
                       output_path: str,
                       palette: str = "black_red",
                       depth_model_path: str = "yolo26x-depth.pt",
                       sem_model_path: str = "yolo26x-sem.pt",
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
    """Render an input image as depth-aware Kusama-style polka dot art.

    The pipeline integrates YOLO26 monocular depth estimation and semantic
    segmentation with Weighted Voronoi Stippling. Dot size encodes scene
    depth (near=large, far=small) with controlled Gaussian randomization,
    while semantic segmentation enables region-aware coloring.

    Three-layer architecture
    ------------------------
    The pipeline renders dots in three depth-stratified layers to avoid
    blob merging while preserving the multi-scale Kusama aesthetic:

    1. **Fine stipple layer** (r = 1–5 px): dense, depth-modulated small
       dots covering the entire canvas. Dot density follows the composite
       depth-luminance density field. This layer provides the base texture.

    2. **Depth-emphasis layer** (r = 5–r_max px): sparse, large dots placed
       only in near regions (d̂ < depth_threshold). These dots are pruned
       against the fine layer to prevent merging. They encode the strongest
       depth signal.

    3. **Edge & background layer**: small dots along Canny contours for
       structural emphasis, plus a sparse horror-vacui fill in empty
       background regions.

    Parameters
    ----------
    palette : one of DEPTH_PALETTES keys
    alpha : depth-to-radius falloff exponent (higher = stronger depth emphasis)
    beta : depth-to-density exponent (lower = more uniform far-region coverage)
    sigma : Gaussian noise std for radius randomization (organic variation)
    semantic_aware : if True, foreground/background get different dot colors
    save_intermediates : save depth map, seg map, and density field visualizations

    Returns
    -------
    stats : dict with pipeline statistics (n_dots, depth range, etc.)
    """
    t_start = time.time()
    rng = np.random.default_rng(seed)

    # --- Load image ---
    img = cv2.imread(input_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {input_path}")
    H0, W0 = img.shape[:2]
    scale = target_long_edge / max(H0, W0)
    if scale < 1.0:
        img = cv2.resize(img, (int(W0 * scale), int(H0 * scale)),
                         interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- Stage 1: Depth estimation ---
    t0 = time.time()
    depth_estimator = DepthEstimator(depth_model_path, device=device)
    depth = depth_estimator.predict(img)
    t_depth = time.time() - t0

    # --- Stage 2: Semantic segmentation ---
    t0 = time.time()
    segmentor = SemanticSegmentor(sem_model_path, device=device)
    seg = segmentor.predict(img)
    fg_mask = get_foreground_mask(seg) if semantic_aware else np.ones((H, W), dtype=np.uint8)
    t_seg = time.time() - t0

    # --- Stage 2b: Foreground-aware depth normalization ---
    # Normalize depth using only the foreground region's depth range,
    # so that the full [0,1] range captures depth variation *within*
    # the foreground objects. This amplifies subtle depth differences
    # (e.g., front vs. back of a pumpkin) into visible dot size variation.
    # Background pixels are assigned d̂ = 1.0 (farthest → smallest dots).
    if semantic_aware and fg_mask.mean() > 0.005:
        d_norm = normalize_depth_foreground(depth, fg_mask,
                                            percentile_clip=percentile_clip)
    else:
        d_norm = normalize_depth(depth, percentile_clip=percentile_clip)

    # --- Stage 3: Composite density field ---
    density = depth_to_density(d_norm, gray, gamma=gamma, beta=beta)

    t0 = time.time()

    # --- Layer 1: Fine stipple (small dots, depth-modulated density) ---
    # These are the "base texture" dots — small, densely packed, with
    # subtle depth variation in size. The overlap gap is tight so they
    # can form a rich stipple texture without merging.
    fine_r_max = min(5.0, r_max * 0.35)
    pts_fine, rad_fine = depth_aware_stipple(
        density, d_norm,
        n_points=n_points, n_iter=n_iter,
        r_min=r_min, r_max=fine_r_max,
        alpha=alpha * 0.6, sigma=sigma,
        pos_jitter=pos_jitter,
        overlap_gap=1.0,
        seed=seed)

    # --- Layer 2: Depth-emphasis (large dots, near regions only) ---
    # These dots carry the main depth signal: near objects get big bold
    # dots, far objects get none. We sample from a near-weighted density
    # and prune against the fine layer so they never merge with it.
    depth_emphasis_pts = np.empty((0, 2))
    depth_emphasis_rads = np.empty((0,))
    if multi_scale:
        # near-region mask: place large dots where depth is below threshold
        # AND the pixel is foreground. With foreground-aware normalization,
        # the threshold operates on the foreground depth range, so it
        # selects the nearest portion of foreground objects.
        near_threshold = 0.55  # d̂ < 0.55 = nearer half of foreground depth range
        near_mask = ((d_norm < near_threshold) & (fg_mask > 0)).astype(np.float32)

        # near-weighted density: emphasize near regions, modulated by luminance
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
                pos_jitter=pos_jitter,
                overlap_gap=overlap_gap,
                seed=seed + 1)

            # Cross-layer pruning: remove fine dots that fall inside large
            # depth-emphasis dots. This prevents the large dots from
            # connecting to nearby fine dots and forming merged blobs.
            if len(pts_large) > 0 and len(pts_fine) > 0:
                from scipy.spatial import cKDTree
                tree_large = cKDTree(pts_large)
                fine_keep = np.ones(len(pts_fine), dtype=bool)
                for i in range(len(pts_fine)):
                    search_r = rad_fine[i] + rad_large.max() + 2.0
                    neighbors = tree_large.query_ball_point(pts_fine[i], search_r)
                    for j in neighbors:
                        d = np.linalg.norm(pts_fine[i] - pts_large[j])
                        if d < rad_fine[i] + rad_large[j] + 1.0:
                            fine_keep[i] = False
                            break
                pts_fine = pts_fine[fine_keep]
                rad_fine = rad_fine[fine_keep]

            depth_emphasis_pts = pts_large
            depth_emphasis_rads = rad_large

    # --- Layer 3: Edge enhancement ---
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

    # --- Layer 4: Horror vacui background fill ---
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

    # --- Stage 5: Merge layers and render ---
    pal = DEPTH_PALETTES[palette]
    bg_color = pal["bg"]
    fg_dot_color = pal["fg_dot"]
    bg_dot_color = pal["bg_dot"]

    canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)

    # Draw order: background fill → fine stipple → edge dots → depth-emphasis (on top)
    # Background fill: single color (bg_dot), drawn first (underneath)
    if len(bg_pts):
        draw_dots_singlecolor(canvas, bg_pts, bg_rads, bg_dot_color)

    # Fine stipple: dual-color (semantic-aware), drawn second
    if len(pts_fine):
        if semantic_aware:
            draw_dots_dualcolor(canvas, pts_fine, rad_fine,
                                fg_mask, fg_dot_color, bg_dot_color)
        else:
            draw_dots_singlecolor(canvas, pts_fine, rad_fine, fg_dot_color)

    # Edge dots: fg_dot color, drawn third (over fine stipple)
    if len(edge_pts):
        draw_dots_singlecolor(canvas, edge_pts, edge_rads, fg_dot_color)

    # Depth-emphasis: dual-color, drawn last (on top, most prominent)
    if len(depth_emphasis_pts):
        if semantic_aware:
            draw_dots_dualcolor(canvas, depth_emphasis_pts, depth_emphasis_rads,
                                fg_mask, fg_dot_color, bg_dot_color)
        else:
            draw_dots_singlecolor(canvas, depth_emphasis_pts, depth_emphasis_rads, fg_dot_color)

    # --- Save output ---
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6])

    # --- Save intermediate visualizations ---
    if save_intermediates:
        _save_intermediates(output_dir, depth, d_norm, seg, density, fg_mask,
                            SemanticSegmentor.CLASS_NAMES, W, H)

    t_total = time.time() - t_start

    # --- Statistics ---
    n_total = (len(pts_fine) + len(depth_emphasis_pts) +
               len(edge_pts) + len(bg_pts))
    all_radii = np.concatenate([rad_fine, depth_emphasis_rads, edge_rads, bg_rads]) \
        if n_total > 0 else np.array([0.0])
    stats = {
        "output": output_path,
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
    print(f"[depth_kusama] {output_path}  ({W}x{H}, palette={palette})")
    print(f"  Depth: {stats['depth_range_m'][0]:.2f}-{stats['depth_range_m'][1]:.2f} m  "
          f"| Dots: {n_total} (fine={len(pts_fine)}"
          f", depth_emphasis={len(depth_emphasis_pts)}"
          f", edge={len(edge_pts)}"
          f", bg={len(bg_pts)})")
    print(f"  Radius: {stats['radius_range'][0]:.1f}-{stats['radius_range'][1]:.1f} px  "
          f"| FG ratio: {stats['fg_pixel_ratio']:.1%}  "
          f"| Time: {t_total:.1f}s (depth={t_depth:.1f}s, seg={t_seg:.1f}s, stipple={t_stipple:.1f}s)")
    return stats


def _save_intermediates(output_dir: str, depth: np.ndarray, d_norm: np.ndarray,
                        seg: np.ndarray, density: np.ndarray, fg_mask: np.ndarray,
                        class_names: dict, W: int, H: int):
    """Save visualizations of intermediate pipeline stages."""
    inter_dir = os.path.join(output_dir, "intermediates")
    os.makedirs(inter_dir, exist_ok=True)

    # Depth map colorized
    depth_vis = cv2.applyColorMap(
        (d_norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    cv2.imwrite(os.path.join(inter_dir, "depth_normalized.png"), depth_vis)

    # Semantic segmentation colorized
    seg_vis = np.zeros((H, W, 3), dtype=np.uint8)
    colors = np.random.default_rng(42).integers(50, 255, (20, 3))
    for cls_id in np.unique(seg):
        seg_vis[seg == cls_id] = colors[cls_id]
    cv2.imwrite(os.path.join(inter_dir, "semantic_seg.png"), seg_vis)

    # Density field
    density_vis = cv2.applyColorMap(
        (density * 255).astype(np.uint8), cv2.COLORMAP_VIRIDIS)
    cv2.imwrite(os.path.join(inter_dir, "density_field.png"), density_vis)

    # Foreground mask
    fg_vis = np.zeros((H, W, 3), dtype=np.uint8)
    fg_vis[fg_mask > 0] = (0, 255, 0)
    cv2.imwrite(os.path.join(inter_dir, "foreground_mask.png"), fg_vis)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Depth-aware Kusama-style polka dot art generator (YOLO26 + Voronoi stippling)")
    p.add_argument("input", help="input image path")
    p.add_argument("-o", "--output", default="depth_kusama_output.png", help="output path")
    p.add_argument("--depth-model", default="yolo26x-depth.pt", help="YOLO26 depth model path")
    p.add_argument("--sem-model", default="yolo26x-sem.pt", help="YOLO26 semantic seg model path")
    p.add_argument("--device", default="0", help="device (0 for GPU, cpu for CPU)")
    p.add_argument("--palette", default="black_red", choices=list(DEPTH_PALETTES.keys()))
    p.add_argument("--n-points", type=int, default=20000)
    p.add_argument("--n-iter", type=int, default=10)
    p.add_argument("--r-min", type=float, default=1.0, help="minimum dot radius (px)")
    p.add_argument("--r-max", type=float, default=25.0, help="maximum dot radius (px)")
    p.add_argument("--alpha", type=float, default=1.5, help="depth-to-radius falloff exponent")
    p.add_argument("--beta", type=float, default=0.6, help="depth-to-density exponent")
    p.add_argument("--sigma", type=float, default=0.12, help="radius randomization noise std")
    p.add_argument("--gamma", type=float, default=1.2, help="luminance gamma correction")
    p.add_argument("--overlap-gap", type=float, default=2.0)
    p.add_argument("--percentile-clip", type=float, default=2.0, help="depth percentile clipping")
    p.add_argument("--no-multi-scale", action="store_true")
    p.add_argument("--no-edge", action="store_true")
    p.add_argument("--no-bg-fill", action="store_true")
    p.add_argument("--no-semantic", action="store_true", help="disable semantic-aware coloring")
    p.add_argument("--target-long-edge", type=int, default=1024)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--save-intermediates", action="store_true",
                   help="save depth/seg/density visualizations")
    args = p.parse_args()

    depth_kusama_polka(
        args.input, args.output,
        depth_model_path=args.depth_model,
        sem_model_path=args.sem_model,
        device=args.device,
        palette=args.palette,
        n_points=args.n_points,
        n_iter=args.n_iter,
        r_min=args.r_min, r_max=args.r_max,
        alpha=args.alpha, beta=args.beta, sigma=args.sigma,
        gamma=args.gamma,
        overlap_gap=args.overlap_gap,
        percentile_clip=args.percentile_clip,
        multi_scale=not args.no_multi_scale,
        edge_enhance=not args.no_edge,
        bg_fill=not args.no_bg_fill,
        semantic_aware=not args.no_semantic,
        target_long_edge=args.target_long_edge,
        seed=args.seed,
        save_intermediates=args.save_intermediates,
    )
