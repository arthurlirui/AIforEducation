"""导演编排：剧本 → 关键帧 → 视频片段 → 剪辑成片。

负责项目目录管理、产物持久化、进度与错误记录。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from ...common.comfy.client import ComfyClient
from ...common.config import Settings
from ...common.llm_client import LLMClient
from ..screenplay.generator import generate_script
from ..screenplay.schemas import Script
from .animate import render_clip
from .edit import compose_video
from .keyframe import render_keyframe

logger = logging.getLogger(__name__)


def new_project_dir(output_dir: Path, project_id: str | None = None) -> Path:
    """创建/复用项目输出目录。"""
    pid = project_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    d = output_dir / pid
    (d / "keyframes").mkdir(parents=True, exist_ok=True)
    (d / "clips").mkdir(parents=True, exist_ok=True)
    return d


def save_script(script: Script, project_dir: Path) -> Path:
    p = project_dir / "screenplay.json"
    p.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_script(project_dir: Path) -> Script:
    p = project_dir / "screenplay.json"
    if not p.exists():
        raise FileNotFoundError(f"项目目录下未找到 screenplay.json: {project_dir}")
    return Script.model_validate_json(p.read_text(encoding="utf-8"))


async def stage_generate(
    client: LLMClient, settings: Settings, topic: str,
    style_key: str | None, aspect: str | None,
    target_duration_sec: int | None, project_dir: Path,
) -> Script:
    script, info = await generate_script(
        client, settings, topic,
        style_key=style_key, aspect=aspect, target_duration_sec=target_duration_sec,
    )
    if script is None:
        raise RuntimeError(f"剧本生成失败: {info}")
    save_script(script, project_dir)
    logger.info("剧本生成完成: %s — %s", script.title, info)
    return script


def _shot_durations(clips: list[Path]) -> list[float]:
    """用 ffprobe 量测各片段实际时长（秒）。量不到时记 -1。

    I2V 帧数取整（n|1）会让实际时长与剧本 duration_sec 有出入,
    记录实际值供字幕时间轴校对（V5 已知漂移的 meta 侧补偿）。
    """
    from .ffmpeg_tool import probe_duration
    out: list[float] = []
    for c in clips:
        try:
            d = probe_duration("", c)
            out.append(round(d, 2) if d else -1.0)
        except Exception:
            out.append(-1.0)
    return out


async def stage_render(
    comfy: ComfyClient, settings: Settings, script: Script, project_dir: Path,
) -> list[Path]:
    """渲染所有镜头的关键帧 + 视频。返回片段路径列表（按镜头顺序）。

    注: 当前为串行渲染（逐镜头 await）。Settings.concurrency 与
    ComfyClient._sem 仅在并发调用 run() 时限流, 本函数未启用并发。
    """
    style = settings.style(script.style)
    clips: list[Path] = []
    for shot in script.shots:
        prefix = f"shot_{shot.index:03d}"
        # 关键帧
        kf = await render_keyframe(
            comfy, settings, shot, style,
            save_dir=project_dir / "keyframes", out_prefix=prefix,
        )
        logger.info("镜头 %d 关键帧: %s", shot.index, kf)
        # 图生视频
        clip = await render_clip(
            comfy, settings, shot, kf,
            save_dir=project_dir / "clips", out_prefix=prefix,
        )
        logger.info("镜头 %d 视频: %s", shot.index, clip)
        clips.append(clip)
    return clips


def stage_compose(
    settings: Settings, script: Script, clips: list[Path], project_dir: Path,
) -> Path:
    return compose_video(settings, script, clips, project_dir)


def write_meta(project_dir: Path, meta: dict) -> Path:
    p = project_dir / "meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


async def run_full(
    settings: Settings, topic: str,
    style_key: str | None = None, aspect: str | None = None,
    target_duration_sec: int | None = None, project_id: str | None = None,
) -> Path:
    """一键端到端。返回成片路径。

    各阶段失败时把错误写入 meta["stages"] 后 re-raise（保证失败 run 的
    项目目录里也有剧本阶段记录, 便于排障）。
    """
    project_dir = new_project_dir(settings.output_dir, project_id)
    t0 = time.time()
    meta: dict = {"topic": topic, "project_id": project_dir.name, "stages": {}}

    # LLM
    llm = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    comfy = ComfyClient(settings.comfy_url, settings.concurrency)
    stage = "generate"
    try:
        # 1. 剧本
        ts = time.time()
        script = await stage_generate(
            llm, settings, topic, style_key, aspect, target_duration_sec, project_dir,
        )
        meta["stages"]["generate"] = {"ok": True, "sec": round(time.time() - ts, 1),
                                      "shots": len(script.shots)}

        # 2. 渲染
        stage = "render"
        ts = time.time()
        clips = await stage_render(comfy, settings, script, project_dir)
        meta["stages"]["render"] = {"ok": True, "sec": round(time.time() - ts, 1),
                                    "clips": len(clips),
                                    "shot_durations": _shot_durations(clips)}

        # 3. 剪辑
        stage = "compose"
        ts = time.time()
        final = stage_compose(settings, script, clips, project_dir)
        meta["stages"]["compose"] = {"ok": True, "sec": round(time.time() - ts, 1),
                                     "final": str(final)}
    except Exception as e:
        # 失败也要落盘 meta, 记录失败阶段与原因 (docstring 承诺的"错误记录")
        meta["stages"][stage] = {"ok": False, "error": str(e)}
        meta["total_sec"] = round(time.time() - t0, 1)
        write_meta(project_dir, meta)
        raise
    finally:
        await llm.aclose()
        await comfy.aclose()

    meta["total_sec"] = round(time.time() - t0, 1)
    write_meta(project_dir, meta)
    return final
