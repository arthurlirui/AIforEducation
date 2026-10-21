"""辅助：定位或提示安装 ffmpeg。

运行 `python tools/ensure_ffmpeg.py` 检查 ffmpeg 是否可用。
若系统 PATH 没有，会尝试从常见 conda 环境复制到项目 bin/ 目录。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    Path("D:/Code/anaconda3/Library/bin/ffmpeg.exe"),
    Path("D:/Code/miniconda3/Library/bin/ffmpeg.exe"),
    Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
]


def main() -> int:
    found = shutil.which("ffmpeg")
    if found:
        print(f"[OK] ffmpeg 已在 PATH: {found}")
        return 0

    for c in CANDIDATES:
        if c.exists():
            print(f"[OK] 发现 ffmpeg: {c}")
            print("建议在 .env 设置:")
            print(f"  FFMPEG_PATH={c}")
            return 0

    print("[MISS] 未找到 ffmpeg。请任选一种方式安装：")
    print("  1) conda install -c conda-forge ffmpeg")
    print("  2) 从 https://www.gyan.dev/ffmpeg/builds/ 下载，解压后在 .env 设置 FFMPEG_PATH")
    print("  3) winget install Gyan.FFmpeg")
    return 1


if __name__ == "__main__":
    sys.exit(main())
