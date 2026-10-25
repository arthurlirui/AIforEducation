# Canvas3D-v2 ComfyUI 自定义节点插件接口规范

本文档定义 Canvas3D-v2 SpatialFlow 模块与 ComfyUI 交互所需的四个自定义节点。
stage8/workflow.py 构造的 workflow JSON 引用这些节点的 class_type，ComfyUI 侧
需安装对应插件才能执行；未安装时 stage8 自动降级到 mock 路径。

## 安装位置

将本目录下的 `comfyui_custom_nodes/` 文件夹拷贝或软链接到 ComfyUI 的
`custom_nodes/` 目录，重启 ComfyUI 即可自动加载。

## 四个自定义节点

### 1. RelationEmbeddingLoader

**用途**：加载 stage8 GNN 编码器生成的 `.npz` 关系嵌入文件，返回 `(T, hidden_dim)` 张量。

| 字段 | 值 |
|------|-----|
| class_type | `RelationEmbeddingLoader` |
| 分类 | `canvas3d_v2` |
| 输入 | `embeddings_path` (STRING): .npz 在 ComfyUI input 目录下的相对路径 |
|       | `hidden_dim` (INT, 默认 128): 嵌入维度 |
| 输出 | `RELATION_EMBEDDING`: (T, hidden_dim) float 张量 |

**npz 文件格式**：
```python
import numpy as np
data = np.load("relation_embeddings.npz")
embeddings = data["embeddings"]  # shape (T, hidden_dim), T = 帧数
```

### 2. RelationCrossAttentionInject

**用途**：将关系嵌入注入 video diffusion 模型的 cross-attention 层，与文本 prompt
共享 K/V 空间，实现「文本 + 关系图」联合驱动。

| 字段 | 值 |
|------|-----|
| class_type | `RelationCrossAttentionInject` |
| 分类 | `canvas3d_v2` |
| 输入 | `model` (MODEL): 来自模型加载器的输出 |
|       | `relation_embedding` (RELATION_EMBEDDING): 来自 RelationEmbeddingLoader |
|       | `strength` (FLOAT, 默认 0.7, 范围 0-1): 注入强度 |
|       | `text_prompt` (STRING): 全局视频意图文本 |
|       | `negative_prompt` (STRING): 负向提示 |
| 输出 | `MODEL`: 注入关系上下文后的模型 |

**注入机制**：在 model 的 transformer 块上注册 forward hook，将 relation_embedding
拼接到 cross-attention 的 K/V 空间，强度由 `strength` 缩放。具体实现取决于
Wan2.2 / LTX2.3 的 transformer 结构。

### 3. SceneGraphLoader

**用途**：加载 `scene_graph.json`，返回场景图对象供一致性校验节点使用。

| 字段 | 值 |
|------|-----|
| class_type | `SceneGraphLoader` |
| 分类 | `canvas3d_v2` |
| 输入 | `graph_path` (STRING): JSON 在 ComfyUI input 目录下的相对路径 |
| 输出 | `SCENE_GRAPH`: 场景图字典 |

### 4. RelationConsistencyCheck

**用途**：生成后校验，检查每帧的物体可见性与空间关系是否与场景图一致。

| 字段 | 值 |
|------|-----|
| class_type | `RelationConsistencyCheck` |
| 分类 | `canvas3d_v2` |
| 输入 | `frames` (IMAGE): 来自 sampler 的输出帧序列 |
|       | `scene_graph` (SCENE_GRAPH): 来自 SceneGraphLoader |
|       | `iou_threshold` (FLOAT, 默认 0.7): 可见性 IoU 阈值 |
| 输出 | `METRICS`: `{"avg_visibility_iou": float, "relation_violation_rate": float}` |

## 工作流拓扑

```
input_image ─┐
input_depth ─┼→ controlnet_depth ─┐
input_edge ──┼→ controlnet_canny ──┤
              │                     ↓
relation_emb ─→ RelationEmbeddingLoader ─→ RelationCrossAttentionInject ─→ sampler ─→ save
                                                    ↑
                                              wan_model_loader
                                                    ↑
scene_graph ──→ SceneGraphLoader ─→ RelationConsistencyCheck
```

## 降级策略

若 ComfyUI 侧未安装上述自定义节点：
1. `stage8/workflow.py` 的 `validate_spatial_workflow()` 检测到缺失节点
2. `stage8/__init__.py` 的 `generate_comfyui_video()` 抛出 RuntimeError
3. `run_stage8()` 捕获错误，降级到 `generate_mock_video()`（关键帧插值合成）
4. 管线始终可用，不会因 ComfyUI 插件缺失而中断

## 节点注册

在插件的 `__init__.py` 中：
```python
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
```
