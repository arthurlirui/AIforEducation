"""全流程测试：四模块流水线端到端（mock 模式）。

不依赖 YOLO / DepthAnything / TripoSplat / ComfyUI / Wan2.2 / LTX2.3。
全部用 fallback mock 实现，验证数据流衔接与产物完整性。

模块 1: YOLO 多物体分割 → 多物体 mask + 背景
模块 2: TripoSplat 3DGS 生成 + 模型注册表
模块 3: 线稿引导 3DGS 重定位 + 填色补缺
模块 4: 关键帧渲染 + ComfyUI ControlNet 动画生成
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# 让 src 可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oilrev.config import load_settings
from oilrev.pipeline.director import run_pipeline
from oilrev.schemas import Stage1Output, Stage2Output, Stage3Output, Stage4Output


@pytest.fixture
def test_painting(tmp_path) -> Path:
    """生成一张测试用"油画"图像（合成渐变 + 噪声模拟笔触）。"""
    h, w = 480, 360  # 小尺寸加速测试
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # 上方天空（蓝色），中间建筑（棕色），下方人物（暖色）
    img[: h // 3, :] = [180, 130, 60]      # 蓝天
    img[h // 3 : 2 * h // 3, :] = [80, 60, 140]  # 棕色建筑
    img[2 * h // 3 :, :] = [120, 100, 180]  # 暖色人物
    # 加噪声模拟笔触
    noise = np.random.randint(-30, 30, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    path = tmp_path / "test_painting.png"
    cv2.imwrite(str(path), img)
    return path


@pytest.fixture
def test_settings(tmp_path) -> "Settings":
    """小尺寸测试配置。"""
    s = load_settings()
    s.width = 360
    s.height = 480
    s.fps = 8
    s.duration_sec = 1  # 8 帧
    s.focal_length = 500.0
    s.output_dir = tmp_path / "output"
    s.gaussians_per_object = 200
    s.edge_align_iterations = 5  # 少量迭代加速
    s.num_keyframes = 3
    s.inpaint_radius = 3
    return s


class TestModule1:
    """模块 1 单独测试：YOLO 分割 + 深度 + 背景。"""

    def test_segmentation(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        assert len(s1.objects) >= 1, "至少检测到一个物体"
        assert s1.depth_path.exists(), "深度图存在"
        assert s1.background_mask_path.exists(), "背景掩码存在"
        assert s1.background_path.exists(), "背景图像存在"
        assert s1.width == 360 and s1.height == 480
        for obj in s1.objects:
            assert obj.mask_path.exists(), f"物体 {obj.object_id} mask 存在"
            assert obj.crop_path.exists(), f"物体 {obj.object_id} 裁剪图存在"
            assert obj.depth_range[0] <= obj.depth_range[1], "深度范围有效"
            assert obj.bbox[2] > obj.bbox[0] and obj.bbox[3] > obj.bbox[1], "包围盒有效"

    def test_background_preservation(self, test_painting, test_settings, tmp_path):
        """背景掩码 = 所有前景之外的区域。"""
        from oilrev.stage1 import run_stage1
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        bg_mask = cv2.imread(str(s1.background_mask_path), cv2.IMREAD_GRAYSCALE)
        # 合并所有前景 mask
        fg_union = np.zeros_like(bg_mask)
        for obj in s1.objects:
            mask = cv2.imread(str(obj.mask_path), cv2.IMREAD_GRAYSCALE)
            fg_union = np.maximum(fg_union, mask)
        # 验证背景 = ~前景
        expected_bg = 255 - fg_union
        # 允许少量差异（边缘膨胀等）
        diff = np.abs(bg_mask.astype(int) - expected_bg.astype(int))
        assert diff.mean() < 50, "背景掩码应与前景互补"

    def test_auto_canny_edge(self, test_painting, test_settings, tmp_path):
        """无线稿时自动生成 Canny 边缘。"""
        from oilrev.stage1 import run_stage1
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        assert s1.controls.edge_path is not None
        assert s1.controls.edge_path.exists()


class TestModule2:
    """模块 2 单独测试：TripoSplat 3DGS 生成 + 模型注册表。"""

    def test_3dgs_generation(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        assert s2.scene_ply_path.exists(), "统一场景 PLY 存在"
        assert s2.registry.num_models == len(s1.objects), "每个物体一个 3DGS 模型"
        for record in s2.registry.models:
            assert record.ply_path.exists(), f"模型 {record.object_id} PLY 存在"
            assert record.num_gaussians > 0, "高斯点数 > 0"
            assert len(record.center_3d) == 3, "3D 中心存在"

    def test_model_registry(self, test_painting, test_settings, tmp_path):
        """模型注册表查找功能。"""
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        for obj in s1.objects:
            record = s2.registry.get_model(obj.object_id)
            assert record is not None, f"物体 {obj.object_id} 在注册表中"
            assert record.label == obj.label, "标签匹配"
        # 不存在的 ID
        assert s2.registry.get_model(999) is None

    def test_background_2dgs(self, test_painting, test_settings, tmp_path):
        """背景生成 2DGS surfel。"""
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        assert s2.registry.background_ply_path is not None
        assert s2.registry.background_ply_path.exists()


class TestModule3:
    """模块 3 单独测试：线稿引导重定位 + 填色补缺。"""

    def test_repositioning(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        assert len(s3.transforms) == len(s1.objects), "每个物体一个变换"
        assert s3.edited_scene_ply_path.exists(), "编辑后场景 PLY 存在"
        assert s3.inpainted_background_path.exists(), "填色补缺背景图存在"
        assert s3.keyframe_path.exists(), "关键帧存在"
        assert s3.keyframe_depth_path.exists(), "关键帧深度图存在"
        assert s3.keyframe_edge_path.exists(), "关键帧边缘图存在"
        for tr in s3.transforms:
            assert tr.object_id >= 0, "物体 ID 有效"
            assert len(tr.translation) == 3, "平移 3D"
            assert 0.0 <= tr.edge_iou <= 1.0, "IoU 在 [0,1]"

    def test_inpainting(self, test_painting, test_settings, tmp_path):
        """填色补缺后背景图无空洞。"""
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        bg = cv2.imread(str(s3.inpainted_background_path))
        assert bg is not None, "背景图可读"
        assert bg.shape[:2] == (test_settings.height, test_settings.width)

    def test_keyframe_dimensions(self, test_painting, test_settings, tmp_path):
        """关键帧尺寸正确。"""
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        kf = cv2.imread(str(s3.keyframe_path))
        assert kf.shape[:2] == (test_settings.height, test_settings.width)


class TestModule4:
    """模块 4 单独测试：关键帧 + 动画生成（mock 模式）。"""

    def test_keyframe_generation(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        from oilrev.stage4 import run_keyframe_generation
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        keyframes = run_keyframe_generation(s3, tmp_path / "p", test_settings)
        assert len(keyframes) == test_settings.num_keyframes
        for kf in keyframes:
            assert kf.render_path.exists(), f"关键帧 {kf.frame_index} 渲染图存在"
            assert kf.depth_path.exists(), f"关键帧 {kf.frame_index} 深度图存在"
            assert kf.edge_path.exists(), f"关键帧 {kf.frame_index} 边缘图存在"

    def test_mock_animation(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        from oilrev.stage4 import run_keyframe_generation
        from oilrev.stage5 import run_stage5
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        keyframes = run_keyframe_generation(s3, tmp_path / "p", test_settings)
        s4 = run_stage5(s3, tmp_path / "p", test_settings, keyframes, use_comfyui=False)
        assert s4.final_video_path.exists(), "最终视频存在"
        assert s4.final_video_path.suffix == ".mp4"
        assert s4.final_video_path.stat().st_size > 0, "视频非空"
        assert s4.generator == "mock"


class TestFullPipeline:
    """端到端全流程测试。"""

    def test_run_pipeline_mock(self, test_painting, test_settings, tmp_path):
        """四模块端到端，全部 mock，验证最终视频产物。"""
        final = run_pipeline(
            test_settings, test_painting,
            project_id="test_e2e",
            use_comfyui=False,
        )
        assert final.exists()
        assert final.suffix == ".mp4"
        assert final.stat().st_size > 0
        # 检查 meta.json
        meta_path = test_settings.output_dir / "test_e2e" / "meta.json"
        assert meta_path.exists()
        import json
        meta = json.loads(meta_path.read_text())
        assert "1" in meta["stages"], "模块 1 完成"
        assert "4" in meta["stages"], "模块 4 完成"

    def test_checkpoint_persistence(self, test_painting, test_settings, tmp_path):
        """验证检查点：各模块产物落盘。"""
        run_pipeline(
            test_settings, test_painting,
            project_id="test_ckpt",
            use_comfyui=False,
        )
        pdir = test_settings.output_dir / "test_ckpt"
        # 模块 1
        assert (pdir / "stage1" / "depth.png").exists()
        assert (pdir / "stage1" / "mask_background.png").exists()
        assert (pdir / "stage1" / "background.png").exists()
        assert list((pdir / "stage1").glob("mask_obj*.png")), "物体 mask 存在"
        # 模块 2
        assert (pdir / "stage2" / "scene_unified.ply").exists()
        assert (pdir / "stage2" / "background_2dgs.ply").exists()
        assert list((pdir / "stage2").glob("object_*.ply")), "物体 3DGS 模型存在"
        # 模块 3
        assert (pdir / "stage3" / "edited_scene.ply").exists()
        assert (pdir / "stage3" / "inpainted_background.png").exists()
        assert (pdir / "stage3" / "keyframe.png").exists()
        # 模块 4
        assert (pdir / "stage4" / "keyframes").exists()
        assert (pdir / "stage5" / "final_mock.mp4").exists()


class TestSchemas:
    """数据模型校验。"""

    def test_stage1_output_serializable(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        j = s1.model_dump_json()
        assert "objects" in j
        assert "depth_path" in j
        assert "background_path" in j

    def test_model_registry_serializable(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        j = s2.model_dump_json()
        assert "registry" in j
        assert "models" in j

    def test_reposition_transform_serializable(self, test_painting, test_settings, tmp_path):
        from oilrev.stage1 import run_stage1
        from oilrev.stage2 import run_stage2
        from oilrev.stage3 import run_stage3
        s1 = run_stage1(test_painting, tmp_path / "p", test_settings)
        s2 = run_stage2(s1, tmp_path / "p", test_settings)
        s3 = run_stage3(s1, s2, tmp_path / "p", test_settings)
        j = s3.model_dump_json()
        assert "transforms" in j
        assert "edge_iou" in j


class TestWorkflowTemplate:
    """模块 4 工作流模板测试。"""

    def test_ltx_template_loads(self):
        from oilrev.stage5.workflow import load_workflow_template
        wf = load_workflow_template("ltx2.3")
        assert "input_rgb" in wf
        assert "input_depth" in wf
        assert "sampler" in wf
        assert "save" in wf

    def test_wan_template_loads(self):
        from oilrev.stage5.workflow import load_workflow_template
        wf = load_workflow_template("wan2.2")
        assert "input_image" in wf
        assert "input_depth" in wf
        assert "input_edge" in wf
        assert "sampler" in wf
        assert "save" in wf

    def test_wan_workflow_param_injection(self, test_settings):
        from oilrev.stage5.workflow import build_wan_workflow
        wf = build_wan_workflow(test_settings, "kf.png", "depth.png", "edge.png", 9)
        assert wf["input_image"]["inputs"]["image"] == "kf.png"
        assert wf["input_depth"]["inputs"]["image"] == "depth.png"
        assert wf["input_edge"]["inputs"]["image"] == "edge.png"
        assert wf["sampler"]["inputs"]["num_frames"] == 9
        assert isinstance(wf["sampler"]["inputs"]["seed"], int)

    def test_ltx_workflow_param_injection(self, test_settings):
        from oilrev.stage5.workflow import build_ltx_workflow
        wf = build_ltx_workflow(test_settings, "rgb.mp4", "depth.mp4", 9)
        assert wf["input_rgb"]["inputs"]["video"] == "rgb.mp4"
        assert wf["input_depth"]["inputs"]["video"] == "depth.mp4"
        assert wf["sampler"]["inputs"]["num_frames"] == 9
        assert isinstance(wf["sampler"]["inputs"]["seed"], int)
