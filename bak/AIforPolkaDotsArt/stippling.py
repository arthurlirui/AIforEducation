"""
Voronoi stippling core algorithm (Secord 2002) for Kusama-style polka dot art.

Self-contained implementation using scipy.spatial.Voronoi with the mirror-points
trick to handle unbounded cells, and cumulative-sum acceleration for the
weighted centroid computation.

Coordinate convention:
    - density array shape (H, W), indexed [row, col] = [y, x]
    - points stored as (x, y) with x in [0, W], y in [0, H]  (image coords, y-down)
"""

from __future__ import annotations

import numpy as np
import scipy.spatial
from scipy.spatial import Voronoi


# ---------------------------------------------------------------------------
# Density field
# ---------------------------------------------------------------------------

def compute_density(gray: np.ndarray, gamma: float = 1.0, invert: bool = True) -> np.ndarray:
    """Convert a grayscale image to a normalized density field in [0, 1].

    With invert=True (default), dark pixels get HIGH density (more dots),
    which is the standard stippling convention.
    """
    g = gray.astype(np.float64) / 255.0
    if invert:
        g = 1.0 - g
    # gamma > 1 pushes more density into midtones/shadows
    g = np.power(g, gamma)
    g /= max(g.max(), 1e-9)
    return g


# ---------------------------------------------------------------------------
# Rejection sampling initialization
# ---------------------------------------------------------------------------

def rejection_sample(density: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Sample n points with probability proportional to density.

    Returns (n, 2) array of (x, y) coordinates in image space.
    Vectorized: generates candidates in batches for speed.
    """
    H, W = density.shape
    pts = np.empty((n, 2), dtype=np.float64)
    filled = 0
    while filled < n:
        batch = max((n - filled) * 3, 4096)
        xs = rng.uniform(0, W, batch)
        ys = rng.uniform(0, H, batch)
        ps = rng.uniform(0, 1, batch)
        xi = np.clip(xs.astype(int), 0, W - 1)
        yi = np.clip(ys.astype(int), 0, H - 1)
        accept = ps < density[yi, xi]
        ax, ay = xs[accept], ys[accept]
        take = min(len(ax), n - filled)
        pts[filled:filled + take, 0] = ax[:take]
        pts[filled:filled + take, 1] = ay[:take]
        filled += take
    return pts


# ---------------------------------------------------------------------------
# Voronoi with mirror points (handles unbounded cells)
# ---------------------------------------------------------------------------

def voronoi_filtered(points: np.ndarray, W: int, H: int) -> scipy.spatial.Voronoi:
    """Compute Voronoi diagram with mirrored points to eliminate unbounded cells.

    Returns a Voronoi object with extra attributes:
        filtered_regions : list of vertex-index lists (all bounded, in-bbox)
    Only regions belonging to the original (non-mirror) points are kept.
    """
    eps = 0.1
    # mirror points across each of the 4 bbox edges
    left = points.copy(); left[:, 0] = -left[:, 0]
    right = points.copy(); right[:, 0] = 2 * W - right[:, 0]
    top = points.copy(); top[:, 1] = -top[:, 1]
    bottom = points.copy(); bottom[:, 1] = 2 * H - bottom[:, 1]
    all_pts = np.concatenate([points, left, right, top, bottom], axis=0)

    vor = Voronoi(all_pts)

    regions = []
    n_orig = len(points)
    # point_region[i] gives the region index for input point i
    for i in range(n_orig):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            # fallback: skip (shouldn't happen with mirror points)
            continue
        ok = True
        for idx in region:
            x, y = vor.vertices[idx]
            if not (-eps <= x <= W + eps and -eps <= y <= H + eps):
                ok = False
                break
        if ok:
            regions.append(region)
    vor.filtered_regions = regions
    return vor


# ---------------------------------------------------------------------------
# Weighted centroid via cumulative sums (fast)
# ---------------------------------------------------------------------------

def weighted_centroid_cumsum(vertices: np.ndarray, density: np.ndarray,
                              P: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Compute the density-weighted centroid of a polygon using cumulative sums.

    vertices : (k, 2) polygon vertices (x, y), image coords y-down
    density  : (H, W) density field
    P = density.cumsum(axis=1)   ;  Q = P.cumsum(axis=1)

    Uses a scanline fill of the polygon, then sums density*position over
    filled pixels. Returns (cx, cy).
    """
    H, W = density.shape
    xs = vertices[:, 0]
    ys = vertices[:, 1]
    y_min = max(int(np.floor(ys.min())), 0)
    y_max = min(int(np.ceil(ys.max())), H - 1)

    # accumulate sums over scanlines
    sum_d = 0.0
    sum_xd = 0.0
    sum_yd = 0.0

    for y in range(y_min, y_max + 1):
        # find x-intersections of polygon edges with horizontal line at y+0.5
        xints = []
        for j in range(len(vertices)):
            x1, y1 = vertices[j]
            x2, y2 = vertices[(j + 1) % len(vertices)]
            if (y1 <= y + 0.5 < y2) or (y2 <= y + 0.5 < y1):
                t = (y + 0.5 - y1) / (y2 - y1)
                xints.append(x1 + t * (x2 - x1))
        if len(xints) < 2:
            continue
        xints.sort()
        # fill between pairs
        for k in range(0, len(xints) - 1, 2):
            xa = max(int(np.floor(xints[k])), 0)
            xb = min(int(np.ceil(xints[k + 1])), W - 1)
            if xb < xa:
                continue
            # density sum over [xa, xb] on row y via cumsum P
            d = P[y, xb] - (P[y, xa - 1] if xa > 0 else 0.0)
            # x-weighted sum via Q
            xd_a = (Q[y, xa - 1] if xa > 0 else 0.0)
            xd = (xa * P[y, xa - 1] - xd_a) if xa > 0 else 0.0
            # sum_{i=xa}^{xb} i * density[y,i] = xb*P[y,xb] - Q[y,xb] - (xa*P[y,xa-1] - Q[y,xa-1])
            sx = (xb * P[y, xb] - Q[y, xb]) - xd
            sum_d += d
            sum_xd += sx
            sum_yd += y * d

    if sum_d > 1e-12:
        return np.array([sum_xd / sum_d, sum_yd / sum_d])
    # fallback to geometric centroid
    return vertices.mean(axis=0)


# ---------------------------------------------------------------------------
# Lloyd relaxation
# ---------------------------------------------------------------------------

def lloyd_relax(points: np.ndarray, density: np.ndarray, n_iter: int = 10,
                rng: np.random.Generator | None = None) -> np.ndarray:
    """Run Lloyd relaxation: move each point to the weighted centroid of its
    Voronoi cell. A small jitter is added each iteration to avoid the
    regular hexagonal lattice artifact of pure CVT.
    """
    H, W = density.shape
    P = density.cumsum(axis=1)
    Q = P.cumsum(axis=1)
    pts = points.copy()
    for it in range(n_iter):
        vor = voronoi_filtered(pts, W, H)
        new_pts = []
        for region in vor.filtered_regions:
            verts = vor.vertices[region + [region[0]]]
            c = weighted_centroid_cumsum(verts, density, P, Q)
            new_pts.append(c)
        pts = np.array(new_pts)
        # small jitter to break hexagonal regularity
        if rng is not None:
            pts += rng.normal(0, 0.3, pts.shape)
        # clamp to image bounds
        pts[:, 0] = np.clip(pts[:, 0], 0, W - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, H - 1)
    return pts


# ---------------------------------------------------------------------------
# Stipple: full pipeline (density -> points -> radii)
# ---------------------------------------------------------------------------

def prune_overlapping(points: np.ndarray, radii: np.ndarray,
                      gap: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Greedy pruning: remove points whose circles overlap a kept point.
    Two points i,j overlap when dist(i,j) < radii[i] + radii[j] + gap.
    Iterates in random order; larger dots are kept preferentially by sorting
    so that small dark-area dots fill gaps between large bright-area dots.

    This is density-adaptive: small dots in dark regions can pack closely,
    large dots in bright regions are spaced apart — exactly the Kusama look.
    """
    if len(points) == 0:
        return points, radii
    tree = scipy.spatial.cKDTree(points)
    kept = np.ones(len(points), dtype=bool)
    # process larger dots first (they claim space), then smaller dots fill in
    order = np.argsort(-radii)
    rng = np.random.default_rng(0)
    # add slight shuffle within same-size buckets for natural look
    order = rng.permutation(order)
    order = order[np.argsort(-radii[order], kind='stable')]
    for i in order:
        if not kept[i]:
            continue
        # search radius = this dot's radius + max possible neighbor radius + gap
        search_r = radii[i] + radii.max() + gap
        neighbors = tree.query_ball_point(points[i], search_r)
        for j in neighbors:
            if j == i or not kept[j]:
                continue
            d = np.linalg.norm(points[i] - points[j])
            if d < radii[i] + radii[j] + gap:
                kept[j] = False
    return points[kept], radii[kept]


def prune_min_distance(points: np.ndarray, radii: np.ndarray,
                       min_dist: float) -> tuple[np.ndarray, np.ndarray]:
    """Greedy pruning: remove points that are closer than min_dist to an
    already-kept point. Prevents dots from overlapping into blobs."""
    if len(points) == 0:
        return points, radii
    tree = scipy.spatial.cKDTree(points)
    kept = np.ones(len(points), dtype=bool)
    # iterate in random order for fairness
    order = np.random.default_rng(0).permutation(len(points))
    for i in order:
        if not kept[i]:
            continue
        neighbors = tree.query_ball_point(points[i], min_dist)
        for j in neighbors:
            if j != i:
                kept[j] = False
    return points[kept], radii[kept]


def stipple(density: np.ndarray, n_points: int = 8000, n_iter: int = 8,
            r_min: float = 1.5, r_max: float = 5.0,
            gamma: float = 1.0, size_jitter: float = 0.15,
            pos_jitter: float = 0.4, min_dist: float = 0.0,
            overlap_gap: float = 0.5,
            seed: int | None = None):
    """Generate Kusama-style stipple points from a density field.

    Returns (points, radii):
        points : (n, 2) float (x, y) in image coords
        radii  : (n,)   float
    """
    rng = np.random.default_rng(seed)

    # 1. initialize via rejection sampling
    pts = rejection_sample(density, n_points, rng)

    # 2. Lloyd relaxation
    pts = lloyd_relax(pts, density, n_iter=n_iter, rng=rng)

    # 3. radius from local density.
    # Kusama convention: dark regions (high density) get LARGER dots that
    # dominate the composition, bright regions get smaller decorative dots.
    # This is the signature Kusama look: big bold dots in shadows, tiny dots
    # in highlights, with generous spacing (enforced by overlap pruning).
    xi = np.clip(pts[:, 0].astype(int), 0, density.shape[1] - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, density.shape[0] - 1)
    local_d = density[yi, xi]
    ld = local_d / max(local_d.max(), 1e-9)
    # forward mapping: high density -> large radius
    radii = r_min + (r_max - r_min) * ld

    # 4. size jitter (multiplicative)
    if size_jitter > 0:
        radii *= 1.0 + rng.normal(0, size_jitter, radii.shape)
        radii = np.clip(radii, 0.3, r_max * 1.5)

    # 5. position jitter
    if pos_jitter > 0:
        pts = pts + rng.normal(0, pos_jitter, pts.shape)

    # 6. overlap pruning (density-adaptive: small dark dots pack tight,
    #    large bright dots stay apart) — replaces fixed min_dist
    if overlap_gap >= 0:
        pts, radii = prune_overlapping(pts, radii, gap=overlap_gap)
    elif min_dist > 0:
        pts, radii = prune_min_distance(pts, radii, min_dist)

    return pts, radii
