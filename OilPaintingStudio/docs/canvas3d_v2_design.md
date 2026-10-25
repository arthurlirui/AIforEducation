# Canvas3D-v2 设计文档：三维信息驱动的视角可控动态视频生成框架

> 在原 Canvas3D 四模块（PaintParse / MonoSplat / SketchComp / ArtiFlow）之上，
> 扩展为支持 **三维场景图 + 视角可控新视角生成 + 三维空间关系可控场景变换视频**
> 的完整框架。本文档为指导实现与论文修订的单一信源。

## 1. 动机与与原 Canvas3D 的关系

原 Canvas3D 解决了「单画物体级 3D 重排动画」：手绘线稿指定物体目标位置，
3D 物体重定位 + 填色补缺 + 双 ControlNet 视频合成。其能力边界是：

- **视角不可控**：相机轨迹由 `interpolate_camera_offsets` 固定为轻微弧线，
  用户无法指定「绕前景人物环绕 30°」「俯视下降」等任意视角；
- **空间关系隐式**：物体间只通过深度排序隐式表达前后关系，没有显式的
  「A 在 B 左侧 / A 比 B 高 / A 遮挡 B 一半」这类可推理、可编辑的空间图；
- **场景变换语义缺失**：视频生成只接受「深度 + 边缘」控制信号，无法接收
  「让人物走向建筑并背对镜头」这类三维空间关系变化的语义指令。

Canvas3D-v2 在保留原四模块作为感知-几何-合成-时序底座的前提下，新增三个
**正交可独立升级** 的模块，分别对应三个新能力：

| 新模块 | 关切 | 输入 | 输出 | 新能力 |
|--------|------|------|------|--------|
| **SceneGraph3D** (stage6) | 拓扑/空间关系 | stage1 分割 + stage2 物体级 3DGS | 带节点属性与关系边的 3D 场景图 | 显式、可编辑、可序列化的空间结构 |
| **ViewCtrl** (stage7) | 视角可控新视角 | 场景图 + 用户视角轨迹 | 多视角关键帧流 (RGB+Depth+Edge+Mask) | 任意视角探索，不再是固定弧线 |
| **SpatialFlow** (stage8) | 空间关系可控视频 | 视角关键帧 + 空间关系编辑 + 文本 | 三维关系可控的动态视频 | 用文本+空间图联合驱动场景变换 |

设计原则与原框架保持一致：**模块化关切分离 + 显式握手表示**。三个新模块
只通过小而可序列化的张量/JSON 与原四模块通信，可在不重训原模块的前提下
独立升级、独立替换、独立消融。

## 2. 总体架构

```
            原始油画 P
               │
        ┌──────▼──────┐
        │  PaintParse  │  stage1: 分割 + 深度 + 层序
        └──────┬──────┘
               │ {M_i}, M_bg, {d_i}, D_mono
        ┌──────▼──────┐
        │  MonoSplat   │  stage2: 物体级 3DGS + 度量重缩放
        └──────┬──────┘
               │ 3D library {G_i}, scene S, depth D
        ┌──────▼──────┐
        │ SceneGraph3D │  stage6 (新): 构建 3D 场景图
        └──────┬──────┘
               │ SceneGraph G_scene (节点+边+空间关系)
               │
        ┌──────┼──────────────┐
        │      ▼              ▼
        │  SketchComp      ViewCtrl        stage3 / stage7
        │  (线稿重排)      (视角轨迹)
        │      │              │
        │      │      {I_t, D_t, E_t, M_t^view}
        │      │              │
        │      │      ┌───────▼───────┐
        │      │      │  SpatialFlow   │  stage8 (新)
        │      │      │ (关系编辑+T2V) │
        │      │      └───────┬───────┘
        │      │              │
        └──────┴──────┬───────┘
                      ▼
                ArtiFlow 视频合成   stage5
                      │
                      ▼
              最终动态视频 V
```

- SketchComp 保留为「物体级位置编辑」入口（线稿指定目标 bbox）；
- ViewCtrl 是「相机级视角编辑」入口（轨迹/视角参数）；
- SpatialFlow 是「空间关系级语义编辑」入口（文本 + 关系图）；
- 三者输出在 ArtiFlow 统一合成为最终视频，控制信号可叠加。

## 3. SceneGraph3D (stage6) — 三维场景图构建

### 3.1 数据结构

```python
class SceneGraphNode(BaseModel):
    object_id: int
    label: str                       # 语义标签 (person/building/...)
    category: ObjectCategory
    node_type: Literal["foreground", "background"]
    # 几何属性
    center_3d: tuple[float, float, float]      # 世界坐标中心
    bbox_3d: tuple[float, float, float, float, float, float]
    volume: float                              # 包围盒体积
    height_3d: float                           # 米制高度
    depth_range: tuple[float, float]           # [near, far]
    # 渲染属性
    ply_path: Path                             # 对应 3DGS 模型
    mask_path: Path                            # 原始 2D mask
    # 语义属性
    salience: float                            # 显著性 [0,1]（面积+置信度+中心偏置）

class SpatialRelation(BaseModel):
    src_id: int
    dst_id: int
    rel_type: Literal[
        "left_of", "right_of", "above", "below",       # 2D 投影关系
        "in_front_of", "behind",                       # 深度关系
        "inside", "adjacent", "occludes",              # 拓扑关系
        "supports", "leans_on",                        # 物理支撑（启发式）
    ]
    confidence: float
    # 可量化属性
    distance_3d: float | None                  # 中心欧氏距离
    overlap_ratio: float | None                # mask 交叠比
    depth_gap: float | None                    # 深度间隔

class SceneGraph(BaseModel):
    nodes: list[SceneGraphNode]
    relations: list[SpatialRelation]
    background_node_id: int | None
    # 全局场景属性
    scene_extent: tuple[float, float, float]   # 场景三轴尺度
    focal_length: float
    principal_point: tuple[float, float]
    # 序列化路径
    graph_path: Path                            # JSON 持久化
```

### 3.2 构建算法

1. **节点构建**：遍历 stage1 的 `SegmentedObject` + stage2 的 `GSModelRecord`，
   用度量重缩放后的 `bbox_3d` / `center_3d` 填几何属性；
   `salience = 0.5 * normalized_area + 0.3 * confidence + 0.2 * center_bias`。
2. **2D 投影关系**：对每对前景物体 (i, j)，比较 `center_3d` 的 x/y 分量，
   阈值 `ε_xy = 0.1 * scene_extent[0]`，生成 left_of/right_of/above/below。
3. **深度关系**：比较 `depth_range`，若 `d_i^far < d_j^near` 则 i `in_front_of` j；
   否则按质心深度比较生成 in_front_of/behind，置信度按间隔归一化。
4. **拓扑关系**：
   - `occludes`：2D mask 交叠 + 深度前后 → overlap_ratio > 0.05；
   - `inside`：mask 内含（IoU > 0.9 且面积比 > 0.8）；
   - `adjacent`：mask 距离 < ε_adj 且无交叠。
5. **物理支撑（启发式）**：若 i 的 bbox 底面 y ≈ j 的 bbox 顶面 y（容差 5% scene_extent）
   且 i 在 j 之上，标记 `supports`/`leans_on`。
6. **背景节点**：单独建一个 background 节点，与所有前景生成 `behind` 关系。
7. **场景尺度**：所有前景 bbox_3d 并集的外接盒。

### 3.3 序列化与可编辑性

`SceneGraph` 序列化为 `stage6/scene_graph.json`，并提供 `edit_node`/`edit_relation`
接口供下游模块修改。这是「空间关系可控」的关键 —— 用户的编辑直接作用于图，
而非作用于像素。

## 4. ViewCtrl (stage7) — 视角可控新视角渲染

### 4.1 视角轨迹规格

```python
class CameraPose(BaseModel):
    position: tuple[float, float, float]      # 相机位置 (世界坐标)
    look_at: tuple[float, float, float]       # 注视点
    up: tuple[float, float, float] = (0, 1, 0)
    fov_deg: float = 55.0

class ViewpointTrajectory(BaseModel):
    poses: list[CameraPose]
    interpolation: Literal["bspline", "linear", "lookat_orbit"] = "bspline"
    # 自动生成参数
    mode: Literal["manual", "orbit", "dolly", "crane", "auto_orbit"] = "manual"
    orbit_params: dict | None = None          # {center, radius, angle_range, axis}
```

### 4.2 视角生成模式

- **manual**：用户直接给 poses 列表；
- **orbit**：围绕场景图某个节点做轨道：`center = node.center_3d`，
  `radius = 1.5 * node.height_3d`，`angle_range` 由用户指定；
- **dolly**：沿场景主轴推拉：从 `pos0` 到 `pos0 + t * (look_at - pos0) * factor`；
- **crane**：垂直俯仰：y 从 h0 到 h1，look_at 不变；
- **auto_orbit**：以场景图显著性最高的前景节点为焦点自动环绕 30°。

### 4.3 渲染

每个 CameraPose 用现有的 `render_keyframe_from_scene` 升级版渲染：
- 输入：stage3 的 edited_scene.ply（或原始 stage2 scene.ply）+ CameraPose
- 输出：`{I_t, D_t, E_t, M_t^view}`，其中 `M_t^view` 是每个前景节点的可见性 mask
  （从该视角投影节点 bbox，判断是否在视锥内 + 是否被前层遮挡）。

可见性 mask 是 SpatialFlow 的关键输入：它告诉视频模型「这个视角下哪些物体
应该可见、哪些被遮挡」，从而在视角变化时保持 3D 一致性。

## 5. SpatialFlow (stage8) — 空间关系可控视频生成

### 5.1 空间关系编辑规格

```python
class SpatialEdit(BaseModel):
    edit_type: Literal["move", "rotate", "scale", "add_relation",
                       "remove_relation", "change_relation"]
    target_node_id: int | None
    # move/rotate/scale 的参数
    translation: tuple[float, float, float] | None = None
    rotation_deg: float | None = None
    scale_factor: float | None = None
    # 关系编辑
    relation: SpatialRelation | None = None
    # 文本描述（供 T2V 模型理解意图）
    text_prompt: str = ""

class SpatialEditSpec(BaseModel):
    edits: list[SpatialEdit]
    edited_graph_path: Path                   # 编辑后场景图
    # 视频生成参数
    text_prompt: str                          # 全局视频意图
    negative_prompt: str = ""
    num_frames: int = 25
    fps: int = 8
    # 控制信号强度
    depth_strength: float = 0.85
    edge_strength: float = 0.6
    relation_strength: float = 0.7            # 关系图注入强度
```

### 5.2 三路控制信号注入

SpatialFlow 在 ArtiFlow 的「深度 + 边缘」双控制之上，新增第三路：
**关系图嵌入（relation graph embedding）**。

1. **图编码**：将编辑后的 SceneGraph 用轻量 GNN（或预训练图编码器）编码为
   per-node embedding，再池化为 per-frame 上下文向量 `c_t^rel`；
2. **轨迹感知注入**：每个视角帧 `t` 的可见节点集 `V_t` 不同，
   `c_t^rel = Pool({h_i : i ∈ V_t})`，使视角变化时关系上下文自适应；
3. **注入方式**：通过 cross-attention 注入 video diffusion backbone 的
   transformer 块（与文本 prompt 共享 K/V 空间），强度由 `relation_strength` 控制。

### 5.3 三种生成模式

- **I2V 模式**：第一帧 = ViewCtrl 渲染的关键帧 + 深度 + 边缘 + 关系图 → 视频扩散；
- **T2V 模式**：纯文本 + 关系图 → 先生成首帧（image diffusion）再 I2V；
- **混合模式**：用户提供首帧 + 文本 + 关系图 → I2V，关系图作为「空间约束先验」。

### 5.4 一致性校验闭环

生成后用场景图校验：
- 每帧检测前景物体 mask，与 ViewCtrl 渲染的 `M_t^view` 计算可见性 IoU；
- 检查编辑后的空间关系（如「A 应在 B 左侧」）在生成帧中是否成立；
- 若违反，触发 re-prompt：增强 relation_strength 或在文本中显式补述关系。
这构成 stage8 → stage7 → stage8 的反馈闭环（论文中的 re-composition loop 升级版）。

## 6. 与原模块的集成

### 6.1 stage 编排

```
stage1 → stage2 → stage6 → ┬→ stage3 (可选，线稿重排)
                            └→ stage7 (视角轨迹) → stage8 (关系视频) → stage5 (ArtiFlow 合成)
```

- stage6 一定执行（构建场景图是后续一切的基础）；
- stage3 可选：若用户只做视角探索不做物体重排，可跳过；
- stage7 必须执行：视角轨迹决定关键帧流；
- stage8 可选：若用户只做新视角静态渲染不生成变换视频，可止于 stage7；
- stage5 是最终视频合成，接收 stage8 输出。

### 6.2 Settings 扩展

在 `Settings` dataclass 新增 revive 相关字段（修复现状：config.yaml 有但
dataclass 无），并新增 v2 字段：

```python
# 原 revive 字段（修复补齐）
yolo_model: str = "yolov8x-seg.pt"
yolo_conf_threshold: float = 0.4
focal_length: float = 1000.0
gaussians_per_object: int = 5000
inpaint_radius: int = 5
inpaint_method: str = "telea"
lineart_threshold: float = 0.15
video_generator: str = "wan2.2"
num_keyframes: int = 5
duration_sec: int = 5

# v2 新增
scene_graph_threshold_xy: float = 0.1   # 2D 关系判定阈值（场景尺度比例）
scene_graph_overlap_threshold: float = 0.05
view_trajectory_mode: str = "auto_orbit"
view_orbit_angle_deg: float = 30.0
view_num_poses: int = 8
spatial_relation_strength: float = 0.7
spatial_text_mode: str = "i2v"          # i2v / t2v / hybrid
spatial_gnn_hidden: int = 128
```

## 7. 实现计划

1. **schemas.py 扩展**：新增 SceneGraphNode / SpatialRelation / SceneGraph /
   CameraPose / ViewpointTrajectory / SpatialEdit / SpatialEditSpec /
   Stage6Output / Stage7Output / Stage8Output。
2. **stage6/scene_graph.py**：`build_scene_graph(stage1, stage2) -> Stage6Output`。
3. **stage7/viewpoint.py**：`generate_trajectory(scene_graph, spec) -> ViewpointTrajectory`；
   `render_viewpoint_keyframes(scene_ply, trajectory) -> Stage7Output`。
4. **stage8/spatial_video.py**：`encode_relation_graph(scene_graph, visible_ids) -> tensor`；
   `generate_spatial_video(stage7, edit_spec, scene_graph) -> Stage8Output`。
5. **revive/cli.py + director**：新增 `--view-mode`、`--orbit-angle`、
   `--spatial-prompt`、`--edit-graph` 等 CLI 参数，编排 stage6/7/8。
6. **Settings 补齐**：在 dataclass + load_settings 中补齐所有 revive 字段。
7. **测试**：`tests/test_scene_graph.py`、`tests/test_viewpoint.py`、
   `tests/test_spatial_video.py`（全 mock，不依赖 ComfyUI）。
8. **论文修订**：在 method.tex 新增 §3.5 SceneGraph3D / §3.6 ViewCtrl / §3.7 SpatialFlow，
   更新 overview 图、algorithm、experiment 的消融与定性结果。

## 8. 论文修订要点

- **标题**：从「Object-Level 3D Lifting and Line-Art Composition for Painting Animation」
  扩展为「Canvas3D-v2: Scene-Graph-Grounded Viewpoint-Controllable Painting Animation
  with Spatial-Relation-Driven Video Synthesis」；
- **Abstract**：在原四模块后强调「场景图 + 视角可控 + 关系驱动视频」三个新关切；
- **Contributions**：新增 (6) 场景图表征、(7) 视角可控新视角生成、(8) 关系图驱动的
  video diffusion 控制信号注入；
- **Method**：新增三个小节，给出场景图构建算法、视角轨迹生成、三路控制信号公式；
- **Experiments**：新增 Q5（视角可控性定量评测：novel-view IoU、视角一致性）、
  Q6（空间关系准确率：relation accuracy in generated frames）；
- **Limitations**：补充关系图 GNN 的泛化性、视角外推极限的讨论。
