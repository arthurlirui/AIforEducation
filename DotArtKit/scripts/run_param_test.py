"""
Parameter sweep test for the depth-aware Kusama polka dot pipeline.

Systematically varies the key algorithmic parameters and saves the
generated images along with a summary report (JSON + CSV) and a
contact-sheet montage for visual comparison.

Key parameters tested:
    - alpha   : depth-to-radius falloff exponent (0.5, 1.0, 1.5, 2.0, 3.0)
    - sigma   : radius randomization noise std (0.0, 0.05, 0.10, 0.15, 0.25)
    - r_max   : maximum dot radius in px (8, 12, 14, 18, 22)
    - beta    : depth-to-density exponent (0.3, 0.6, 1.0, 1.5)
    - n_points: initial sampling point count (10000, 20000, 30000, 50000)
    - palette : color scheme (black_red, yellow_black, white_red, magenta_cyan)
    - overlap_gap: dot spacing gap (2.0, 4.0, 6.0)
    - ablation: component toggles (no depth-emphasis, no edges, no bg fill,
                no semantic, no foreground normalization)

Usage:
    python run_param_test.py                          # full sweep (slow)
    python run_param_test.py --input inputs/pumpkin.jpg  # specific image
    python run_param_test.py --quick                   # reduced sweep
    python run_param_test.py --group alpha             # test one parameter group
"""
import os
import sys
import json
import time
import csv
import argparse
import itertools
from typing import Optional

import cv2
import numpy as np

from depth_kusama import depth_kusama_polka, DEPTH_PALETTES


# ---------------------------------------------------------------------------
# Parameter test groups
# ---------------------------------------------------------------------------

# Base configuration (sensible defaults from iterative tuning)
BASE = dict(
    n_points=25000,
    r_max=14.0,
    alpha=1.5,
    beta=0.6,
    sigma=0.15,
    gamma=1.2,
    overlap_gap=4.0,
    percentile_clip=2.0,
    multi_scale=True,
    edge_enhance=True,
    bg_fill=True,
    semantic_aware=True,
    seed=42,
)

# Each group varies ONE parameter while keeping the rest at BASE
TEST_GROUPS = {
    "alpha": {
        "param": "alpha",
        "values": [0.5, 1.0, 1.5, 2.0, 3.0],
        "label": "depth falloff exponent",
    },
    "sigma": {
        "param": "sigma",
        "values": [0.0, 0.05, 0.10, 0.15, 0.25],
        "label": "radius noise std",
    },
    "r_max": {
        "param": "r_max",
        "values": [8.0, 12.0, 14.0, 18.0, 22.0],
        "label": "max dot radius (px)",
    },
    "beta": {
        "param": "beta",
        "values": [0.3, 0.6, 1.0, 1.5],
        "label": "depth-density exponent",
    },
    "n_points": {
        "param": "n_points",
        "values": [10000, 20000, 30000, 50000],
        "label": "initial point count",
    },
    "overlap_gap": {
        "param": "overlap_gap",
        "values": [2.0, 4.0, 6.0, 8.0],
        "label": "overlap gap (px)",
    },
    "palette": {
        "param": "palette",
        "values": list(DEPTH_PALETTES.keys()),
        "label": "color palette",
    },
    "ablation": {
        "param": None,  # handled specially
        "values": [
            ("full_pipeline", {}),
            ("no_depth_emphasis", {"multi_scale": False}),
            ("no_edge_enhance", {"edge_enhance": False}),
            ("no_bg_fill", {"bg_fill": False}),
            ("no_semantic", {"semantic_aware": False}),
            ("no_fg_norm", {"semantic_aware": False}),  # disables fg normalization
        ],
        "label": "component ablation",
    },
}

# Quick mode: fewer values per group for faster testing
QUICK_VALUES = {
    "alpha": [0.5, 1.5, 3.0],
    "sigma": [0.0, 0.15, 0.25],
    "r_max": [8.0, 14.0, 22.0],
    "beta": [0.3, 0.6, 1.5],
    "n_points": [10000, 30000],
    "overlap_gap": [2.0, 4.0, 8.0],
    "palette": list(DEPTH_PALETTES.keys()),
    "ablation": [
        ("full_pipeline", {}),
        ("no_depth_emphasis", {"multi_scale": False}),
        ("no_edge_enhance", {"edge_enhance": False}),
        ("no_bg_fill", {"bg_fill": False}),
        ("no_semantic", {"semantic_aware": False}),
    ],
}


# ---------------------------------------------------------------------------
# Quality analysis
# ---------------------------------------------------------------------------

def analyze_output(image_path: str) -> dict:
    """Analyze a generated polka dot image for quality metrics."""
    img = cv2.imread(image_path)
    if img is None:
        return {"error": "cannot read image"}
    H, W = img.shape[:2]

    # Background color from corner
    bg = img[0, 0].copy()
    diff = np.abs(img.astype(int) - bg.astype(int)).sum(axis=2)
    fg_mask = (diff > 30).astype(np.uint8)

    # Connected components
    n_cc, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    if n_cc <= 1:
        return {
            "image_size": (W, H),
            "n_dots": 0,
            "max_blob_pct": 0.0,
            "coverage_pct": 0.0,
            "mean_dot_size": 0.0,
            "n_blobs_over_2000": 0,
        }
    areas = stats[1:, cv2.CC_STAT_AREA]

    # Equivalent radii
    eq_radii = np.sqrt(areas / np.pi)

    return {
        "image_size": (W, H),
        "n_dots": int(n_cc - 1),
        "max_blob_pct": round(float(100 * areas.max() / (H * W)), 2),
        "coverage_pct": round(float(100 * fg_mask.mean()), 1),
        "mean_dot_size": round(float(areas.mean()), 1),
        "median_dot_size": round(float(np.median(areas)), 1),
        "radius_mean": round(float(eq_radii.mean()), 2),
        "radius_median": round(float(np.median(eq_radii)), 2),
        "radius_p95": round(float(np.percentile(eq_radii, 95)), 2),
        "radius_max": round(float(eq_radii.max()), 2),
        "n_blobs_over_2000": int(np.sum(areas > 2000)),
        "n_blobs_over_5000": int(np.sum(areas > 5000)),
    }


# ---------------------------------------------------------------------------
# Contact sheet (montage)
# ---------------------------------------------------------------------------

def make_contact_sheet(image_paths: list, labels: list, output_path: str,
                       cols: int = 3, cell_size: int = 300,
                       label_height: int = 30):
    """Create a labeled contact sheet of generated images."""
    n = len(image_paths)
    rows = (n + cols - 1) // cols
    sheet_w = cols * cell_size
    sheet_h = rows * (cell_size + label_height)
    sheet = np.full((sheet_h, sheet_w, 3), 255, np.uint8)

    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, (path, label) in enumerate(zip(image_paths, labels)):
        img = cv2.imread(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = cell_size / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
        ph, pw = img.shape[:2]

        r, c = i // cols, i % cols
        y0 = r * (cell_size + label_height)
        x0 = c * cell_size
        # center image in cell
        yoff = y0 + label_height + (cell_size - ph) // 2
        xoff = x0 + (cell_size - pw) // 2
        sheet[yoff:yoff + ph, xoff:xoff + pw] = img

        # draw label
        cv2.putText(sheet, label, (x0 + 5, y0 + 20),
                    font, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    cv2.imwrite(output_path, sheet, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(f"  Contact sheet saved: {output_path}")


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_group(group_name: str, input_path: str, output_dir: str,
              quick: bool = False, palette: str = "black_red") -> list:
    """Run parameter sweep for one test group."""
    group = TEST_GROUPS[group_name]
    param = group["param"]
    values = QUICK_VALUES.get(group_name, group["values"]) if quick else group["values"]

    group_dir = os.path.join(output_dir, group_name)
    os.makedirs(group_dir, exist_ok=True)

    results = []
    image_paths = []
    labels = []

    for i, val in enumerate(values):
        # Build parameter override
        overrides = dict(BASE)
        overrides["palette"] = palette

        if group_name == "ablation":
            label_name, toggle = val
            overrides.update(toggle)
            value_str = label_name
        else:
            overrides[param] = val
            value_str = str(val)

        # Output filename
        safe_val = value_str.replace(".", "p").replace(" ", "_")
        out_name = f"{group_name}_{i:02d}_{safe_val}.png"
        out_path = os.path.join(group_dir, out_name)

        print(f"  [{group_name}] {param or 'toggle'}={value_str} ...", end=" ", flush=True)
        t0 = time.time()

        try:
            stats = depth_kusama_polka(input_path, out_path,
                                       output_dir=group_dir,
                                       save_intermediates=False,
                                       **overrides)
            quality = analyze_output(out_path)

            result = {
                "group": group_name,
                "param": param,
                "value": value_str,
                "output": out_path,
                "pipeline_time_s": round(stats["timing"]["total"], 1),
                "depth_range_m": stats["depth_range_m"],
                "n_total_dots": stats["n_total_dots"],
                "n_fine_dots": stats["n_fine_dots"],
                "n_depth_emphasis_dots": stats["n_depth_emphasis_dots"],
                "radius_range_px": stats["radius_range"],
                "fg_ratio": round(stats["fg_pixel_ratio"], 3),
                **quality,
            }
            results.append(result)
            image_paths.append(out_path)
            labels.append(f"{param or 'toggle'}={value_str}" if group_name != "ablation"
                          else value_str)
            print(f"done ({time.time()-t0:.1f}s, {quality['n_dots']} dots, "
                  f"max_blob={quality['max_blob_pct']}%)")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "group": group_name,
                "param": param,
                "value": value_str,
                "output": out_path,
                "error": str(e),
            })

    # Save contact sheet
    if image_paths:
        sheet_path = os.path.join(group_dir, f"contact_sheet_{group_name}.png")
        make_contact_sheet(image_paths, labels, sheet_path, cols=min(len(image_paths), 5))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Parameter sweep test for depth-aware Kusama polka dot pipeline")
    parser.add_argument("--input", default="inputs/pumpkin.jpg",
                        help="input image path")
    parser.add_argument("--output-dir", default="outputs/param_test",
                        help="output directory for test results")
    parser.add_argument("--quick", action="store_true",
                        help="reduced parameter sweep for faster testing")
    parser.add_argument("--group", default=None,
                        help="test only one parameter group (alpha, sigma, r_max, beta, "
                             "n_points, overlap_gap, palette, ablation)")
    parser.add_argument("--palette", default="black_red",
                        help="color palette to use (except when testing palette group)")
    args = parser.parse_args()

    # Validate input
    if not os.path.exists(args.input):
        print(f"Error: input image not found: {args.input}")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Determine which groups to run
    if args.group:
        if args.group not in TEST_GROUPS:
            print(f"Error: unknown group '{args.group}'. "
                  f"Available: {', '.join(TEST_GROUPS.keys())}")
            sys.exit(1)
        groups_to_run = [args.group]
    else:
        groups_to_run = list(TEST_GROUPS.keys())

    all_results = []
    t_start = time.time()

    for group_name in groups_to_run:
        print(f"\n{'='*60}")
        print(f"Testing group: {group_name} ({TEST_GROUPS[group_name]['label']})")
        print(f"{'='*60}")
        results = run_group(group_name, args.input, args.output_dir,
                            quick=args.quick, palette=args.palette)
        all_results.extend(results)

    t_total = time.time() - t_start

    # Save JSON summary
    json_path = os.path.join(args.output_dir, "param_test_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "input": args.input,
            "palette": args.palette,
            "quick_mode": args.quick,
            "total_runs": len(all_results),
            "total_time_s": round(t_total, 1),
            "results": all_results,
        }, f, indent=2)
    print(f"\nResults JSON saved: {json_path}")

    # Save CSV summary
    csv_path = os.path.join(args.output_dir, "param_test_results.csv")
    if all_results:
        fields = ["group", "param", "value", "n_dots", "max_blob_pct",
                  "coverage_pct", "radius_mean", "radius_max",
                  "n_blobs_over_2000", "n_total_dots", "n_depth_emphasis_dots",
                  "pipeline_time_s", "output"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for r in all_results:
                writer.writerow(r)
        print(f"Results CSV saved: {csv_path}")

    # Print summary table
    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(all_results)} runs in {t_total:.0f}s")
    print(f"{'='*60}")
    print(f"{'Group':<15} {'Value':<20} {'Dots':>6} {'MaxBlob':>8} {'Cov%':>6} "
          f"{'R_mean':>7} {'R_max':>7} {'Time':>6}")
    print("-" * 80)
    for r in all_results:
        if "error" in r:
            print(f"{r['group']:<15} {r['value']:<20} ERROR: {r['error'][:30]}")
        else:
            print(f"{r['group']:<15} {r['value']:<20} {r.get('n_dots',0):>6} "
                  f"{r.get('max_blob_pct',0):>7.2f}% {r.get('coverage_pct',0):>5.1f}% "
                  f"{r.get('radius_mean',0):>7.2f} {r.get('radius_max',0):>7.2f} "
                  f"{r.get('pipeline_time_s',0):>5.1f}s")


if __name__ == "__main__":
    main()
