"""mesh2video 模块冒烟测试。

不依赖 ComfyUI 在线，仅验证：
* 模块导入正常
* 相机/渲染器在合成 mesh 上能产出三路 (T,H,W,3) uint8
* pipeline 的 workflow 注入逻辑能正确生成 API JSON

需要 trimesh + numpy（dev 环境自带；CI 可 pip install trimesh）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")

from oilpaint.mesh2video import (  # noqa: E402
    Camera,
    orbit_camera,
    WhiteMeshRenderer,
    RenderPass,
    StaticDriver,
    Mesh2VideoPipeline,
    Mesh2VideoConfig,
)
from oilpaint.mesh2video.animation import MorphDriver  # noqa: E402


def _box_mesh() -> "trimesh.Trimesh":
    return trimesh.creation.box(extents=[1.0, 1.5, 0.5])


def test_camera_orbit_sequence():
    cams = orbit_camera(target=np.zeros(3), radius=2.0, num_frames=5)
    assert len(cams) == 5
    assert all(isinstance(c, Camera) for c in cams)
    V = cams[0].view_matrix()
    P = cams[0].projection_matrix()
    assert V.shape == (4, 4) and P.shape == (4, 4)


def test_renderer_three_passes():
    mesh = _box_mesh()
    cam = Camera.from_fov(width=128, height=96, eye=np.array([2, 1, 2]), target=np.zeros(3))
    r = WhiteMeshRenderer(width=128, height=96)
    out = r.render(mesh, cam, passes=(RenderPass.CLAY, RenderPass.DEPTH, RenderPass.NORMAL))
    assert set(out) == {RenderPass.CLAY, RenderPass.DEPTH, RenderPass.NORMAL}
    for p, arr in out.items():
        assert arr.shape == (96, 128, 3) and arr.dtype == np.uint8, p
    # 深度图应有非背景像素
    assert int((out[RenderPass.DEPTH] > 30).sum()) > 100


def test_render_sequence_static_driver():
    mesh = _box_mesh()
    cams = orbit_camera(target=np.zeros(3), radius=2.0, num_frames=4, width=96, height=64)
    driver = StaticDriver(mesh=mesh, num_frames=4)
    r = WhiteMeshRenderer(width=96, height=64)
    out = r.render_sequence(driver.frames(), cams, passes=(RenderPass.DEPTH, RenderPass.CLAY))
    assert out[RenderPass.DEPTH].shape == (4, 64, 96, 3)
    assert out[RenderPass.CLAY].shape == (4, 64, 96, 3)


def test_morph_driver_vertex_interpolation():
    m0 = _box_mesh()
    m1 = trimesh.creation.box(extents=[1.5, 1.5, 0.5])
    # MorphDriver 要求顶点数一致
    assert m0.vertices.shape == m1.vertices.shape
    driver = MorphDriver(key_meshes=[m0, m1], num_frames=5)
    f0 = driver.frame(0)
    fmid = driver.frame(2)
    f1 = driver.frame(4)
    # 端点应等于关键 mesh
    assert np.allclose(np.asarray(f0.vertices), np.asarray(m0.vertices))
    assert np.allclose(np.asarray(f1.vertices), np.asarray(m1.vertices))
    # 中间帧应在两端之间（顶点均值变化单调）
    d0 = np.abs(np.asarray(f0.vertices) - np.asarray(fmid.vertices)).mean()
    d1 = np.abs(np.asarray(f1.vertices) - np.asarray(fmid.vertices)).mean()
    assert d0 > 0 and d1 > 0


def test_pipeline_workflow_injection_wan(tmp_path: Path):
    cfg = Mesh2VideoConfig(
        comfy_host="127.0.0.1",
        comfy_port=8188,
        backend="wan",
        style_image="x.png",
        num_frames=33,
        width=832,
        height=480,
        steps=20,
        cfg=5.5,
        depth_control_strength=0.65,
        seed=7,
    )
    pipe = Mesh2VideoPipeline(cfg)
    wf = pipe._build_wan_workflow(Path("style.png"), Path("depth.mp4"), tmp_path)
    # 关键注入字段
    assert wf["wan_pos_text"]["inputs"]["text"] == cfg.positive_prompt
    assert wf["wan_i2v_encode"]["inputs"]["num_frames"] == 33
    assert wf["wan_depth_control"]["inputs"]["strength"] == 0.65
    assert wf["wan_sampler"]["inputs"]["steps"] == 20
    assert wf["wan_sampler"]["inputs"]["seed"] == 7
    # debug json 落盘
    assert (tmp_path / "wan_workflow_debug.json").exists()
    json.loads((tmp_path / "wan_workflow_debug.json").read_text(encoding="utf-8"))


def test_pipeline_workflow_injection_ltx(tmp_path: Path):
    cfg = Mesh2VideoConfig(
        backend="ltx", style_image="x.png", num_frames=25, guide_strength=0.5, seed=3,
    )
    pipe = Mesh2VideoPipeline(cfg)
    wf = pipe._build_ltx_workflow(Path("style.png"), Path("guide.mp4"), tmp_path)
    assert wf["ltx_i2v"]["inputs"]["length"] == 25
    assert wf["ltx_add_guide"]["inputs"]["strength"] == 0.5
    assert wf["ltx_sampler"]["inputs"]["seed"] == 3
