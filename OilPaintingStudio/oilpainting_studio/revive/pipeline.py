"""Revive 管线编排：油画 + 线稿 → 三维场景图 → 视角可控 → 空间关系视频。

Canvas3D-v2 完整流程:
  stage1 (PaintParse)   分割 + 深度 + 层序
  stage2 (MonoSplat)    物体级 3DGS + 度量重缩放
  stage6 (SceneGraph3D) 三维场景图构建                  ← v2 新增
  stage3 (SketchComp)   线稿引导重定位 + 填色补缺（可选）
  stage7 (ViewCtrl)     视角可控新视角渲染              ← v2 新增
  stage8 (SpatialFlow)  空间关系可控视频生成            ← v2 新增
  stage5 (ArtiFlow)     最终视频合成

支持检查点恢复：每个 stage 完成后写 stageN.json，resume 时跳过已完成的 stage。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..common.config import Settings, load_settings
from .schemas import (
    SpatialEditSpec,
    Stage1Output,
    Stage2Output,
    Stage3Output,
    Stage6Output,
    Stage7Output,
    Stage8Output,
)
from .stage1 import run_stage1
from .stage2 import run_stage2
from .stage3 import run_stage3
from .stage5 import run_stage5
from .stage6 import run_stage6
from .stage7 import run_stage7
from .stage8 import run_stage8

logger = logging.getLogger(__name__)


def new_project_dir(output_dir: Path, project_id: str | None = None) -> Path:
    """创建带时间戳的项目目录。"""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = project_id or f"revive_{ts}"
    d = output_dir / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_checkpoint(project_dir: Path, stage: int, output) -> None:
    """保存 stage 输出为 checkpoint JSON。"""
    cp = project_dir / f"stage{stage}.json"
    try:
        cp.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("stage%d checkpoint 序列化失败: %s", stage, e)


def _load_checkpoint(project_dir: Path, stage: int, model_cls):
    """从 checkpoint 加载 stage 输出。"""
    cp = project_dir / f"stage{stage}.json"
    if not cp.exists():
        return None
    try:
        return model_cls.model_validate_json(cp.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("stage%d checkpoint 加载失败: %s", stage, e)
        return None


def run_pipeline(
    settings: Settings,
    painting_path: Path,
    object_lineart_path: Path | None = None,
    keyframe_lineart_paths: list[Path] | None = None,
    project_id: str | None = None,
    resume_from_stage: int = 0,
    use_comfyui: bool = True,
    view_mode: str | None = None,
    focus_node_id: int | None = None,
    spatial_prompt: str = "",
    edit_spec: SpatialEditSpec | None = None,
) -> Path:
    """端到端 Canvas3D-v2 管线。

    resume_from_stage:
      0  - 从头开始
      >0 - 从指定 stage 恢复（跳过之前的，使用 checkpoint）
      -1 - 自动恢复（加载所有可用 checkpoint）

    返回最终视频路径。
    """
    project_dir = new_project_dir(settings.output_dir, project_id)
    logger.info("项目目录: %s", project_dir)

    resume = resume_from_stage == -1

    # ── Stage 1: PaintParse ──
    s1 = None
    if resume or resume_from_stage <= 1:
        s1 = _load_checkpoint(project_dir, 1, Stage1Output) if resume else None
    if s1 is None and resume_from_stage <= 1:
        logger.info("Stage 1: PaintParse")
        s1 = run_stage1(painting_path, project_dir, settings,
                        object_lineart_path, keyframe_lineart_paths)
        _save_checkpoint(project_dir, 1, s1)
    if s1 is None:
        s1 = _load_checkpoint(project_dir, 1, Stage1Output)
        if s1 is None:
            raise RuntimeError("无法加载 stage1 checkpoint")

    # ── Stage 2: MonoSplat ──
    s2 = None
    if resume or resume_from_stage <= 2:
        s2 = _load_checkpoint(project_dir, 2, Stage2Output) if resume else None
    if s2 is None and resume_from_stage <= 2:
        logger.info("Stage 2: MonoSplat")
        s2 = run_stage2(s1, project_dir, settings)
        _save_checkpoint(project_dir, 2, s2)
    if s2 is None:
        s2 = _load_checkpoint(project_dir, 2, Stage2Output)
        if s2 is None:
            raise RuntimeError("无法加载 stage2 checkpoint")

    # ── Stage 6: SceneGraph3D (v2) ──
    s6 = None
    if resume or resume_from_stage <= 6:
        s6 = _load_checkpoint(project_dir, 6, Stage6Output) if resume else None
    if s6 is None and resume_from_stage <= 6:
        logger.info("Stage 6: SceneGraph3D")
        s6 = run_stage6(s1, s2, project_dir, settings)
        _save_checkpoint(project_dir, 6, s6)
    if s6 is None:
        s6 = _load_checkpoint(project_dir, 6, Stage6Output)
        if s6 is None:
            raise RuntimeError("无法加载 stage6 checkpoint")

    # ── Stage 3: SketchComp (可选) ──
    s3 = None
    if object_lineart_path is not None:
        if resume or resume_from_stage <= 3:
            s3 = _load_checkpoint(project_dir, 3, Stage3Output) if resume else None
        if s3 is None and resume_from_stage <= 3:
            logger.info("Stage 3: SketchComp")
            s3 = run_stage3(s1, s2, project_dir, settings)
            _save_checkpoint(project_dir, 3, s3)
        if s3 is None:
            s3 = _load_checkpoint(project_dir, 3, Stage3Output)
    # s3 可能为 None（无线稿编辑，跳过此 stage）

    # ── Stage 7: ViewCtrl (v2) ──
    s7 = None
    if resume or resume_from_stage <= 7:
        s7 = _load_checkpoint(project_dir, 7, Stage7Output) if resume else None
    if s7 is None and resume_from_stage <= 7:
        logger.info("Stage 7: ViewCtrl (mode=%s)", view_mode or settings.view_trajectory_mode)
        s7 = run_stage7(s3, s6, project_dir, settings,
                        mode=view_mode, focus_node_id=focus_node_id,
                        stage2_output=s2)
        _save_checkpoint(project_dir, 7, s7)
    if s7 is None:
        s7 = _load_checkpoint(project_dir, 7, Stage7Output)
        if s7 is None:
            raise RuntimeError("无法加载 stage7 checkpoint")

    # ── Stage 8: SpatialFlow (v2) ──
    s8 = None
    if resume or resume_from_stage <= 8:
        s8 = _load_checkpoint(project_dir, 8, Stage8Output) if resume else None
    if s8 is None and resume_from_stage <= 8:
        logger.info("Stage 8: SpatialFlow")
        if edit_spec is None and spatial_prompt:
            edit_spec = SpatialEditSpec(
                num_frames=max(int(settings.duration_sec * settings.fps), 9),
                fps=settings.fps,
                text_prompt=spatial_prompt,
                relation_strength=settings.spatial_relation_strength,
                generation_mode=settings.spatial_text_mode,
            )
        s8 = run_stage8(s7, s6, project_dir, settings,
                        edit_spec=edit_spec, use_comfyui=use_comfyui)
        _save_checkpoint(project_dir, 8, s8)
    if s8 is None:
        s8 = _load_checkpoint(project_dir, 8, Stage8Output)
        if s8 is None:
            raise RuntimeError("无法加载 stage8 checkpoint")

    # ── Stage 5: ArtiFlow 最终合成（可选，stage8 已含视频生成）──
    # stage8 已生成最终视频；若需要额外的 ArtiFlow 后处理可在此调用
    # run_stage5(s3, project_dir, settings, keyframes=..., use_comfyui=use_comfyui)

    logger.info("✅ 管线完成: %s", s8.final_video_path)
    return s8.final_video_path
