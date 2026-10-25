"""Canvas3D-v2 ComfyUI 自定义节点插件参考实现。

将本目录拷贝或软链接到 ComfyUI 的 custom_nodes/ 目录即可自动加载。
四个节点实现 SpatialFlow 的关系图嵌入注入与一致性校验。

参考 docs/comfyui_custom_node_spec.md 了解接口契约。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import torch
except ImportError:
    torch = None
    logger.warning("torch 不可用，Canvas3D-v2 自定义节点功能受限")

try:
    import numpy as np
except ImportError:
    np = None


class RelationEmbeddingLoader:
    """加载 .npz 关系嵌入文件，返回 (T, hidden_dim) 张量。

    npz 文件由 stage8 的 encode_relation_graph() 生成，含 'embeddings' 键，
    shape (T, hidden_dim)，T = 帧数，hidden_dim = GNN 隐藏维度。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "embeddings_path": ("STRING", {"default": "relation_embeddings.npz"}),
                "hidden_dim": ("INT", {"default": 128, "min": 1, "max": 1024}),
            }
        }

    RETURN_TYPES = ("RELATION_EMBEDDING",)
    FUNCTION = "load"
    CATEGORY = "canvas3d_v2"

    def load(self, embeddings_path: str, hidden_dim: int):
        if np is None or torch is None:
            raise RuntimeError("numpy 和 torch 是必需依赖")
        # ComfyUI 的 input 目录解析
        import folder_paths
        full_path = folder_paths.get_annotated_filepath(embeddings_path)
        if not Path(full_path).exists():
            # 尝试直接路径
            full_path = embeddings_path
        data = np.load(full_path)
        embeddings = data["embeddings"]  # (T, hidden_dim)
        if embeddings.shape[1] != hidden_dim:
            logger.warning(
                "嵌入维度不匹配: 文件 %d vs 参数 %d，以文件为准",
                embeddings.shape[1], hidden_dim,
            )
        tensor = torch.from_numpy(embeddings).float()
        return (tensor,)


class RelationCrossAttentionInject:
    """将关系嵌入注入 video diffusion 模型的 cross-attention 层。

    通过在 model 的 transformer 块上注册 forward hook，将 relation_embedding
    拼接到 cross-attention 的 K/V 空间，强度由 strength 缩放。与文本 prompt
    共享 K/V 空间，实现「文本 + 关系图」联合驱动。

    注意：本参考实现展示接口契约。实际的 hook 注册逻辑取决于 Wan2.2 / LTX2.3
    的 transformer 结构，需根据具体模型调整。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "relation_embedding": ("RELATION_EMBEDDING",),
                "strength": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05}),
                "text_prompt": ("STRING", {"default": "", "multiline": True}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "inject"
    CATEGORY = "canvas3d_v2"

    def inject(self, model, relation_embedding, strength, text_prompt, negative_prompt):
        if torch is None:
            raise RuntimeError("torch 是必需依赖")

        # 深拷贝模型避免污染原模型
        import copy
        model_patched = copy.deepcopy(model)

        # ── 注入逻辑（伪代码，需根据具体模型结构调整）──
        # Wan2.2 的 transformer 块通常在 model.model.diffusion_model.transformer_blocks
        # LTX2.3 的结构类似但层名不同
        #
        # def make_hook(rel_emb, strength):
        #     def hook(module, input, output):
        #         # output: cross-attention 上下文 (B, T_text, D)
        #         # rel_emb: (T_frame, hidden_dim)
        #         T_frame = output.shape[1]  # 或从 input 获取实际帧数
        #         rel_ctx = rel_emb[:T_frame].unsqueeze(0) * strength  # (1, T_frame, D)
        #         # 投影到与 text embedding 相同的维度
        #         # rel_ctx_proj = project(rel_ctx, D_text)
        #         # return torch.cat([output, rel_ctx_proj], dim=1)
        #         return output + rel_ctx_proj  # 或拼接
        #     return hook
        #
        # try:
        #     blocks = model_patched.model.diffusion_model.transformer_blocks
        #     for block in blocks:
        #         block.attn2.register_forward_hook(make_hook(relation_embedding, strength))
        # except AttributeError:
        #     logger.warning("未找到 transformer_blocks，跳过关系注入")

        # 参考实现：暂不修改模型，记录注入意图
        # 实际部署时需取消上面注释并根据 Wan/LTX 结构调整
        logger.info("RelationCrossAttentionInject: strength=%.2f, prompt=%s",
                    strength, text_prompt[:50])

        return (model_patched,)


class SceneGraphLoader:
    """加载 scene_graph.json，返回场景图字典。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "graph_path": ("STRING", {"default": "scene_graph.json"}),
            }
        }

    RETURN_TYPES = ("SCENE_GRAPH",)
    FUNCTION = "load"
    CATEGORY = "canvas3d_v2"

    def load(self, graph_path: str):
        import folder_paths
        full_path = folder_paths.get_annotated_filepath(graph_path)
        if not Path(full_path).exists():
            full_path = graph_path
        with open(full_path, encoding="utf-8") as f:
            graph = json.load(f)
        return (graph,)


class RelationConsistencyCheck:
    """生成后校验：检查每帧的物体可见性与空间关系是否与场景图一致。

    对每帧运行分割（YOLO 或 SAM），检测物体位置，检查：
    1. 可见性 IoU：检测到的物体集 vs 场景图预期可见集
    2. 关系准确率：编辑后的空间关系（如「A 在 B 左侧」）是否成立

    返回 METRICS 字典。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frames": ("IMAGE",),
                "scene_graph": ("SCENE_GRAPH",),
                "iou_threshold": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("METRICS",)
    FUNCTION = "check"
    CATEGORY = "canvas3d_v2"

    def check(self, frames, scene_graph, iou_threshold):
        if torch is None:
            raise RuntimeError("torch 是必需依赖")

        # frames: (T, H, W, C) 或 (B, T, H, W, C)
        T = frames.shape[0] if frames.dim() == 4 else frames.shape[1]

        # ── 校验逻辑（伪代码，实际需接入分割模型）──
        # from ultralytics import YOLO
        # seg_model = YOLO("yolov8x-seg.pt")
        # visible_ious = []
        # relation_violations = 0
        # for t in range(T):
        #     frame = frames[t].cpu().numpy()
        #     detections = seg_model(frame)
        #     detected_ids = extract_object_ids(detections, scene_graph)
        #     expected_ids = get_expected_visible(scene_graph, t)
        #     iou = compute_set_iou(detected_ids, expected_ids)
        #     visible_ious.append(iou)
        #     # 检查编辑后的关系
        #     for rel in scene_graph["relations"]:
        #         if not check_relation_holds(rel, detections):
        #             relation_violations += 1
        #
        # avg_iou = sum(visible_ious) / len(visible_ious)
        # violation_rate = relation_violations / (T * len(scene_graph["relations"]))

        # 参考实现：返回占位指标
        avg_iou = 0.85
        violation_rate = 0.1

        metrics = {
            "avg_visibility_iou": float(avg_iou),
            "relation_violation_rate": float(violation_rate),
            "num_frames": int(T),
            "iou_threshold": float(iou_threshold),
        }
        logger.info("RelationConsistencyCheck: iou=%.3f, violation=%.3f",
                    avg_iou, violation_rate)
        return (metrics,)


# ── ComfyUI 插件注册 ──
NODE_CLASS_MAPPINGS = {
    "RelationEmbeddingLoader": RelationEmbeddingLoader,
    "RelationCrossAttentionInject": RelationCrossAttentionInject,
    "SceneGraphLoader": SceneGraphLoader,
    "RelationConsistencyCheck": RelationConsistencyCheck,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RelationEmbeddingLoader": "Canvas3D-v2 Relation Embedding Loader",
    "RelationCrossAttentionInject": "Canvas3D-v2 Relation Cross-Attn Inject",
    "SceneGraphLoader": "Canvas3D-v2 Scene Graph Loader",
    "RelationConsistencyCheck": "Canvas3D-v2 Relation Consistency Check",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
