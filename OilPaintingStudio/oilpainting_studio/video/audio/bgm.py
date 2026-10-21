"""背景音乐选取/混音：按风格情绪匹配 assets/bgm 下的免版权音乐。

assets/bgm/ 按 <mood>.mp3 命名（如 gentle.mp3 / solemn.mp3 / epic.mp3 / calm.mp3）。
缺失时跳过 BGM，仅输出无声视频。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def pick_bgm(assets_dir: Path, mood: str) -> Path | None:
    """按情绪匹配 BGM 文件。"""
    bgm_dir = assets_dir / "bgm"
    if not bgm_dir.exists():
        return None
    for ext in (".mp3", ".wav", ".m4a", ".aac"):
        p = bgm_dir / f"{mood}{ext}"
        if p.exists():
            return p
    # 退而求其次：取目录下任意一个
    for ext in (".mp3", ".wav", ".m4a"):
        files = list(bgm_dir.glob(f"*{ext}"))
        if files:
            return files[0]
    return None
