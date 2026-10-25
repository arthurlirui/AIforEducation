"""oilrev CLI 入口（Canvas3D-v2）。

端到端：油画 + 线稿 → 三维场景图 → 视角可控 → 空间关系视频。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from ..common.config import load_settings
from .pipeline import run_pipeline

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
    """探测配置可用性。"""
    s = load_settings()
    click.echo(f"[aspect] {s.aspect} → {s.width}x{s.height}")
    click.echo(f"[fps] {s.fps}  [duration] {s.duration_sec}s")
    click.echo(f"[generator] {s.video_generator}")
    click.echo(f"[yolo] {s.yolo_model}")
    click.echo(f"[focal] {s.focal_length}")
    click.echo(f"[view_mode] {s.view_trajectory_mode}  [orbit] {s.view_orbit_angle_deg}°")
    click.echo(f"[spatial] relation_strength={s.spatial_relation_strength} mode={s.spatial_text_mode}")


@cli.command()
@click.argument("painting", type=click.Path(exists=True, path_type=Path))
@click.option("--lineart", "lineart", type=click.Path(path_type=Path), default=None,
              help="物体轮廓线稿（指引 stage3 重定位，可选）")
@click.option("--keyframe", "keyframes", multiple=True, type=click.Path(path_type=Path),
              help="关键帧线稿（可多个，指引 stage4 动画）")
@click.option("--project-id", "project_id", default=None, help="项目目录名")
@click.option("--no-comfyui", is_flag=True, default=False, help="跳过 ComfyUI，用 mock 生成")
@click.option("--resume", "resume", is_flag=True, default=False, help="从检查点恢复")
# v2 新增参数
@click.option("--view-mode", "view_mode",
              type=click.Choice(["manual", "orbit", "dolly", "crane", "auto_orbit"]),
              default=None, help="视角轨迹模式（默认 auto_orbit）")
@click.option("--orbit-angle", "orbit_angle", type=float, default=None,
              help="轨道扫过角度（度）")
@click.option("--focus-node", "focus_node", type=int, default=None,
              help="视角焦点节点 object_id")
@click.option("--spatial-prompt", "spatial_prompt", type=str, default="",
              help="空间关系视频的文本意图")
def run(painting, lineart, keyframes, project_id, no_comfyui, resume,
        view_mode, orbit_angle, focus_node, spatial_prompt):
    """一键端到端：油画 + 线稿 → 三维场景图 → 视角可控 → 空间关系视频。"""
    s = load_settings()
    if orbit_angle is not None:
        s.view_orbit_angle_deg = orbit_angle
    final = run_pipeline(
        s, painting,
        object_lineart_path=lineart,
        keyframe_lineart_paths=list(keyframes) if keyframes else None,
        project_id=project_id,
        resume_from_stage=-1 if resume else 0,
        use_comfyui=not no_comfyui,
        view_mode=view_mode,
        focus_node_id=focus_node,
        spatial_prompt=spatial_prompt,
    )
    click.echo(f"✅ 最终视频: {final}")


if __name__ == "__main__":
    cli()
