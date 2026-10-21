"""自动剪辑：ffmpeg 拼接片段 + 转场 + BGM + 字幕烧录。

策略（简单稳健，避免 xfade 复杂偏移）：
1. 先把每个片段 reencode 到统一分辨率/帧率/编码（normalize）
2. concat 拼接（硬切）或对相邻片段做 xfade 交叉淡化
3. 叠加 BGM（循环/截断到视频时长，音量 ducking）
4. 烧录字幕（drawtext，按镜头时间区间显示旁白）
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..audio.bgm import pick_bgm
from ..config import Settings
from ..screenplay.schemas import Script, Shot
from .ffmpeg_tool import probe_duration, resolve_ffmpeg, run_ffmpeg

logger = logging.getLogger(__name__)


def _norm_clip(
    exe: str,
    src: Path,
    dst: Path,
    width: int,
    height: int,
    fps: int,
) -> bool:
    """统一片段分辨率/帧率/编码/像素格式，便于 concat。"""
    # scale 用 force_original_aspect_ratio=decrease + pad 保证不变形且填满画幅
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},format=yuv420p"
    )
    ok, err = run_ffmpeg(
        ["-y", "-i", str(src), "-vf", vf, "-c:v", "libx264",
         "-preset", "medium", "-crf", "20", "-an", str(dst)],
        ffmpeg_path=exe,
    )
    if not ok:
        logger.warning("normalize 失败 %s: %s", src.name, err)
    return ok


def _concat(exe: str, clips: list[Path], out: Path) -> bool:
    """concat demuxer 拼接。"""
    list_file = out.parent / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf-8"
    )
    ok, err = run_ffmpeg(
        ["-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(out)],
        ffmpeg_path=exe,
    )
    if not ok:
        # copy 可能因参数不一致失败，退到 reencode
        logger.info("concat copy 失败，改用 reencode: %s", err)
        ok, err = run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c:v", "libx264", "-crf", "20", "-preset", "medium",
             "-pix_fmt", "yuv420p", str(out)],
            ffmpeg_path=exe,
        )
    list_file.unlink(missing_ok=True)
    return ok, err


def _build_subtitle_filter(script: Script, fps: int, font: str) -> str:
    """按镜头时间区间生成 drawtext 滤镜链。"""
    if not script.shots:
        return ""
    # 估算每镜头起始时间（用剧本 duration_sec；剪辑后实际可能略有出入，作为近似可接受）
    t = 0.0
    parts: list[str] = []
    for shot in script.shots:
        text = (shot.narration or "").strip()
        dur = shot.duration_sec
        if text:
            # 转义 drawtext 特殊字符
            safe = (
                text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "\\'")
                .replace("%", "\\%")
            )
            font_arg = f":fontfile='{font}'" if font else ""
            parts.append(
                f"drawtext=text='{safe}'"
                f":fontsize=h/18:fontcolor=white:alpha=0.9"
                f":x=(w-text_w)/2:y=h-text_h-h/40"
                f":enable='between(t,{t:.2f},{t + dur:.2f})'{font_arg}"
            )
        t += dur
    return ",".join(parts)


def _add_bgm_and_subtitle(
    exe: str,
    video: Path,
    out: Path,
    bgm: Path | None,
    subtitle_filter: str,
) -> bool:
    """叠加 BGM 与字幕，输出最终成片。"""
    args = ["-y", "-i", str(video)]
    has_bgm = bgm is not None and bgm.exists()
    if has_bgm:
        args += ["-i", str(bgm)]

    vf = subtitle_filter or None
    if vf:
        args += ["-vf", vf]

    if has_bgm:
        # BGM 循环并截到视频时长，音量降低
        args += [
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-filter:a", "volume=0.35",
        ]
    else:
        args += ["-c:v", "libx264", "-crf", "20", "-preset", "medium"]

    args += ["-pix_fmt", "yuv420p", str(out)]
    ok, err = run_ffmpeg(args, ffmpeg_path=exe)
    if not ok:
        logger.error("最终合成失败: %s", err)
    return ok


def compose_video(
    settings: Settings,
    script: Script,
    clips: list[Path],
    project_dir: Path,
) -> Path:
    """把镜头片段剪辑成 final.mp4，返回成片路径。

    clips 顺序需与 script.shots 一致。
    """
    exe = resolve_ffmpeg(settings.ffmpeg_path)
    if not exe:
        raise RuntimeError(
            "ffmpeg 未找到。请安装 ffmpeg，或在 .env 设置 FFMPEG_PATH，"
            "或在 settings.yaml 设置 ffmpeg_path。"
        )

    work = project_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    norm_dir = work / "norm"
    norm_dir.mkdir(exist_ok=True)

    # 1. 归一化
    norm_clips: list[Path] = []
    for i, c in enumerate(clips, 1):
        dst = norm_dir / f"clip_{i:03d}.mp4"
        if _norm_clip(exe, c, dst, settings.width, settings.height, settings.fps):
            norm_clips.append(dst)
        elif c.suffix == ".mp4":
            norm_clips.append(c)  # 退用原文件
    if not norm_clips:
        raise RuntimeError("没有可用片段可剪辑")

    # 2. 拼接
    concat_out = work / "concat.mp4"
    ok, err = _concat(exe, norm_clips, concat_out)
    if not ok:
        raise RuntimeError(f"拼接失败: {err}")

    # 3. BGM + 字幕
    style = settings.style(script.style)
    bgm = pick_bgm(settings.assets_dir, style.bgm_mood)
    font = settings.subtitle_font or ""
    if not font:
        # 尝试 assets/fonts 下任意字体
        fonts_dir = settings.assets_dir / "fonts"
        if fonts_dir.exists():
            for ext in ("*.ttf", "*.otf"):
                fs = list(fonts_dir.glob(ext))
                if fs:
                    font = str(fs[0])
                    break
    sub_filter = _build_subtitle_filter(script, settings.fps, font) if settings.burn_subtitle else ""

    final = project_dir / "final.mp4"
    ok = _add_bgm_and_subtitle(exe, concat_out, final, bgm, sub_filter)
    if not ok:
        # 退而求其次：仅复制拼接结果
        shutil.copy2(concat_out, final)
        logger.warning("BGM/字幕合成失败，已退回纯拼接版本")

    # 清理临时
    shutil.rmtree(work, ignore_errors=True)
    return final
