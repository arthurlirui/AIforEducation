"""run_demos.py — 统一 demo: 跑全部 6 种纯 numpy 流派 + 草间基础版.

用法::

    cd DotArtKit
    python scripts/run_demos.py                 # 默认跑 inputs/ 所有图
    python scripts/run_demos.py --input pumpkin.jpg  # 指定单张
    python scripts/run_demos.py --modes seurat,benday  # 指定模式
    python scripts/run_demos.py --include-kusama-basic  # 加上草间基础版 (较慢)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image
from dotartkit import generate, list_pure_modes, mode_info


def main() -> int:
    p = argparse.ArgumentParser(description="DotArtKit 统一 demo")
    p.add_argument("--input", default=None, help="指定单张图 (默认 inputs/ 所有)")
    p.add_argument("--input-dir", default=str(ROOT / "inputs"), help="输入目录")
    p.add_argument("--output-dir", default=str(ROOT / "outputs" / "demo"), help="输出目录")
    p.add_argument("--modes", default=None, help="逗号分隔模式, 默认全部纯 numpy")
    p.add_argument("--include-kusama-basic", action="store_true",
                   help="加上 kusama_basic (Voronoi, 较慢)")
    p.add_argument("--long-edge", type=int, default=480, help="下采样长边")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 收集输入
    if args.input:
        inputs = [Path(args.input)]
    else:
        in_dir = Path(args.input_dir)
        inputs = sorted(list(in_dir.glob("*.jpg")) + list(in_dir.glob("*.png")))
    if not inputs:
        print(f"[demo] 未找到输入图: {args.input_dir}")
        return 1

    # 收集模式
    if args.modes:
        modes = args.modes.split(",")
    else:
        modes = list_pure_modes()
        if args.include_kusama_basic:
            modes = modes + ["kusama_basic"]

    print(f"[demo] {len(inputs)} 图 × {len(modes)} 模式 → {out_dir}")
    print(f"       模式: {', '.join(modes)}\n")

    total = 0
    for inp in inputs:
        img = Image.open(inp).convert("RGB")
        if max(img.size) > args.long_edge:
            img.thumbnail((args.long_edge, args.long_edge))
        stem = inp.stem
        for mode in modes:
            t = time.time()
            try:
                out = generate(mode, img)
                out_path = out_dir / f"{stem}_{mode}.png"
                out.save(out_path)
                dt = time.time() - t
                print(f"[{stem:10s}] {mode:14s} -> {out_path.name}  ({dt:5.2f}s)")
                total += 1
            except Exception as e:
                print(f"[{stem:10s}] {mode:14s} FAILED: {e}")
    print(f"\n[demo] 完成: {total} 张输出 → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
