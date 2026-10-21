"""ffmpeg 工具：定位可执行文件并封装常用命令。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ...common.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


def resolve_ffmpeg(ffmpeg_path: str = "") -> str:
    """返回 ffmpeg 可执行文件路径；找不到返回空串。"""
    if ffmpeg_path and Path(ffmpeg_path).exists():
        return ffmpeg_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    # 常见 conda 路径
    candidates = [
        PROJECT_ROOT / "bin" / "ffmpeg.exe",
        PROJECT_ROOT / "bin" / "ffmpeg",
        Path("D:/Code/anaconda3/Library/bin/ffmpeg.exe"),
        Path("D:/Code/miniconda3/Library/bin/ffmpeg.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def run_ffmpeg(args: list[str], ffmpeg_path: str = "") -> tuple[bool, str]:
    """运行 ffmpeg 命令，返回 (ok, stderr_tail)。"""
    exe = ffmpeg_path or resolve_ffmpeg()
    if not exe:
        return False, "ffmpeg 未找到，请安装或配置 FFMPEG_PATH / settings.ffmpeg_path"
    cmd = [exe, *args]
    logger.info("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-800:]
        return False, tail
    return True, ""


def probe_duration(ffprobe_path: str, video: Path) -> float:
    """用 ffprobe 读视频时长（秒）。失败返回 0。"""
    exe = ffprobe_path or resolve_ffmpeg().replace("ffmpeg", "ffprobe")
    if not exe or not Path(exe).exists():
        return 0.0
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0
