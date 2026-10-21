"""Mesh2Video 命令行示例。

把一个 GLB/OBJ 模型渲染成动态白膜，再交给 ComfyUI (Wan2.1 / LTX) 生成风格化视频。

用法
----
.. code-block:: bash

    # 1) 静态网格 + 相机环绕 → 油画风视频
    python -m oilpaint.mesh2video.example \\
        --mesh assets/bust.glb \\
        --style-image assets/style_vangogh.png \\
        --backend wan --num-frames 49

    # 2) 仅离线渲染白膜/深度/法线序列（不调用 ComfyUI）
    python -m oilpaint.mesh2video.example \\
        --mesh assets/bust.glb --render-only --work-dir output/m2v_debug

    # 3) 用自定义 config
    python -m oilpaint.mesh2video.example --config config/mesh2video.yaml \\
        --mesh assets/bust.glb

需要 ``trimesh`` 与 ``imageio``（pip install trimesh imageio）。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import numpy as np

from .camera import orbit_camera
from .animation import StaticDriver, MorphDriver
from .pipeline import Mesh2VideoPipeline, Mesh2VideoConfig
from .renderer import WhiteMeshRenderer, RenderPass, save_frames


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    import yaml

    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _build_cfg(args, raw: dict) -> Mesh2VideoConfig:
    render_cfg = raw.get("render", {}) or {}
    cam_cfg = raw.get("camera", {}) or {}
    # 把 render/camera 子段存到 args 里供后续用，主 cfg 字段平铺
    return Mesh2VideoConfig(
        comfy_host=raw.get("comfy_host", args.comfy_host),
        comfy_port=int(raw.get("comfy_port", args.comfy_port)),
        concurrency=int(raw.get("concurrency", 1)),
        backend=raw.get("backend", args.backend),
        workflows_dir=raw.get("workflows_dir", ""),
        num_frames=int(raw.get("num_frames", args.num_frames)),
        width=int(raw.get("width", args.width)),
        height=int(raw.get("height", args.height)),
        fps=int(raw.get("fps", 24)),
        seed=raw.get("seed", args.seed),
        style_image=raw.get("style_image", args.style_image) or "",
        depth_control_strength=float(raw.get("depth_control_strength", 0.7)),
        guide_strength=float(raw.get("guide_strength", 0.6)),
        i2v_strength=float(raw.get("i2v_strength", 0.9)),
        positive_prompt=raw.get("positive_prompt", ""),
        negative_prompt=raw.get("negative_prompt", ""),
        steps=int(raw.get("steps", 30)),
        cfg=float(raw.get("cfg", 6.0)),
        work_dir=raw.get("work_dir", args.work_dir or ""),
        output_filename_prefix=raw.get("output_filename_prefix", "mesh2video"),
    ), cam_cfg, render_cfg


def _load_mesh(path: str):
    import trimesh

    m = trimesh.load(path, force="mesh")
    # 归一化到单位球内，居中
    if hasattr(m, "vertices") and len(m.vertices):
        v = np.asarray(m.vertices)
        v = v - v.mean(axis=0)
        s = np.linalg.norm(v, axis=1).max()
        if s > 1e-6:
            v = v / s
        m.vertices = v
    return m


async def _run_pipeline(cfg: Mesh2VideoConfig, driver, cameras) -> None:
    pipe = Mesh2VideoPipeline(cfg)
    res = await pipe.run(driver, cameras)
    print("==== Mesh2Video 完成 ====")
    for k, v in res.items():
        print(f"  {k}: {v}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Mesh2Video: 3D 动态白膜 → ComfyUI 风格化视频")
    p.add_argument("--config", default="", help="config/mesh2video.yaml 路径")
    p.add_argument("--mesh", required=True, help="3D 模型路径 (.glb/.obj/.stl)")
    p.add_argument("--style-image", default="", help="风格参考图")
    p.add_argument("--backend", choices=["wan", "ltx"], default="wan")
    p.add_argument("--num-frames", type=int, default=49)
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--comfy-host", default="127.0.0.1")
    p.add_argument("--comfy-port", type=int, default=8188)
    p.add_argument("--work-dir", default="", help="中间产物/输出目录")
    p.add_argument("--render-only", action="store_true", help="只渲染白膜序列，不调 ComfyUI")
    args = p.parse_args()

    raw = _load_config(args.config or None)
    cfg, cam_cfg, render_cfg = _build_cfg(args, raw)

    mesh = _load_mesh(args.mesh)
    cams = orbit_camera(
        target=np.asarray(cam_cfg.get("target", [0, 0, 0]), dtype=np.float64),
        radius=float(cam_cfg.get("radius", 2.5)),
        num_frames=cfg.num_frames,
        height_offset=float(cam_cfg.get("height_offset", 0.5)),
        num_turns=float(cam_cfg.get("num_turns", 1.0)),
        fov_y_deg=float(cam_cfg.get("fov_y_deg", 50.0)),
        width=cfg.width,
        height=cfg.height,
        tilt_deg=float(cam_cfg.get("tilt_deg", 15.0)),
    )
    driver = StaticDriver(mesh=mesh, num_frames=cfg.num_frames)

    if args.render_only:
        work = Path(cfg.work_dir) if cfg.work_dir else Path("output/mesh2video_debug")
        r = WhiteMeshRenderer(width=cfg.width, height=cfg.height)
        out = r.render_sequence(driver.frames(), cams)
        for p_, arr in out.items():
            d = work / p_.value
            save_frames(arr, d, prefix=p_.value)
            print(f"  {p_.value}: {len(arr)} frames → {d}")
        return

    if not cfg.style_image:
        raise SystemExit("非 --render-only 模式必须提供 --style-image 或 config.style_image")
    asyncio.run(_run_pipeline(cfg, driver, cams))


if __name__ == "__main__":
    main()
