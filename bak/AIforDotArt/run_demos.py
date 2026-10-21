"""run_demos.py — 用复用输入图跑全部 6 种模式, 输出到 outputs/."""

import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from dotart import MODES  # noqa: E402

INPUT_DIR = ROOT.parent / "AIforPolkaDotsArt" / "inputs"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

DEMOS = [
    ("pumpkin.jpg", ["seurat", "kusama", "benday", "warp", "stipple", "vogel"]),
    ("cat.jpg",     ["seurat", "benday", "stipple"]),
    ("pepper.jpg",  ["kusama", "vogel"]),
]


def main() -> None:
    for fname, modes in DEMOS:
        src = Image.open(INPUT_DIR / fname).convert("RGB")
        src.thumbnail((480, 480))  # 保持演示轻量
        stem = Path(fname).stem
        for mode in modes:
            t = time.time()
            img = MODES[mode](src)
            out = OUT / f"{stem}_{mode}.png"
            img.save(out)
            print(f"[{stem:8s}] {mode:8s} -> {out.name}  ({time.time()-t:5.2f}s)")


if __name__ == "__main__":
    main()
