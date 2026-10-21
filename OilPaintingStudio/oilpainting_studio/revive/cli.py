"""oilrev CLI 入口。"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from ..common.comfy.client import ComfyClient
from ..common.config import load_settings
from ..video.pipeline.director import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


@click.group()
def cli() -> None:
    """OilPaintingRevive —— 融合 3D 信息的手绘线稿引导图像视频生成框架。"""


@cli.command()
def health() -> None:
    """探测 ComfyUI 可用性。"""
    s = load_settings()
    client = ComfyClient(s.comfy_url, s.concurrency)
    try:
        ok, info = asyncio.run(client.health())
        click.echo(f"[ComfyUI] {'OK' if ok else '不可用'}  {s.comfy_url}  ({info})")
    finally:
        asyncio.run(client.aclose())
    click.echo(f"[aspect] {s.aspect} → {s.width}x{s.height}")
    click.echo(f"[fps] {s.fps}  [duration] {s.duration_sec}s")
    click.echo(f"[generator] {s.video_generator}")
    click.echo(f"[yolo] {s.yolo_model}")


@cli.command()
@click.argument("painting", type=click.Path(exists=True, path_type=Path))
@click.option("--lineart", "lineart", type=click.Path(path_type=Path), default=None,
              help="物体轮廓线稿（指引模块 3 重定位）")
@click.option("--keyframe", "keyframes", multiple=True, type=click.Path(path_type=Path),
              help="关键帧线稿（可多个，指引模块 4 动画）")
@click.option("--project-id", "project_id", default=None, help="项目目录名")
@click.option("--no-comfyui", is_flag=True, default=False, help="跳过 ComfyUI，用 mock 生成")
@click.option("--resume", "resume", is_flag=True, default=False, help="从检查点恢复")
def run(painting, lineart, keyframes, project_id, no_comfyui, resume):
    """一键端到端：油画 + 线稿 → 动态视频。"""
    s = load_settings()
    final = run_pipeline(
        s, painting,
        object_lineart_path=lineart,
        keyframe_lineart_paths=list(keyframes) if keyframes else None,
        project_id=project_id,
        resume_from_stage=0 if not resume else -1,
        use_comfyui=not no_comfyui,
    )
    click.echo(f"✅ 最终视频: {final}")


if __name__ == "__main__":
    cli()
