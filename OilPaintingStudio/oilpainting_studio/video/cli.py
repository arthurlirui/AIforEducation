"""oilpaint CLI：generate / render / compose / full / health。"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import click

from ..common.comfy.client import ComfyClient
from ..common.comfy.workflows import list_templates
from ..common.config import load_settings
from ..common.llm_client import LLMClient
from .pipeline.director import (
    load_script, new_project_dir, run_full, save_script,
    stage_compose, stage_generate, stage_render, write_meta,
)
from .pipeline.ffmpeg_tool import resolve_ffmpeg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


@click.group()
@click.version_option()
def cli() -> None:
    """OilPaintingVideo —— 经典油画风格剧情短视频生成器。"""


@cli.command()
def health() -> None:
    """探测 LLM / ComfyUI / ffmpeg 可用性与工作流模板。"""
    s = load_settings()

    # LLM
    llm_ok = bool(s.llm_api_key)
    click.echo(f"[LLM]      {'OK' if llm_ok else '缺少 API KEY'}  "
               f"base={s.llm_base_url}  model={s.llm_model}")

    # ComfyUI
    comfy = ComfyClient(s.comfy_url, s.concurrency)
    try:
        ok, info = asyncio.run(comfy.health())
        click.echo(f"[ComfyUI]  {'OK' if ok else '不可用'}  {s.comfy_url}  ({info})")
        if ok:
            # 探测模型节点
            try:
                info_obj = asyncio.run(comfy.object_info("CheckpointLoaderSimple"))
                ckpts = info_obj.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})
                click.echo(f"           可用 checkpoint 节点已就绪")
            except Exception as e:
                click.echo(f"           object_info 查询失败: {e}")
    finally:
        asyncio.run(comfy.aclose())

    # ffmpeg
    exe = resolve_ffmpeg(s.ffmpeg_path)
    click.echo(f"[ffmpeg]   {'OK' if exe else '未找到'}  {exe or '(请在 .env/settings 配置)'}")

    # 模板
    click.echo(f"[workflows] 内置模板: {', '.join(list_templates())}")
    if s.workflows_dir.exists():
        overrides = [p.stem for p in s.workflows_dir.glob('*.json')]
        if overrides:
            click.echo(f"            自定义覆盖: {', '.join(overrides)}")

    # 风格
    click.echo(f"[styles]   可用: {', '.join(s.styles.keys())}  (默认: {s.default_style})")
    click.echo(f"[aspect]   {s.aspect}  → {s.width}x{s.height}")


@cli.command()
@click.argument("topic")
@click.option("--style", "style", default=None, help="风格预设 key（见 styles.yaml）")
@click.option("--aspect", default=None, type=click.Choice(["9:16", "16:9"]), help="画幅")
@click.option("--duration", "duration", default=None, type=int, help="目标总时长（秒）")
@click.option("--project-id", "project_id", default=None, help="项目目录名（默认时间戳）")
def generate(topic, style, aspect, duration, project_id):
    """仅生成剧本 → output/<id>/screenplay.json。"""
    s = load_settings()
    pdir = new_project_dir(s.output_dir, project_id)
    llm = LLMClient(s.llm_base_url, s.llm_api_key, s.llm_model)

    async def _run():
        try:
            script = await stage_generate(llm, s, topic, style, aspect, duration, pdir)
            click.echo(f"剧本已生成: {pdir / 'screenplay.json'}")
            click.echo(f"  标题: {script.title}")
            click.echo(f"  场景: {len(script.scenes)}  镜头: {len(script.shots)}  "
                       f"时长: {script.total_duration_sec}s")
        finally:
            await llm.aclose()

    asyncio.run(_run())


@cli.command()
@click.argument("project_id")
def render(project_id):
    """渲染关键帧 + 视频片段（需已有 screenplay.json）。"""
    s = load_settings()
    pdir = s.output_dir / project_id
    if not pdir.exists():
        raise click.ClickException(f"项目目录不存在: {pdir}")
    script = load_script(pdir)
    comfy = ComfyClient(s.comfy_url, s.concurrency)

    async def _run():
        try:
            clips = await stage_render(comfy, s, script, pdir)
            click.echo(f"已渲染 {len(clips)} 个片段 → {pdir / 'clips'}")
        finally:
            await comfy.aclose()

    asyncio.run(_run())


@cli.command()
@click.argument("project_id")
def compose(project_id):
    """把已渲染片段剪辑成 final.mp4。"""
    s = load_settings()
    pdir = s.output_dir / project_id
    if not pdir.exists():
        raise click.ClickException(f"项目目录不存在: {pdir}")
    script = load_script(pdir)
    clips_dir = pdir / "clips"
    clips = sorted(clips_dir.glob("*.mp4"))
    if not clips:
        raise click.ClickException(f"未找到视频片段: {clips_dir}")
    final = stage_compose(s, script, clips, pdir)
    click.echo(f"成片已生成: {final}")


@cli.command()
@click.argument("topic")
@click.option("--style", "style", default=None, help="风格预设 key")
@click.option("--aspect", default=None, type=click.Choice(["9:16", "16:9"]), help="画幅")
@click.option("--duration", "duration", default=None, type=int, help="目标总时长（秒）")
@click.option("--i2v", "i2v", default=None, type=click.Choice(["ltx", "wan"]),
              help="默认图生视频模型（剧本中可逐镜头覆盖）")
@click.option("--project-id", "project_id", default=None, help="项目目录名")
def full(topic, style, aspect, duration, i2v, project_id):
    """一键端到端：剧本 → 关键帧 → 视频 → 剪辑。"""
    s = load_settings()
    if i2v:
        s.default_i2v_model = i2v
    if aspect:
        s.aspect = aspect
        # 重算分辨率
        if aspect == "9:16":
            s.width, s.height = 1080, 1920
        else:
            s.width, s.height = 1920, 1080

    final = asyncio.run(run_full(
        s, topic, style_key=style, aspect=aspect,
        target_duration_sec=duration, project_id=project_id,
    ))
    click.echo(f"✅ 成片已生成: {final}")


if __name__ == "__main__":
    cli()
