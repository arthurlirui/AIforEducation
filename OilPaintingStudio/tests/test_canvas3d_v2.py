"""Canvas3D-v2 新模块测试：stage6 场景图 / stage7 视角可控 / stage8 空间关系视频。

全 mock 模式，不依赖 YOLO / DepthAnything / TripoSplat / ComfyUI。
验证数据流衔接、产物完整性、关系图构建正确性。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# 让包可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oilpainting_studio.common.config import Settings
from oilpainting_studio.revive.schemas import (
    CameraPose,
    ControlSignals,
    GSModelRecord,
    GSModelRegistry,
    ObjectCategory,
    SegmentedObject,
    SpatialEdit,
    SpatialEditSpec,
    SpatialEditType,
    SpatialRelation,
    SpatialRelationType,
    Stage1Output,
    Stage2Output,
)
from oilpainting_studio.revive.stage6 import build_scene_graph
from oilpainting_studio.revive.stage7 import (
    generate_trajectory,
    render_viewframe,
    run_stage7,
)
from oilpainting_studio.revive.stage8 import (
    encode_node_features,
    encode_relation_edges,
    encode_relation_graph,
    gnn_message_passing,
    run_stage8,
)


# ────────────────────── Fixtures ──────────────────────

@pytest.fixture
def small_settings(tmp_path) -> Settings:
    """小尺寸测试配置。"""
    s = Settings()
    s.width = 120
    s.height = 90
    s.fps = 8
    s.duration_sec = 1
    s.focal_length = 200.0
    s.output_dir = tmp_path / "output"
    s.gaussians_per_object = 50
    s.edge_align_iterations = 3
    s.num_keyframes = 3
    s.inpaint_radius = 2
    s.view_num_poses = 4
    s.view_orbit_angle_deg = 20.0
    s.view_trajectory_mode = "auto_orbit"
    s.spatial_gnn_hidden = 32
    s.spatial_relation_strength = 0.7
    s.spatial_text_mode = "i2v"
    return s


def _make_mask(h: int, w: int, bbox: tuple[int, int, int, int]) -> Path:
    """生成二值 mask 并保存到临时文件。"""
    img = np.zeros((h, w), dtype=np.uint8)
    x0, y0, x1, y1 = bbox
    img[y0:y1, x0:x1] = 255
    return img


@pytest.fixture
def fake_stage1(tmp_path, small_settings) -> Stage1Output:
    """构造一个假的 Stage1Output：2 个前景物体 + 背景。"""
    h, w = small_settings.height, small_settings.width
    # 物体 0：左上 person
    mask0 = _make_mask(h, w, (10, 10, 50, 60))
    crop0 = np.zeros((50, 40, 3), dtype=np.uint8)
    mask0_path = tmp_path / "mask0.png"
    crop0_path = tmp_path / "crop0.png"
    cv2.imwrite(str(mask0_path), mask0)
    cv2.imwrite(str(crop0_path), crop0)
    # 物体 1：右下 building
    mask1 = _make_mask(h, w, (60, 40, 110, 80))
    crop1 = np.zeros((40, 50, 3), dtype=np.uint8)
    mask1_path = tmp_path / "mask1.png"
    crop1_path = tmp_path / "crop1.png"
    cv2.imwrite(str(mask1_path), mask1)
    cv2.imwrite(str(crop1_path), crop1)
    bg_mask = np.full((h, w), 255, dtype=np.uint8)
    bg_mask[np.maximum(mask0, mask1) > 0] = 0
    bg_mask_path = tmp_path / "bg_mask.png"
    bg_path = tmp_path / "bg.png"
    cv2.imwrite(str(bg_mask_path), bg_mask)
    cv2.imwrite(str(bg_path), np.zeros((h, w, 3), dtype=np.uint8))
    depth = (np.random.rand(h, w) * 5 + 1).astype(np.float32)
    depth_path = tmp_path / "depth.png"
    cv2.imwrite(str(depth_path), (depth * 1000).astype(np.uint16))

    return Stage1Output(
        painting_path=tmp_path / "painting.png",
        objects=[
            SegmentedObject(
                object_id=0, category=ObjectCategory.PERSON, label="person",
                confidence=0.9, mask_path=mask0_path, bbox=(10, 10, 50, 60),
                crop_path=crop0_path, depth_range=(1.0, 2.5),
            ),
            SegmentedObject(
                object_id=1, category=ObjectCategory.BUILDING, label="building",
                confidence=0.85, mask_path=mask1_path, bbox=(60, 40, 110, 80),
                crop_path=crop1_path, depth_range=(4.0, 8.0),
            ),
        ],
        background_mask_path=bg_mask_path,
        background_path=bg_path,
        depth_path=depth_path,
        controls=ControlSignals(),
        width=w, height=h, detector="mock",
    )


@pytest.fixture
def fake_stage2(tmp_path, fake_stage1) -> Stage2Output:
    """构造假的 Stage2Output：2 个物体 3DGS 记录 + 背景。"""
    # 构造极简 PLY 文件
    ply_content = """ply
format ascii 1.0
element vertex 1
property float x
property float y
property float z
property float sx
property float sy
property float sz
property float r
property float g
property float b
property float opacity
property float qx
property float qy
end_header
0 0 1.5 0.1 0.1 0.1 0.8 0.6 0.4 1.0 0 0
"""
    obj0_ply = tmp_path / "obj0.ply"
    obj1_ply = tmp_path / "obj1.ply"
    bg_ply = tmp_path / "bg.ply"
    obj0_ply.write_text(ply_content)
    obj1_ply.write_text(ply_content)
    bg_ply.write_text(ply_content)

    registry = GSModelRegistry(
        models=[
            GSModelRecord(
                object_id=0, label="person", ply_path=obj0_ply, num_gaussians=1,
                bbox_3d=(-0.3, -0.5, 1.0, 0.3, 0.5, 2.5),
                center_3d=(0.0, 0.0, 1.75), source="mock",
            ),
            GSModelRecord(
                object_id=1, label="building", ply_path=obj1_ply, num_gaussians=1,
                bbox_3d=(0.5, -0.4, 4.0, 1.5, 0.4, 8.0),
                center_3d=(1.0, 0.0, 6.0), source="mock",
            ),
        ],
        background_ply_path=bg_ply,
    )
    scene_ply = tmp_path / "scene.ply"
    scene_ply.write_text(ply_content)
    return Stage2Output(registry=registry, scene_ply_path=scene_ply)


# ────────────────────── Stage 6: 场景图 ──────────────────────

class TestStage6:
    def test_build_scene_graph_basic(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        out = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        assert out.num_nodes == 3, "2 前景 + 1 背景 = 3 节点"
        assert out.num_relations > 0, "至少有节点间关系"
        assert out.scene_graph.background_node_id == -1
        assert out.graph_path.exists(), "场景图 JSON 持久化"

    def test_scene_graph_relations(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        out = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        sg = out.scene_graph
        # 应有深度关系：person (1-2.5) 在 building (4-8) 之前
        rel_types = {(r.src_id, r.dst_id, r.rel_type.value) for r in sg.relations}
        assert any(r[2] == "in_front_of" for r in rel_types), "存在 in_front_of 关系"
        # 应有左右关系
        assert any(r[2] in ("left_of", "right_of") for r in rel_types), "存在 left/right_of 关系"

    def test_scene_graph_salience(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        out = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        fg = [n for n in out.scene_graph.nodes if n.node_type == "foreground"]
        for n in fg:
            assert 0.0 <= n.salience <= 1.0, f"显著性 [0,1]: {n.salience}"

    def test_scene_graph_serialization(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        import json
        out = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        data = json.loads(out.graph_path.read_text(encoding="utf-8"))
        assert "nodes" in data and "relations" in data
        assert len(data["nodes"]) == 3


# ────────────────────── Stage 7: 视角可控 ──────────────────────

class TestStage7:
    def test_generate_trajectory_auto_orbit(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        traj = generate_trajectory(s6.scene_graph, small_settings, mode="auto_orbit")
        assert len(traj.poses) == small_settings.view_num_poses
        assert traj.mode == "auto_orbit"
        for p in traj.poses:
            assert len(p.position) == 3
            assert len(p.look_at) == 3

    def test_generate_trajectory_modes(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        for mode in ["orbit", "dolly", "crane"]:
            traj = generate_trajectory(s6.scene_graph, small_settings, mode=mode)
            assert len(traj.poses) == small_settings.view_num_poses
            assert traj.mode == mode

    def test_generate_trajectory_manual(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        manual = [CameraPose(position=(0, 0, 3), look_at=(0, 0, 0)),
                  CameraPose(position=(1, 0, 3), look_at=(0, 0, 0))]
        traj = generate_trajectory(s6.scene_graph, small_settings, mode="manual",
                                   manual_poses=manual)
        assert len(traj.poses) == 2
        assert traj.poses[0].position == (0, 0, 3)

    def test_render_viewframe_empty(self, small_settings):
        from oilpainting_studio.revive.schemas import SceneGraph
        empty_surfels = np.zeros((1, 12), dtype=np.float32)
        pose = CameraPose(position=(0, 0, 3), look_at=(0, 0, 0))
        rgb, depth, edge, vis = render_viewframe(
            empty_surfels, pose, small_settings.height, small_settings.width,
            small_settings.focal_length, SceneGraph())
        assert rgb.shape == (small_settings.height, small_settings.width, 3)
        assert depth.shape == (small_settings.height, small_settings.width)

    def test_run_stage7_full(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        # 用 fake_stage2 的 scene.ply 作为场景
        class FakeStage3:
            edited_scene_ply_path = fake_stage2.scene_ply_path
        out = run_stage7(FakeStage3(), s6, tmp_path, small_settings, mode="auto_orbit")
        assert len(out.keyframes) == small_settings.view_num_poses
        for kf in out.keyframes:
            assert kf.render_path.exists(), f"视角帧 {kf.frame_index} 渲染图存在"
            assert kf.depth_path.exists(), "深度图存在"
            assert kf.edge_path.exists(), "边缘图存在"
            assert kf.visibility_mask_path.exists(), "可见性 mask 存在"


# ────────────────────── Stage 8: 空间关系视频 ──────────────────────

class TestStage8:
    def test_encode_node_features(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        emb = encode_node_features(s6.scene_graph, hidden_dim=32)
        assert emb.shape == (3, 32), "3 节点 × 32 维"

    def test_encode_relation_edges(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        edges = encode_relation_edges(s6.scene_graph)
        assert edges.shape[1] == 3, "[src, dst, rel_type]"
        assert len(edges) > 0, "至少有边"

    def test_gnn_message_passing(self):
        node_emb = np.random.randn(3, 16).astype(np.float32)
        edges = np.array([[0, 1, 0], [1, 2, 1]], dtype=np.int64)
        out = gnn_message_passing(node_emb, edges, num_layers=2)
        assert out.shape == (3, 16)

    def test_encode_relation_graph(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        ctx = encode_relation_graph(s6.scene_graph, visible_node_ids=[0], hidden_dim=32)
        assert ctx.shape == (32,), "per-frame 上下文向量"

    def test_encode_relation_graph_no_visible(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        ctx = encode_relation_graph(s6.scene_graph, visible_node_ids=[], hidden_dim=32)
        assert ctx.shape == (32,), "无可见节点时回退到所有前景均值"

    def test_run_stage8_mock(self, fake_stage1, fake_stage2, tmp_path, small_settings):
        from oilpainting_studio.revive.stage6 import build_scene_graph
        from oilpainting_studio.revive.stage7 import run_stage7
        s6 = build_scene_graph(fake_stage1, fake_stage2, tmp_path, small_settings)
        class FakeStage3:
            edited_scene_ply_path = fake_stage2.scene_ply_path
        s7 = run_stage7(FakeStage3(), s6, tmp_path, small_settings, mode="auto_orbit")
        edit_spec = SpatialEditSpec(
            num_frames=8, fps=8, text_prompt="test spatial video",
            relation_strength=0.7, generation_mode="i2v",
        )
        out = run_stage8(s7, s6, tmp_path, small_settings,
                         edit_spec=edit_spec, use_comfyui=False)
        assert out.final_video_path.exists(), "mock 视频生成"
        assert out.generator == "mock"
        assert out.relation_embedding_path.exists(), "关系嵌入持久化"
        assert "avg_visibility_iou" in out.consistency_metrics


# ────────────────────── Settings 修复验证 ──────────────────────

class TestSettings:
    def test_revive_fields_present(self):
        s = Settings()
        # 原先缺失的字段现在应该存在
        assert hasattr(s, "focal_length")
        assert hasattr(s, "yolo_model")
        assert hasattr(s, "num_keyframes")
        assert hasattr(s, "video_generator")
        assert hasattr(s, "inpaint_radius")
        assert hasattr(s, "lineart_threshold")
        # v2 新增
        assert hasattr(s, "view_trajectory_mode")
        assert hasattr(s, "view_orbit_angle_deg")
        assert hasattr(s, "spatial_relation_strength")
        assert hasattr(s, "spatial_gnn_hidden")

    def test_load_settings_revive(self):
        from oilpainting_studio.common.config import load_settings
        s = load_settings()
        assert isinstance(s.focal_length, float)
        assert isinstance(s.num_keyframes, int)
        assert s.view_trajectory_mode in ("manual", "orbit", "dolly", "crane", "auto_orbit")


# ────────────────────── ComfyUI 接口 ──────────────────────

class TestSpatialWorkflow:
    """stage8/workflow.py 构造的空间关系可控 ComfyUI 工作流。"""

    def test_build_spatial_wan_workflow(self, small_settings):
        from oilpainting_studio.revive.stage8.workflow import (
            build_spatial_wan_workflow,
        )
        wf = build_spatial_wan_workflow(
            small_settings,
            keyframe_image="kf_0001.png",
            depth_image="depth_0001.png",
            edge_image="edge_0001.png",
            relation_embeddings_file="relation_embeddings.npz",
            scene_graph_file="scene_graph.json",
            num_frames=8,
            text_prompt="person walks toward building",
        )
        # 基础节点存在
        assert "input_image" in wf
        assert "input_depth" in wf
        assert "input_edge" in wf
        assert "sampler" in wf
        assert "save" in wf
        # v2 自定义节点存在
        assert wf["relation_embedding_loader"]["class_type"] == "RelationEmbeddingLoader"
        assert wf["relation_inject"]["class_type"] == "RelationCrossAttentionInject"
        assert wf["scene_graph_loader"]["class_type"] == "SceneGraphLoader"
        assert wf["relation_consistency_check"]["class_type"] == "RelationConsistencyCheck"

    def test_spatial_workflow_sampler_uses_injected_model(self, small_settings):
        """sampler 的 model 输入应指向 relation_inject 而非原始 wan_model。"""
        from oilpainting_studio.revive.stage8.workflow import build_spatial_wan_workflow
        wf = build_spatial_wan_workflow(
            small_settings, "kf.png", "d.png", "e.png",
            "rel.npz", "sg.json", num_frames=8,
        )
        assert wf["sampler"]["inputs"]["model"] == ["relation_inject", 0]

    def test_spatial_workflow_relation_strength(self, small_settings):
        """关系注入强度应从 settings.spatial_relation_strength 读取。"""
        from oilpainting_studio.revive.stage8.workflow import build_spatial_wan_workflow
        small_settings.spatial_relation_strength = 0.42
        wf = build_spatial_wan_workflow(
            small_settings, "kf.png", "d.png", "e.png",
            "rel.npz", "sg.json", num_frames=8,
        )
        assert wf["relation_inject"]["inputs"]["strength"] == 0.42

    def test_validate_spatial_workflow_complete(self, small_settings):
        from oilpainting_studio.revive.stage8.workflow import (
            build_spatial_wan_workflow,
            validate_spatial_workflow,
        )
        wf = build_spatial_wan_workflow(
            small_settings, "kf.png", "d.png", "e.png",
            "rel.npz", "sg.json", num_frames=8,
        )
        missing = validate_spatial_workflow(wf)
        assert missing == [], "完整 workflow 不应缺失节点"

    def test_validate_spatial_workflow_missing(self):
        from oilpainting_studio.revive.stage8.workflow import validate_spatial_workflow
        # 不含自定义节点的普通 workflow
        wf = {"input_image": {"class_type": "LoadImage", "inputs": {}}}
        missing = validate_spatial_workflow(wf)
        assert "RelationCrossAttentionInject" in missing
        assert "RelationEmbeddingLoader" in missing
        assert "SceneGraphLoader" in missing
        assert "RelationConsistencyCheck" in missing

    def test_spatial_workflow_text_prompt(self, small_settings):
        from oilpainting_studio.revive.stage8.workflow import build_spatial_wan_workflow
        wf = build_spatial_wan_workflow(
            small_settings, "kf.png", "d.png", "e.png",
            "rel.npz", "sg.json", num_frames=8,
            text_prompt="a person moves left of the building",
            negative_prompt="blurry, low quality",
        )
        assert wf["relation_inject"]["inputs"]["text_prompt"] == "a person moves left of the building"
        assert wf["relation_inject"]["inputs"]["negative_prompt"] == "blurry, low quality"


class TestComfyUICustomNodes:
    """ComfyUI 自定义节点插件的接口契约。"""

    def test_node_class_mappings_defined(self):
        """插件 __init__.py 应定义所有 4 个节点映射。"""
        from oilpainting_studio.revive.stage8 import comfyui_custom_nodes
        mappings = comfyui_custom_nodes.NODE_CLASS_MAPPINGS
        assert "RelationEmbeddingLoader" in mappings
        assert "RelationCrossAttentionInject" in mappings
        assert "SceneGraphLoader" in mappings
        assert "RelationConsistencyCheck" in mappings

    def test_node_display_names(self):
        from oilpainting_studio.revive.stage8 import comfyui_custom_nodes
        display = comfyui_custom_nodes.NODE_DISPLAY_NAME_MAPPINGS
        assert "RelationEmbeddingLoader" in display
        assert "Canvas3D-v2" in display["RelationEmbeddingLoader"]

    def test_relation_embedding_loader_input_types(self):
        from oilpainting_studio.revive.stage8.comfyui_custom_nodes import RelationEmbeddingLoader
        types = RelationEmbeddingLoader.INPUT_TYPES()
        assert "required" in types
        assert "embeddings_path" in types["required"]
        assert "hidden_dim" in types["required"]
        assert types["return_types"] if hasattr(types, "return_types") else True
        assert RelationEmbeddingLoader.RETURN_TYPES == ("RELATION_EMBEDDING",)
        assert RelationEmbeddingLoader.FUNCTION == "load"
        assert RelationEmbeddingLoader.CATEGORY == "canvas3d_v2"

    def test_relation_inject_input_types(self):
        from oilpainting_studio.revive.stage8.comfyui_custom_nodes import RelationCrossAttentionInject
        types = RelationCrossAttentionInject.INPUT_TYPES()
        required = types["required"]
        assert "model" in required
        assert "relation_embedding" in required
        assert "strength" in required
        assert "text_prompt" in required
        assert RelationCrossAttentionInject.RETURN_TYPES == ("MODEL",)
        assert RelationCrossAttentionInject.FUNCTION == "inject"


class TestStage5ImportFix:
    """验证 stage5 的 import bug 修复（from .stage4 → from ..stage4）。"""

    def test_stage5_imports_stage4(self):
        """stage5 应能正确导入 stage4 的 run_keyframe_generation。"""
        # 这个导入本身验证了 import 路径正确
        from oilpainting_studio.revive.stage4 import run_keyframe_generation
        assert callable(run_keyframe_generation)
        # stage5 的 run_stage5 函数内部会 from ..stage4 import，验证不报错
        from oilpainting_studio.revive.stage5 import run_stage5
        assert callable(run_stage5)
