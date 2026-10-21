"""
Demo: render all test images in multiple Kusama palettes.
Final tuned: forward radius mapping (dark=large dots), overlap_gap=2.0, hard edges.
"""
import time
from kusama import kusama_polka

# (input, palette, n_points, n_iter, r_min, r_max, gamma, overlap_gap, target_long_edge)
JOBS = [
    ("inputs/sphere.png",     "black_red",    20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
    ("inputs/pumpkin.png",    "yellow_black", 20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
    ("inputs/portrait.png",   "white_red",    20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
    ("inputs/still_life.png", "red_white",    20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
    ("inputs/pumpkin.png",    "black_red",    20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
    ("inputs/sphere.png",     "yellow_red",   20000, 10, 1.0, 5.0, 1.2, 2.0, 900),
]

for i, (inp, pal, n, it, rmin, rmax, gm, og, tle) in enumerate(JOBS):
    out = f"outputs/demo_{i+1}_{pal}_{inp.split('/')[-1].split('.')[0]}.png"
    t0 = time.time()
    kusama_polka(inp, out, palette=pal, n_points=n, n_iter=it,
                 r_min=rmin, r_max=rmax, gamma=gm, overlap_gap=og,
                 target_long_edge=tle, seed=42)
    print(f"  [{i+1}/{len(JOBS)}] {time.time()-t0:.1f}s")

print("\nDemo complete. All outputs in outputs/")
