"""端到端编排：3D 动态白膜 → ComfyUI 图生视频。

典型用法
--------
.. code-block:: python

    import trimesh
    from oilpaint.mesh2video import (
        Mesh2VideoPipeline, Mesh2VideoConfig, StaticDriver, orbit_camera,
    )

    mesh = trimesh.load("bust.glb", force="mesh")
    cams = orbit_camera(target=[0,0,0], radius=2.5, num_frames=49)
    driver = StaticDriver(mesh=mesh, num_frames=49)

    cfg = Mesh2VideoConfig(
        comfy_host="127.0.0.1", comfy_port=8188,
        backend="wan",         # "wan" 或 "ltx"
        style_image="assets/style_vangogh.png",
        num_frames=49, width=832, height=480,
        depth_control_strength=0.7,
    )
    pipe = Mesh2VideoPipeline(cfg)
    out = asyncio.run(pipe.run(driver, cams))
    print(out["video"])

工作流选择
----------
* ``backend="wan"`` → ``wan_i2v_3d_depth.json``：用 Wan2.1 + depth Control LoRA，
  几何控制强、风格自由度高（推荐主路径）。
* ``backend="ltx"`` → ``ltx_i2v_3d_guide.json``：用 LTX-Video + LTXVAddGuide，
  速度快、显存友好；几何控制稍弱但 STG 时序稳定好。

风格稳定三件套
--------------
1. 单张 ``style_image`` 锚定全局风格（CLIP vision / 首帧）。
2. 深度/法线序列锁几何跨帧一致。
3. TeaCache + Context overlap（Wan）/ STG（LTX）压时序抖动。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ...common.comfy.client import ComfyClient
from ...common.comfy.workflows import load_template, apply_params, set_seed
from .camera import Camera
from .renderer import WhiteMeshRenderer, RenderPass, save_frames

logger = logging.getLogger(__name__)


@dataclass
class Mesh2VideoConfig:
    """Mesh2Video 流水线配置。"""

    # ComfyUI
    comfy_host: str = "127.0.0.1"
    comfy_port: int = 8188
    concurrency: int = 1

    # 后端模型
    backend: str = "wan"          # "wan" 或 "ltx"
    workflows_dir: str = ""       # 覆盖内置 templates 的目录，留空用默认

    # 视频参数
    num_frames: int = 49
    width: int = 832
    height: int = 480
    fps: int = 24
    seed: int | None = None

    # 风格锚定
    style_image: str = ""         # 风格参考图路径（必填）

    # 控制强度
    depth_control_strength: float = 0.7   # Wan depth ControlNet strength
    guide_strength: float = 0.6           # LTX LTXVAddGuide strength
    i2v_strength: float = 0.9             # 首帧保持强度

    # 提示词
    positive_prompt: str = (
        "oil painting, impasto brush strokes, cinematic lighting, masterpiece"
    )
    negative_prompt: str = (
        "static, 3d render, flat shading, low quality, jitter, watermark, text, blurry"
    )

    # 采样
    steps: int = 30
    cfg: float = 6.0

    # 输出
    work_dir: str = ""             # 中间产物目录，留空 → <项目>/output/mesh2video
    output_filename_prefix: str = "mesh2video"

    # ---- 内部 ----
    @property
    def base_url(self) -> str:
        return f"http://{self.comfy_host}:{self.comfy_port}"

    def workflow_name(self) -> str:
        return "wan_i2v_3d_depth" if self.backend == "wan" else "ltx_i2v_3d_guide"


class Mesh2VideoPipeline:
    """3D 白膜 → ComfyUI I2V 流水线。"""

    def __init__(self, cfg: Mesh2VideoConfig) -> None:
        self.cfg = cfg
        self._client = ComfyClient(cfg.base_url, concurrency=cfg.concurrency)

    # ------------------------------------------------------------------
    async def run(
        self,
        driver,
        cameras,
        *,
        passes: tuple[RenderPass, ...] = (RenderPass.CLAY, RenderPass.DEPTH, RenderPass.NORMAL),
    ) -> dict[str, Any]:
        """端到端执行。

        Parameters
        ----------
        driver : AnimationDriver，提供每帧 mesh。
        cameras : Camera 或 list[Camera]。
        passes : 需要渲染的通道；至少需要 DEPTH（wan）或 CLAY（ltx）。

        Returns
        -------
        dict 包含 ``work_dir``、各 pass 的 mp4 路径、最终风格化视频 ``video``。
        """
        cfg = self.cfg
        work = Path(cfg.work_dir) if cfg.work_dir else self._default_work_dir()
        work.mkdir(parents=True, exist_ok=True)
        logger.info("Mesh2Video 工作目录: %s", work)

        # 1) 渲染 3D 白膜序列
        renderer = WhiteMeshRenderer(width=cfg.width, height=cfg.height)
        frames = driver.frames()
        if len(frames) != cfg.num_frames:
            logger.warning("driver 帧数 %d != cfg.num_frames %d，以 driver 为准", len(frames), cfg.num_frames)
            cfg.num_frames = len(frames)
        rendered = renderer.render_sequence(frames, cameras, passes=passes)

        # 2) 落盘为 mp4 + png 序列
        seq_paths: dict[str, Path] = {}
        for p, arr in rendered.items():
            # mp4（ComfyUI 的 VHS_LoadVideo 需要）
            mp4 = work / f"{p.value}_seq.mp4"
            self._write_mp4(arr, mp4, cfg.fps)
            seq_paths[p.value] = mp4
            # 同时存 png 序列，便于人工检查
            save_frames(arr, work / p.value, prefix=p.value)
            logger.info("%s 序列已写出: %s (%d 帧)", p.value, mp4, len(arr))

        # 3) 选后端需要的控制序列上传到 ComfyUI
        style_path = Path(cfg.style_image)
        if not style_path.is_file():
            raise FileNotFoundError(f"风格参考图不存在: {style_path}")

        if cfg.backend == "wan":
            control_path = seq_paths[RenderPass.DEPTH.value]
            workflow = self._build_wan_workflow(style_path, control_path, work)
            outputs_node = "wan_save"
        else:
            control_path = seq_paths[RenderPass.CLAY.value]
            workflow = self._build_ltx_workflow(style_path, control_path, work)
            outputs_node = "ltx_save"

        # 4) 上传风格图 + 控制视频
        up_style = await self._client.upload_image(style_path)
        up_control = await self._client.upload_image(control_path)  # VHS_LoadVideo 也走 /upload/image
        logger.info("上传 style=%s control=%s", up_style.get("name"), up_control.get("name"))

        # 5) 注入上传后的文件名到工作流
        if cfg.backend == "wan":
            workflow["input_style_image"]["inputs"]["image"] = up_style["name"]
            workflow["input_depth_video"]["inputs"]["video"] = up_control["name"]
        else:
            workflow["input_style_image"]["inputs"]["image"] = up_style["name"]
            workflow["input_guide_frames"]["inputs"]["video"] = up_control["name"]

        # 6) 提交并等待产物
        try:
            results = await self._client.run(
                workflow,
                outputs_node=outputs_node,
                save_to=work / "out",
                timeout=1800,
            )
        finally:
            await self._client.aclose()

        if not results:
            raise RuntimeError("ComfyUI 未返回产物")
        logger.info("Mesh2Video 完成: %s", results[0])
        return {
            "work_dir": str(work),
            "clay_video": str(seq_paths.get(RenderPass.CLAY.value, "")),
            "depth_video": str(seq_paths.get(RenderPass.DEPTH.value, "")),
            "normal_video": str(seq_paths.get(RenderPass.NORMAL.value, "")),
            "video": str(results[0]),
        }

    # ------------------------------------------------------------------
    def _build_wan_workflow(self, style_path: Path, depth_path: Path, work: Path) -> dict[str, Any]:
        cfg = self.cfg
        wf = load_template("wan_i2v_3d_depth", self._workflows_dir())
        params = {
            "wan_pos_text": {"text": cfg.positive_prompt},
            "wan_neg_text": {"text": cfg.negative_prompt},
            "wan_i2v_encode": {
                "width": cfg.width,
                "height": cfg.height,
                "num_frames": cfg.num_frames,
                "strength": cfg.i2v_strength,
            },
            "wan_depth_control": {"strength": cfg.depth_control_strength},
            "wan_sampler": {"steps": cfg.steps, "cfg": cfg.cfg},
            "wan_save": {"filename_prefix": cfg.output_filename_prefix, "frame_rate": cfg.fps},
            "input_depth_video": {"frame_load_cap": cfg.num_frames},
        }
        wf = apply_params(wf, params)
        set_seed(wf, "wan_sampler", cfg.seed)
        # 备份一份调试用
        (work / "wan_workflow_debug.json").write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
        return wf

    def _build_ltx_workflow(self, style_path: Path, guide_path: Path, work: Path) -> dict[str, Any]:
        cfg = self.cfg
        wf = load_template("ltx_i2v_3d_guide", self._workflows_dir())
        params = {
            "ltx_pos": {"text": cfg.positive_prompt},
            "ltx_neg": {"text": cfg.negative_prompt},
            "ltx_i2v": {
                "width": cfg.width,
                "height": cfg.height,
                "length": cfg.num_frames,
                "strength": cfg.i2v_strength,
            },
            "ltx_add_guide": {"strength": cfg.guide_strength},
            "ltx_sampler": {"steps": cfg.steps, "cfg": cfg.cfg},
            "ltx_save": {"filename_prefix": cfg.output_filename_prefix, "frame_rate": cfg.fps},
        }
        wf = apply_params(wf, params)
        set_seed(wf, "ltx_sampler", cfg.seed)
        (work / "ltx_workflow_debug.json").write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
        return wf

    # ------------------------------------------------------------------
    def _workflows_dir(self):
        from ...common.config import PROJECT_ROOT

        d = self.cfg.workflows_dir
        return Path(d) if d else PROJECT_ROOT / "workflows"

    def _default_work_dir(self):
        from ...common.config import PROJECT_ROOT

        return PROJECT_ROOT / "output" / "mesh2video"

    @staticmethod
    def _write_mp4(frames: np.ndarray, path: Path, fps: int) -> None:
        """(T,H,W,3) uint8 → mp4。优先用 imageio，回退到 imageio-ffmpeg。"""
        try:
            import imageio.v2 as imageio
            writer = imageio.get_writer(str(path), fps=fps, codec="libx264", quality=8)
            for f in frames:
                writer.append_data(f)
            writer.close()
        except Exception:
            import imageio_ffmpeg
            import subprocess
            tmp = path.with_suffix(".mp4.tmp")
            # 退化方案：用 ffmpeg 读 png 序列
            frames_dir = path.parent / (path.stem + "_tmpframes")
            save_frames(frames, frames_dir, prefix="f")
            cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y",
                "-framerate", str(fps),
                "-i", str(frames_dir / "f_%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(tmp),
            ]
            subprocess.run(cmd, check=True)
            tmp.replace(path)
