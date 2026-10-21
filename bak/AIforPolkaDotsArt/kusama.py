"""
Kusama-style polka dot art renderer.

Takes an input image, runs Voronoi stippling to get a dot distribution,
then applies Yayoi Kusama's signature visual traits:
    - high-chroma duotone palettes (black/red, yellow/black, white/red, ...)
    - horror vacui: background fully covered with a sparse small-dot fill
    - multi-scale dots: 2-3 stipple layers of different density/radius
    - edge enhancement: extra small dots along Canny edges
    - hard-edged solid circles (no gradients within a dot)
"""

from __future__ import annotations

import cv2
import numpy as np

from stippling import compute_density, stipple


# ---------------------------------------------------------------------------
# Kusama palettes: (background BGR, dot BGR)
# ---------------------------------------------------------------------------

PALETTES = {
    "black_red":      ((0, 0, 0),       (0, 0, 220)),     # black bg, red dots
    "yellow_black":   ((0, 215, 255),   (0, 0, 0)),       # chrome yellow bg, black dots
    "white_red":      ((255, 255, 255), (0, 0, 220)),     # white bg, scarlet dots
    "red_white":      ((0, 0, 200),     (255, 255, 255)), # red bg, white dots
    "magenta_black":  ((0, 0, 0),       (220, 0, 220)),   # black bg, magenta dots
    "yellow_red":     ((0, 215, 255),   (0, 0, 220)),     # yellow bg, red dots
}


# ---------------------------------------------------------------------------
# Edge enhancement
# ---------------------------------------------------------------------------

def canny_edges(gray: np.ndarray, low: int = 80, high: int = 160) -> np.ndarray:
    """Return a binary edge mask (255 where edge)."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    return cv2.Canny(blurred, low, high)


def edge_points(edges: np.ndarray, step: int = 4, jitter: float = 1.5,
                rng: np.random.Generator | None = None,
                r: float = 1.2) -> tuple[np.ndarray, np.ndarray]:
    """Sample small dots along Canny edges for contour emphasis."""
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
# Horror vacui: sparse background fill
# ---------------------------------------------------------------------------

def background_fill_points(W: int, H: int, spacing: float = 18.0,
                           r: float = 1.0, jitter: float = 3.0,
                           seed: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """A sparse jittered grid of tiny dots to fill empty background areas,
    honoring Kusama's horror vacui (no blank space)."""
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
# Drawing
# ---------------------------------------------------------------------------

def draw_dots(canvas: np.ndarray, points: np.ndarray, radii: np.ndarray,
              color_bgr: tuple[int, int, int]) -> None:
    """Draw hard-edged solid circles (in-place). Points in (x, y) image coords.
    Kusama's dots are hard-edged; no anti-aliasing (which also prevents
    neighboring dots from being bridged by intermediate-alpha pixels)."""
    for (x, y), r in zip(points, radii):
        xi, yi = int(round(x)), int(round(y))
        rr = int(round(r))
        if rr < 1:
            # sub-pixel dot: draw a single pixel
            if 0 <= xi < canvas.shape[1] and 0 <= yi < canvas.shape[0]:
                canvas[yi, xi] = color_bgr
        else:
            cv2.circle(canvas, (xi, yi), rr,
                       color_bgr, -1, lineType=cv2.LINE_4)


# ---------------------------------------------------------------------------
# Full Kusama pipeline
# ---------------------------------------------------------------------------

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
    """Render an input image as Kusama-style polka dot art.

    Parameters
    ----------
    palette : one of PALETTES keys
    multi_scale : if True, add a second coarser stipple layer (fewer, larger dots)
    target_long_edge : downscale large inputs for tractable Voronoi compute time
    """
    rng = np.random.default_rng(seed)

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
    density = compute_density(gray, gamma=gamma, invert=True)
    bg_color, dot_color = PALETTES[palette]

    # main stipple layer
    pts1, rad1 = stipple(density, n_points=n_points, n_iter=n_iter,
                         r_min=r_min, r_max=r_max, gamma=1.0,
                         size_jitter=size_jitter, pos_jitter=pos_jitter,
                         min_dist=min_dist, overlap_gap=overlap_gap,
                         seed=seed)

    all_pts = [pts1]
    all_rads = [rad1]

    # optional second coarser layer (multi-scale, Kusama's mixed dot sizes).
    # Uses INVERTED density so large decorative dots land in bright regions,
    # complementing the main layer's large dots in dark regions.
    if multi_scale:
        n2 = max(n_points // 5, 600)
        inv_density = 1.0 - density
        pts2, rad2 = stipple(inv_density, n_points=n2, n_iter=n_iter,
                             r_min=r_max * 0.8, r_max=r_max * 1.5, gamma=1.0,
                             size_jitter=size_jitter, pos_jitter=pos_jitter,
                             min_dist=min_dist, overlap_gap=overlap_gap * 1.2,
                             seed=seed + 1)
        all_pts.append(pts2)
        all_rads.append(rad2)

    # edge enhancement dots (small, along contours)
    edges = canny_edges(gray)
    epts, erad = edge_points(edges, step=edge_step, jitter=1.2, rng=rng, r=edge_r)
    if len(epts):
        all_pts.append(epts)
        all_rads.append(erad)

    # background horror-vacui fill (only where image is bright/sparse)
    bg_pts, bg_rads = background_fill_points(W, H, spacing=bg_spacing,
                                              r=bg_r, jitter=3.0, seed=seed + 2)
    # only keep background dots in low-density regions to avoid over-crowding dark areas
    bxi = np.clip(bg_pts[:, 0].astype(int), 0, W - 1)
    byi = np.clip(bg_pts[:, 1].astype(int), 0, H - 1)
    bg_keep = density[byi, bxi] < 0.25
    if bg_keep.any():
        all_pts.append(bg_pts[bg_keep])
        all_rads.append(bg_rads[bg_keep])

    # --- render ---
    canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)

    # draw background fill first (small), then main, then coarse on top
    # order: bg -> main -> multi-scale -> edges
    # but we appended in order [main, multi, edge, bg]; reorder:
    draw_order = [3, 0, 1, 2]  # bg first, then main, multi, edge
    for idx in draw_order:
        if idx < len(all_pts) and len(all_pts[idx]):
            draw_dots(canvas, all_pts[idx], all_rads[idx], dot_color)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(f"Saved: {output_path}  ({W}x{H}, palette={palette}, "
          f"main={len(pts1)} dots"
          f"{f', multi={len(all_pts[1])}' if multi_scale else ''}"
          f"{f', edge={len(epts)}' if len(epts) else ''}"
          f", bg={int(bg_keep.sum())})")
    return canvas


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Kusama-style polka dot art generator")
    p.add_argument("input", help="input image path")
    p.add_argument("-o", "--output", default="kusama_output.png", help="output path")
    p.add_argument("--palette", default="black_red", choices=list(PALETTES.keys()))
    p.add_argument("--n-points", type=int, default=20000)
    p.add_argument("--n-iter", type=int, default=10)
    p.add_argument("--r-min", type=float, default=1.0)
    p.add_argument("--r-max", type=float, default=5.0)
    p.add_argument("--gamma", type=float, default=1.2)
    p.add_argument("--min-dist", type=float, default=0.0)
    p.add_argument("--overlap-gap", type=float, default=2.0)
    p.add_argument("--no-multi-scale", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--target-long-edge", type=int, default=1024)
    args = p.parse_args()

    kusama_polka(
        args.input, args.output,
        palette=args.palette,
        n_points=args.n_points,
        n_iter=args.n_iter,
        r_min=args.r_min, r_max=args.r_max,
        gamma=args.gamma,
        min_dist=args.min_dist,
        overlap_gap=args.overlap_gap,
        multi_scale=not args.no_multi_scale,
        seed=args.seed,
        target_long_edge=args.target_long_edge,
    )
