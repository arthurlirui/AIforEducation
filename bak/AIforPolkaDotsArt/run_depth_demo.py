"""
Demo: run the depth-aware Kusama polka dot pipeline on all input images
with multiple palettes. Generates side-by-side comparison outputs and
intermediate visualizations for the paper.
"""
import os
import time
import json
from depth_kusama import depth_kusama_polka

# Optimized parameters after iterative testing:
# - r_max=15 keeps large dots from dominating the composition
# - alpha=1.5 gives strong depth emphasis (near >> far)
# - sigma=0.15 adds organic variation (Kusama's hand-painted feel)
# - overlap_gap=3.0 prevents blob merging across layers
JOBS = [
    # (input, palette, n_points, r_max, alpha, sigma)
    ("inputs/pumpkin.jpg", "yellow_black", 25000, 14.0, 1.5, 0.15),
    ("inputs/pumpkin.jpg", "black_red",    25000, 14.0, 1.5, 0.15),
    ("inputs/cat.jpg",     "black_red",    25000, 14.0, 1.5, 0.15),
    ("inputs/cat.jpg",     "magenta_cyan", 25000, 14.0, 1.8, 0.18),
    ("inputs/pepper.jpg",  "white_red",    20000, 12.0, 1.3, 0.12),
    ("inputs/pepper.jpg",  "red_yellow",   20000, 12.0, 1.3, 0.12),
]

output_dir = "outputs/depth_demo"
os.makedirs(output_dir, exist_ok=True)
all_stats = []

for i, (inp, pal, n, rmax, alpha, sigma) in enumerate(JOBS):
    name = os.path.splitext(os.path.basename(inp))[0]
    out = os.path.join(output_dir, f"demo_{i+1}_{pal}_{name}.png")
    print(f"\n[{i+1}/{len(JOBS)}] {inp} -> {pal}")
    t0 = time.time()
    stats = depth_kusama_polka(
        inp, out,
        palette=pal,
        n_points=n,
        r_max=rmax,
        alpha=alpha,
        sigma=sigma,
        overlap_gap=4.0,
        save_intermediates=(i == 0),  # save intermediates for first job only
        output_dir=output_dir,
        seed=42,
    )
    all_stats.append(stats)

# save stats as JSON
stats_path = os.path.join(output_dir, "pipeline_stats.json")
with open(stats_path, "w") as f:
    json.dump(all_stats, f, indent=2)
print(f"\nPipeline stats saved to {stats_path}")
print("\nDepth-aware demo complete. All outputs in", output_dir)
