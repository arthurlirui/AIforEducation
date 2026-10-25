"""模块 8：ComfyUI 空间关系可控视频工作流构造。

在 stage5 的 Wan2.2 / LTX2.3 双 ControlNet（depth + edge）工作流之上，
新增第三路「关系图嵌入」控制信号。关系嵌入由 stage8 的 GNN 编码器生成，
持久化为 .npz 文件，通过 ComfyUI 自定义节点加载并注入 video diffusion
backbone 的 cross-attention。

== ComfyUI 接口契约 ==

本模块构造的 workflow JSON 包含以下自定义节点（需在 ComfyUI 侧实现）：

1. RelationEmbeddingLoader
   class_type: "RelationEmbeddingLoader"
   inputs:
     - embeddings_path: str   # .npz 文件在 ComfyUI input 目录下的相对路径
     - hidden_dim: int        # 嵌入维度（与 stage8 编码器一致，默认 128）
   outputs: RELATION_EMBEDDING  # (T, hidden_dim) 张量，T = 帧数

2. RelationCrossAttentionInject
   class_type: "RelationCrossAttentionInject"
   inputs:
     - model: MODEL           # 来自 wan_model_loader 的输出
     - relation_embedding: RELATION_EMBEDDING  # 来自 RelationEmbeddingLoader
     - strength: float        # 注入强度 (0.0-1.0)，对应 settings.spatial_relation_strength
     - text_prompt: str       # 全局视频意图文本（与关系图共享 K/V 空间）
   outputs: MODEL             # 注入关系上下文后的模型，传入 sampler

3. SceneGraphLoader (可选，用于一致性校验节点)
   class_type: "SceneGraphLoader"
   inputs:
     - graph_path: str        # scene_graph.json 在 ComfyUI input 目录下的相对路径
   outputs: SCENE_GRAPH

4. RelationConsistencyCheck (可选，生成后校验)
   class_type: "RelationConsistencyCheck"
   inputs:
     - frames: IMAGE          # 来自 sampler 的输出帧
     - scene_graph: SCENE_GRAPH
     - iou_threshold: float
   outputs: METRICS

== 工作流拓扑 ==

input_image ─┐
input_depth ─┼→ controlnet_depth ─┐
input_edge ──┼→ controlnet_canny ──┤
              │                     ↓
relation_emb ─→ RelationEmbeddingLoader ─→ RelationCrossAttentionInject ─→ sampler ─→ save
                                                    ↑
                                              wan_model_loader

== 降级策略 ==

若 ComfyUI 侧未安装上述自定义节点，本模块构造的 workflow 会在 ComfyUI
加载时报 "custom node not found" 错误。stage8 的 run_stage8() 会捕获此
错误并降级到 mock 路径（关键帧插值合成），保证管线始终可用。
"""
from __future__ import annotations

import copy
import json
import logging
import random
from pathlib import Path
from typing import Any

from ...common.config import Settings

logger = logging.getLogger(__name__)


def build_spatial_wan_workflow(
    settings: Settings,
    keyframe_image: str,
    depth_image: str,
    edge_image: str,
    relation_embeddings_file: str,
    scene_graph_file: str,
    num_frames: int,
    text_prompt: str = "",
    negative_prompt: str = "",
    out_prefix: str = "canvas3d_v2_spatial",
) -> dict[str, Any]:
    """构造 Canvas3D-v2 空间关系可控 Wan2.2 工作流。

    在 stage5 的 build_wan_workflow 基础上，新增关系嵌入加载与注入节点。
    返回的 workflow JSON 包含自定义节点 RelationEmbeddingLoader 和
    RelationCrossAttentionInject，需在 ComfyUI 侧安装对应插件。
    """
    # 从 stage5 模板开始
    from ..stage5.workflow import load_workflow_template, apply_params

    template = load_workflow_template("wan2.2", settings.workflows_dir)

    # ── 1. 基础参数注入（与 stage5 build_wan_workflow 一致）──
    params = {
        "input_image": {"inputs.image": keyframe_image},
        "input_depth": {"inputs.image": depth_image},
        "input_edge": {"inputs.image": edge_image},
        "wan_model": {"inputs.model": settings.wan_model},
        "controlnet_depth": {
            "inputs.control_net_name": settings.controlnet_depth,
            "inputs.strength": settings.depth_guide_strength,
        },
        "controlnet_canny": {
            "inputs.control_net_name": settings.controlnet_canny,
            "inputs.strength": settings.edge_guide_strength,
        },
        "sampler": {
            "inputs.steps": settings.ltx_steps,
            "inputs.cfg": settings.ltx_cfg,
            "inputs.num_frames": num_frames,
        },
        "save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)

    # ── 2. 新增关系嵌入控制节点（v2 核心扩展）──

    # 2a. RelationEmbeddingLoader: 加载 .npz 关系嵌入
    wf["relation_embedding_loader"] = {
        "class_type": "RelationEmbeddingLoader",
        "inputs": {
            "embeddings_path": relation_embeddings_file,
            "hidden_dim": int(getattr(settings, "spatial_gnn_hidden", 128)),
        },
    }

    # 2b. RelationCrossAttentionInject: 将关系嵌入注入模型的 cross-attention
    #     接收 wan_model 的 MODEL 输出，返回增强后的 MODEL
    wf["relation_inject"] = {
        "class_type": "RelationCrossAttentionInject",
        "inputs": {
            # 引用 wan_model 节点的输出（假设模板中模型加载节点 id 为 "wan_model"）
            "model": ["wan_model", 0],
            "relation_embedding": ["relation_embedding_loader", 0],
            "strength": float(getattr(settings, "spatial_relation_strength", 0.7)),
            "text_prompt": text_prompt,
            "negative_prompt": negative_prompt,
        },
    }

    # 2c. SceneGraphLoader: 加载场景图（供一致性校验节点使用）
    wf["scene_graph_loader"] = {
        "class_type": "SceneGraphLoader",
        "inputs": {
            "graph_path": scene_graph_file,
        },
    }

    # 2d. RelationConsistencyCheck: 生成后校验（可选，接在 save 之前）
    wf["relation_consistency_check"] = {
        "class_type": "RelationConsistencyCheck",
        "inputs": {
            "frames": ["sampler", 0],
            "scene_graph": ["scene_graph_loader", 0],
            "iou_threshold": 0.7,
        },
    }

    # ── 3. 重连 sampler 的 model 输入：从 wan_model 改为 relation_inject ──
    # 原 sampler.inputs.model 可能是 ["wan_model", 0]，改为 ["relation_inject", 0]
    if "sampler" in wf and "model" in wf["sampler"].get("inputs", {}):
        wf["sampler"]["inputs"]["model"] = ["relation_inject", 0]

    # ── 4. 注入文本 prompt 到 sampler 的 positive conditioning ──
    # 假设模板中 sampler 有 positive 输入（WanVideoSampler 的 positive 条件）
    if "sampler" in wf and "positive" in wf["sampler"].get("inputs", {}):
        # 若 positive 已是节点引用，保留；若是文本，则追加关系 prompt
        positive = wf["sampler"]["inputs"]["positive"]
        if isinstance(positive, str) and text_prompt:
            wf["sampler"]["inputs"]["positive"] = f"{positive}. {text_prompt}"
        elif text_prompt:
            # positive 是节点引用：新增一个文本编码节点
            wf["spatial_text_encode"] = {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": text_prompt},
            }
            # 注意：实际拓扑需根据具体 Wan sampler 的 conditioning 接口调整
            # 此处保留接口示意，实际部署时按 ComfyUI Wan 节点规范连线

    # ── 5. 随机种子 ──
    wf["sampler"]["inputs"]["seed"] = random.randint(0, 2**63 - 1)

    # ── 6. 元数据：记录这是 v2 spatial workflow ──
    wf["_comment"] = (
        "Canvas3D-v2 SpatialFlow workflow. "
        "Requires custom nodes: RelationEmbeddingLoader, "
        "RelationCrossAttentionInject, SceneGraphLoader, "
        "RelationConsistencyCheck. "
        "Falls back to mock if custom nodes are unavailable."
    )

    return wf


def build_spatial_ltx_workflow(
    settings: Settings,
    rgb_video_name: str,
    depth_video_name: str,
    relation_embeddings_file: str,
    scene_graph_file: str,
    num_frames: int,
    text_prompt: str = "",
    out_prefix: str = "canvas3d_v2_spatial_ltx",
) -> dict[str, Any]:
    """构造 Canvas3D-v2 空间关系可控 LTX2.3 工作流。

    LTX 路径用 IC-LoRA Union Control（depth + rgb），关系嵌入通过
    RelationCrossAttentionInject 注入 ltx_model。
    """
    from ..stage5.workflow import load_workflow_template, apply_params

    template = load_workflow_template("ltx2.3", settings.workflows_dir)
    w, h = settings.ltx_5a_resolution

    params = {
        "input_rgb": {"inputs.video": rgb_video_name},
        "input_depth": {"inputs.video": depth_video_name},
        "ltx_model": {"inputs.model": settings.ltx_model},
        "iclora_loader": {
            "inputs.lora_name": settings.ltx_iclora,
            "inputs.strength_model": 1.0,
        },
        "iclora_guide_depth": {"inputs.strength": settings.depth_guide_strength},
        "iclora_guide_rgb": {"inputs.strength": settings.rgb_guide_strength},
        "sampler": {
            "inputs.steps": settings.ltx_steps,
            "inputs.cfg": settings.ltx_cfg,
            "inputs.width": w,
            "inputs.height": h,
            "inputs.num_frames": num_frames,
        },
        "save": {
            "inputs.filename_prefix": out_prefix,
            "inputs.frame_rate": settings.fps,
        },
    }
    wf = apply_params(template, params)

    # 关系嵌入节点（与 wan 路径一致）
    wf["relation_embedding_loader"] = {
        "class_type": "RelationEmbeddingLoader",
        "inputs": {
            "embeddings_path": relation_embeddings_file,
            "hidden_dim": int(getattr(settings, "spatial_gnn_hidden", 128)),
        },
    }
    wf["relation_inject"] = {
        "class_type": "RelationCrossAttentionInject",
        "inputs": {
            "model": ["ltx_model", 0],
            "relation_embedding": ["relation_embedding_loader", 0],
            "strength": float(getattr(settings, "spatial_relation_strength", 0.7)),
            "text_prompt": text_prompt,
            "negative_prompt": "",
        },
    }
    wf["scene_graph_loader"] = {
        "class_type": "SceneGraphLoader",
        "inputs": {"graph_path": scene_graph_file},
    }
    wf["relation_consistency_check"] = {
        "class_type": "RelationConsistencyCheck",
        "inputs": {
            "frames": ["sampler", 0],
            "scene_graph": ["scene_graph_loader", 0],
            "iou_threshold": 0.7,
        },
    }

    # 重连 sampler 的 model 输入
    if "sampler" in wf and "model" in wf["sampler"].get("inputs", {}):
        wf["sampler"]["inputs"]["model"] = ["relation_inject", 0]

    wf["sampler"]["inputs"]["seed"] = random.randint(0, 2**63 - 1)
    wf["_comment"] = (
        "Canvas3D-v2 SpatialFlow LTX workflow. "
        "Requires custom nodes: RelationEmbeddingLoader, "
        "RelationCrossAttentionInject, SceneGraphLoader, "
        "RelationConsistencyCheck."
    )
    return wf


def validate_spatial_workflow(wf: dict[str, Any]) -> list[str]:
    """校验 spatial workflow 是否包含所有必需的自定义节点。

    返回缺失的节点 class_type 列表（空列表表示全部就绪）。
    """
    required_class_types = {
        "RelationEmbeddingLoader",
        "RelationCrossAttentionInject",
        "SceneGraphLoader",
        "RelationConsistencyCheck",
    }
    present = {node.get("class_type") for node in wf.values()
               if isinstance(node, dict)}
    missing = required_class_types - present
    return sorted(missing)


# ── ComfyUI 自定义节点参考实现（伪代码，供 ComfyUI 侧插件开发参考）──
#
# 以下是四个自定义节点的 Python 参考实现，应作为 ComfyUI 自定义插件安装：
#
# class RelationEmbeddingLoader:
#     """加载 .npz 关系嵌入文件，返回 (T, hidden_dim) 张量。"""
#     @classmethod
#     def INPUT_TYPES(cls):
#         return {"required": {
#             "embeddings_path": ("STRING", {"default": ""}),
#             "hidden_dim": ("INT", {"default": 128}),
#         }}
#     RETURN_TYPES = ("RELATION_EMBEDDING",)
#     FUNCTION = "load"
#     CATEGORY = "canvas3d_v2"
#
#     def load(self, embeddings_path, hidden_dim):
#         import numpy as np
#         data = np.load(embeddings_path)
#         embeddings = data["embeddings"]  # (T, hidden_dim)
#         return (torch.from_numpy(embeddings).float(),)
#
#
# class RelationCrossAttentionInject:
#     """将关系嵌入注入 video diffusion 模型的 cross-attention 层。
#
#     通过 hook 模型的 transformer 块，在 text cross-attention 的 K/V 空间
#     拼接 relation_embedding，强度由 strength 控制。
#     """
#     @classmethod
#     def INPUT_TYPES(cls):
#         return {"required": {
#             "model": ("MODEL",),
#             "relation_embedding": ("RELATION_EMBEDDING",),
#             "strength": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0}),
#             "text_prompt": ("STRING", {"default": ""}),
#             "negative_prompt": ("STRING", {"default": ""}),
#         }}
#     RETURN_TYPES = ("MODEL",)
#     FUNCTION = "inject"
#     CATEGORY = "canvas3d_v2"
#
#     def inject(self, model, relation_embedding, strength, text_prompt, negative_prompt):
#         # 在 model 的 transformer 块上注册 forward hook，注入 relation_embedding
#         # 具体实现取决于 Wan2.2 / LTX2.3 的模型结构
#         # 伪代码：
#         # def hook(module, input, output):
#         #     # output: (B, T, D) cross-attention 上下文
#         #     T_frame = output.shape[1]
#         #     rel_ctx = relation_embedding[:T_frame] * strength
#         #     return torch.cat([output, rel_ctx.unsqueeze(0)], dim=1)
#         # model.model.diffusion_model.transformer_blocks[0].register_forward_hook(hook)
#         return (model,)
#
#
# class SceneGraphLoader:
#     """加载 scene_graph.json，返回场景图对象。"""
#     @classmethod
#     def INPUT_TYPES(cls):
#         return {"required": {"graph_path": ("STRING", {"default": ""})}}
#     RETURN_TYPES = ("SCENE_GRAPH",)
#     FUNCTION = "load"
#     CATEGORY = "canvas3d_v2"
#
#     def load(self, graph_path):
#         import json
#         with open(graph_path) as f:
#             graph = json.load(f)
#         return (graph,)
#
#
# class RelationConsistencyCheck:
#     """生成后校验：检查每帧的物体可见性与空间关系是否与场景图一致。"""
#     @classmethod
#     def INPUT_TYPES(cls):
#         return {"required": {
#             "frames": ("IMAGE",),
#             "scene_graph": ("SCENE_GRAPH",),
#             "iou_threshold": ("FLOAT", {"default": 0.7}),
#         }}
#     RETURN_TYPES = ("METRICS",)
#     FUNCTION = "check"
#     CATEGORY = "canvas3d_v2"
#
#     def check(self, frames, scene_graph, iou_threshold):
#         # 对每帧跑分割，检查 visible_node_ids 与关系是否成立
#         # 返回 {"avg_visibility_iou": float, "relation_violation_rate": float}
#         return ({"avg_visibility_iou": 0.85, "relation_violation_rate": 0.1},)
#
#
# # ComfyUI 插件注册（在插件的 __init__.py 中）：
# NODE_CLASS_MAPPINGS = {
#     "RelationEmbeddingLoader": RelationEmbeddingLoader,
#     "RelationCrossAttentionInject": RelationCrossAttentionInject,
#     "SceneGraphLoader": SceneGraphLoader,
#     "RelationConsistencyCheck": RelationConsistencyCheck,
# }
# NODE_DISPLAY_NAME_MAPPINGS = {
#     "RelationEmbeddingLoader": "Canvas3D-v2 Relation Embedding Loader",
#     "RelationCrossAttentionInject": "Canvas3D-v2 Relation Cross-Attn Inject",
#     "SceneGraphLoader": "Canvas3D-v2 Scene Graph Loader",
#     "RelationConsistencyCheck": "Canvas3D-v2 Relation Consistency Check",
# }
