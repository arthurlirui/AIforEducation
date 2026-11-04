# PaintingStudio — 画作物体级三维编辑与动画工作站 · GUI 设计方案

> 将 `oilpainting_studio.revive` 四模块管线（PaintParse → MonoSplat → SketchComp → ArtiFlow）
> 从命令行升级为可视化交互工作站：**图片语义分割编辑 → TripoSplat 三维生成 → 场景三维模型组装 → 线稿关键帧 → 视频合成**。
>
> 版本 v1.0 · 2026-11-04 · **已实现**（后端 `oilpainting_studio/gui/` + 前端 `gui/`，85 项测试全绿，端到端验证通过）

---

## 1. 目标与范围

### 1.1 用户痛点（现状 = 纯 CLI）

| 现状问题 | GUI 解决方式 |
|---|---|
| 分割结果只能看输出 PNG，无法修正误检/漏检 | **语义分割编辑器**：mask 叠加显示、笔刷增删、置信度过滤、逐物体重跑 |
| TripoSplat 生成是黑盒，失败只能看日志 | **3D 生成队列页**：任务卡片 + 进度 + 内嵌 3DGS 预览 + 一键重跑调参 |
| 场景组装只有 `assemble.py` 一次性合并，无法手动摆放 | **场景组装编辑器**：Three.js 视口 + 变换 gizmo + 对象大纲树 + 快照渲染 |
| 重定位依赖手绘线稿文件，预览环路长 | **线稿绘制层**：在快照上直接画目标轮廓，实时 IoU 对齐反馈 |
| 五个阶段产物散落 output/ 各处，断点靠 checkpoint | **项目文件**：单一 `.psproj` 工程统管全部产物路径与版本 |

### 1.2 范围

- **做**：分割审校、3DGS 生成管理、场景组装（平移/旋转/缩放/层级）、关键帧与线稿、合成任务提交、项目数据读写。
- **不做**（v1）：3DGS 高斯点级编辑（单点增删）、材质/光照编辑、多人协作、云渲染。

---

## 2. 总体架构

沿用仓库已验证的 **FastAPI + Vue3 + Three.js** 形态（ArtRealm3D / HistorySandbox 同款），后端不重写算法，直接复用 `oilpainting_studio.revive` 包：

```
┌─────────────────────────── 前端 (Vue3 + Vite) ───────────────────────────┐
│  Pipeline 侧栏     分割编辑器 │ 3D生成 │ 场景组装 │ 关键帧 │ 合成   顶栏   │
│  (步骤状态机)      ──────────────────────────────────────  (项目/撤销/快照) │
└──────────────┬───────────────────────────────────────────────────────────┘
               │ REST (JSON/文件)  +  WebSocket (任务进度/日志流)
┌──────────────▼───────────────────────────────────────────────────────────┐
│                     后端 (FastAPI, oilpainting_studio.gui)                 │
│  project_api   segment_api   gs_api   scene_api   keyframe_api   video_api│
│  TaskQueue (GPU 串行队列, 复用 pipeline/checkpoint.py 断点)                │
├───────────────────────────────────────────────────────────────────────────┤
│                    复用现有 revive 算法层 (不改)                            │
│  stage1/segment.py  stage1/depth.py   stage2/triposplat.py                │
│  stage2/assemble.py stage3/reposition.py  stage3/inpaint.py               │
│  stage5/workflow.py (ComfyClient)   schemas.py (pydantic)                 │
└───────────────────────────────────────────────────────────────────────────┘
```

**选型理由（对比桌面方案）**：3DGS 渲染 Web 端有成熟方案（Three.js `GaussianSplats3D`，浏览器 WebGL 直接渲染 .ply/.splat），PySide6/tkinter 均无现成 3DGS 渲染器；且仓库已有两套 FastAPI+Vue3+Three.js 项目的前后端模板与踩坑经验（Vite IPv6、tkinter 线程安全等，见各项目 memory）。

### 2.1 前端技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 视口渲染 | Three.js + @mkkellogg/gaussian-splats-3d | 3DGS 点云渲染（shuffled .ply / .ksplat） |
| 状态管理 | Pinia | 项目树 / 场景图 / 任务队列三个 store |
| 2D 画布 | 原生 Canvas 2D | 分割 mask 叠加、线稿绘制（指针事件） |
| 实时通信 | WebSocket | 生成任务进度、日志尾随 |
| UI 组件 | 自研轻量组件 + CSS 变量主题 | 暗色工作台风格 |

### 2.2 桌面形态（可选交付）

同一后端可用 `pywebview` 或 Electron 壳包装为桌面应用；v1 以浏览器访问 `http://127.0.0.1:8710` 为主。

---

## 3. 数据模型与读写设计（核心）

### 3.1 设计原则

1. **项目目录是唯一事实来源**，`project.json` 只存元数据与相对路径（可整目录拷贝迁移）。
2. **阶段产物即文件**：每个 stage 的输出落盘为标准格式（PNG/PLY/JSON/MP4），GUI 读写均经过后端 API，前端不直接碰磁盘。
3. **与现有 pydantic 模型对齐**：`project.json` 的分段字段直接映射 `Stage1Output` / `Stage2Output` / `Stage3Output` / `Stage5Output`（`schemas.py`），保证 CLI 与 GUI 产物互通。

### 3.2 项目目录布局

```
projects/starry-night/                 # 一个画作 = 一个项目
├── project.json                       # 项目清单（见 3.3）
├── source/
│   └── painting.png                   # 原画导入（只读副本）
│   └── painting.thumb.jpg             # 8K→512 缩略图（列表页用）
├── stage1/
│   ├── objects/
│   │   ├── 00_person/
│   │   │   ├── mask.png               # 二值掩码（可被 GUI 笔刷改写）
│   │   │   ├── crop.png               # 裁剪图
│   │   │   └── meta.json              # {category,label,confidence,bbox,depth_range}
│   │   └── 01_cypress/ ...
│   ├── background.png / background_mask.png
│   ├── depth.png                      # 16-bit 单目深度
│   └── stage1.json                    # Stage1Output 序列化（含 detector 版本）
├── stage2/
│   ├── gs/
│   │   ├── 00_person.ply              # TripoSplat 3DGS（重跑会带 .v2 后缀翻版）
│   │   ├── 00_person.meta.json        # {num_gaussians,bbox_3d,center_3d,source,gen_params}
│   │   └── background.ply             # 背景 2DGS surfel
│   └── stage2.json                    # Stage2Output（GSModelRegistry）
├── stage3/
│   ├── scene.json                     # ★ 场景图（GUI 组装的核心可写文件，见 3.4）
│   ├── lineart/                       # 用户线稿（按关键帧命名）
│   ├── keyframes/                     # 快照渲染 RGB/depth/edge 三联图
│   └── inpainted_background.png
├── stage5/
│   └── runs/2026-11-04T14-30/         # 每次合成一个 run 目录
│       ├── params.json  prompt.txt  output.mp4
└── exports/                           # 用户显式导出（不参与断点）
```

### 3.3 `project.json` 清单（pydantic 草案）

```python
class ProjectMeta(BaseModel):
    schema_version: int = 1
    project_id: str                      # uuid4
    name: str                            # "starry-night"
    created_at: datetime
    painting: PaintingSource             # path, width, height, md5
    pipeline_state: dict[str, StageState]
    #  "segment":  {status: "done",   updated: ..., artifact: "stage1/stage1.json"}
    #  "gs":       {status: "partial", updated: ..., artifact: "stage2/stage2.json"}
    #  "scene":    {status: "draft",   ...}
    #  "compose":  {status: "todo",    ...}

class UndoEntry(BaseModel):
    op: str                              # "mask.paint" | "scene.move" | "object.add" ...
    target: str                          # "stage1/objects/00_person/mask.png" | "scene.json#/objects/0"
    before: dict | None                  # JSON 状态或（位图类）撤销快照路径
    after: dict | None
    ts: datetime
```

- **撤销**：JSON 类操作记 before/after 快照（≤50 步栈）；位图 mask 类操作另存 `mask.undo.N.png` 差分快照，同栈管理。
- **翻版不覆盖**：重跑 TripoSplat、重做分割均产生新版本文件，`scene.json` 与 stage 输出引用具体版本，保证历史可回退（配合现有 `pipeline/checkpoint.py` 的断点续跑）。

### 3.4 `scene.json` 场景图（组装编辑器的核心数据）

```python
class SceneNode(BaseModel):
    node_id: str                         # "obj-00-person"
    kind: Literal["gs_object", "gs_background", "group"]
    source_ply: str                      # 相对项目路径 "stage2/gs/00_person.ply"
    parent: str | None                   # 组层级（背景为根同级）
    transform: Transform                 # translation[3] / rotation_quat[4] / scale[3]
    visible: bool = True
    locked: bool = False
    keyframes: dict[str, Transform] = {} # "kf-0","kf-1" → 各关键帧位姿（插值用）

class SceneGraph(BaseModel):
    schema_version: int = 1
    camera: CameraRig                    # 位置/朝向/fov（与原画视角锁定见 §4.4）
    ground: Literal["auto", "grid", "none"]
    nodes: list[SceneNode]
    edited_scene_ply_path: str | None    # "stage3/scene_edited.ply"（导出合并结果）
```

**写入协议**：前端视口每次拖拽结束 → `PATCH /api/projects/{id}/scene`（带 undo 令牌）→ 后端原子写 `scene.json`（先写 tmp 再 rename）→ 广播 WebSocket `scene.changed`。合并导出时才调用 `stage2/assemble.py` 生成 `edited_scene_ply`，编辑期间不做全场景合并（避免每次拖拽都重写大 PLY）。

### 3.5 读写 API 总表

| 端点 | 方法 | 读写对象 |
|---|---|---|
| `/api/projects` | GET/POST | 项目列表 / 从图片新建（生成缩略图） |
| `/api/projects/{id}` | GET/PATCH | `project.json` |
| `/api/projects/{id}/painting` | GET | 原画 / 缩略图（Range 分块, 8K 大图） |
| `/api/projects/{id}/segment/run` | POST | 触发 stage1（参数: detector, conf 阈值, 深度后端）→ 任务 |
| `/api/projects/{id}/objects` | GET/POST/DELETE | 物体元数据（`meta.json`） |
| `/api/projects/{id}/objects/{oid}/mask` | GET/PUT | mask PNG 读写（PUT 携带笔刷笔划或整幅 PNG） |
| `/api/projects/{id}/gs/run` | POST | 为选中物体触发 TripoSplat（批量入队） |
| `/api/projects/{id}/gs/{oid}` | GET | PLY 文件流（`Content-Type: model/ply`） |
| `/api/projects/{id}/scene` | GET/PATCH | `scene.json`（PATCH 原子写 + undo 栈） |
| `/api/projects/{id}/scene/snapshot` | POST | 服务端渲染当前视口 → keyframe 三联图 |
| `/api/projects/{id}/keyframes` | GET/POST | 关键帧与线稿管理 |
| `/api/projects/{id}/compose/run` | POST | stage5 ComfyUI 工作流提交 |
| `/api/tasks/{task_id}` | GET / WS `/ws/tasks` | 任务进度、日志尾随、取消 |
| `/api/projects/{id}/undo` `…/redo` | POST | 撤销/重做 |

**大文件策略**：PLY 走 HTTP Range + 浏览器端 `GaussianSplats3D` 的流式加载；深度图 PNG 前端按需取（滑条对比时才拉 16-bit 全图）。

---

## 4. GUI 功能模块与交互设计

整体布局 = **顶部项目栏 + 左侧管线步骤栏 + 中央工作区 + 右侧属性/检查器面板**。步骤栏是状态机：上游未完成时下游步骤显示锁定态（仍可点击查看，但操作禁用并给出引导提示）。

### 4.1 项目主页（画作库）

- 卡片网格：缩略图 + 名称 + 管线五段进度点（●完成 ◐部分 ○未做）。
- 「导入画作」拖拽区：支持 PNG/JPG，>4K 图自动生成缩略图并提示显存预估。
- 卡片右键：打开 / 复制项目目录 / 导出（zip） / 删除（二次确认 + 回收站目录）。

### 4.2 语义分割编辑器（stage1 审校）

```
┌──────────┬──────────────────────────────────┬───────────────┐
│ 物体列表   │        画作视口 (Canvas 2D)        │   检查器        │
│ ☑ 村民#0  │   原画底图 + 半透明彩色 mask 叠加    │ 类别: person   │
│ ☑ 柏树#1  │   选中物体描边高亮 + bbox 角标       │ 置信度: 0.91   │
│ ☐ 误检#2  │   笔刷/橡皮模式: 修补 mask 边缘      │ 深度: [0.2,0.5]│
│ ＋添加物体 │   拖拽 bbox = 整体移动 mask          │ [重跑此物体3DGS] │
└──────────┴──────────────────────────────────┴───────────────┘
 底部: [原图 | 叠加 | 纯mask | 深度图] 四视图切换   置信度滑条(过滤弱检测)
```

- **mask 修正**：笔刷半径/硬度可调；每次抬笔 = 一次 undo 单元；「套索添加」可框选新物体区域 + 输入类别 → 调 `stage1/segment.py` 的 mock/K-Means 通道补分割。
- **误检处理**：不物理删除，`meta.json` 标记 `rejected: true`（下游 stage2 自动跳过），可随时恢复。
- **深度联动**：深度图视图下拖动物体深度范围滑条 → 写回 `meta.json` 的 `depth_range`（影响 3DGS 度量重缩放）。
- 「重新分割」按钮：换检测器（YOLO26-seg / v8-seg / mock）或调置信度整图重跑，旧结果翻版保留。

### 4.3 3D 生成管理页（stage2 TripoSplat 队列）

- **任务卡片流**：每个未生成/失败的物体一张卡片（缩略图 + 名称 + 高斯数）。
  - 状态机：`待生成 → 排队 → 生成中(进度%) → 预览 / 失败(重试) / 已过期(mask 已改)`。
  - **已过期态**是关键交互：mask 被编辑后对应 3DGS 卡片打黄色"源已变更"角标，提示重跑。
- **内嵌预览**：点卡片 → 右侧抽屉弹出 360° 可旋转 3DGS 预览（单物体 + 棋盘格地面），下方滑条调 TripoSplat 参数（引导强度、高斯预算）后「重跑」。
- **批量操作**：全选未生成 → 「批量生成」入 GPU 串行队列；队列页显示预计时间与取消按钮。
- 背景卡片单独一格：显示 RGB-D 反投影 2DGSsurf el 状态。

### 4.4 场景组装编辑器（核心工作区）

```
┌──────────┬──────────────────────────────────┬───────────────┐
│ 大纲树     │        Three.js 3D 视口            │  变换检查器      │
│ ▾ 场景     │   3DGS 物体 + 背景 surfel 同场景渲染  │ 位置 x y z     │
│   背景 2DGS│   选中物体 = 高亮轮廓 + 变换 gizmo    │ 旋转 x y z     │
│ ▾ 村民#0  │   快捷键: G移动 R旋转 S缩放 F聚焦     │ 缩放 x y z     │
│   柏树#1  │   视图: [透视 | 正交 | 原画对齐]      │  [关键帧+:当前位姿]│
│ ＋拖入物体 │   显示: ☑地面网格 ☑原画幽灵底图       │  IoU 对齐: 0.87 │
└──────────┴──────────────────────────────────┴───────────────┘
 底部: 关键帧时间轴   [KF0]───[KF1]───▶   ▶试播(插值预览)   [快照渲染]
```

- **原画对齐模式**（本软件特色）：视口把原画作为固定相机下的"幽灵底图"（半透明叠在 3D 场景投影上），用户摆位时所见即最终关键帧构图；相机被锁定为原画内参，防止摆好了却拍不到。
- **变换 gizmo**：Three.js `TransformControls`；拖拽结束才提交 `PATCH scene`（拖拽中仅本地预览，避免写盘风暴）。
- **大纲树**：拖拽重排层级（group）、可见性眼睛、锁定；「拖入物体」从 stage2 未入场的 3DGS 列表拖到视口即创建节点。
- **IoU 对齐反馈**：开启"线稿对齐"后，视口角落实时显示当前渲染边缘与目标线稿的 IoU（复用 `stage3/reposition.py` 的 `compute_edge_iou`），并提供「自动对齐」按钮调用 `optimize_repositioning` 作为初值，再手动微调。
- **试播**：关键帧间位姿插值（贝塞尔缓动）实时预览，确认后「快照渲染」产出 RGB/深度/边缘三联图写 `stage3/keyframes/`。

### 4.5 线稿与关键帧页

- 左：关键帧缩略图列（含来源标记：快照 / 手绘）；右：绘制画布。
- 画布底层 = 关键帧 RGB 快照，上层笔刷画线稿（压感模拟线宽）；色标区分"轮廓线"（指引对齐）与"运动线"（指引动画方向）。
- 「发送到合成」检查清单：每个动体物体是否有目标线稿、IoU 是否达标（阈值可调，默认 0.75）。

### 4.6 视频合成页（stage5）

- 表单：I2V 模型切换（Wan2.2 / LTX）、ControlNet 权重（depth 0.85 / canny 0.6 预设）、提示词、时长、画幅。
- 提交 → 任务卡片（ComfyUI 节点进度流 + 中间产物缩略图轮播）→ 完成内嵌播放器。
- 历史 run 列表（`stage5/runs/`），可对比两个 run 的并排播放。

### 4.7 全局交互约定

- **快捷键**：`1–5` 切步骤、`Ctrl+Z/Y` 撤销重做、空格播放预览、`Del` 删除选中（带确认）。
- **任务中心**：右下角常驻小浮窗，任何后台生成任务（分割/3DGS/快照/合成）统一收口，点击跳转对应页面。
- **失败自愈**：GPU OOM 任务自动降级（高斯预算减半重试一次，标注"降级"角标）；ComfyUI 断连提示重连并保留已排队任务。

---

## 5. 用户旅程（端到端）

```
导入《星月夜》 → ① 分割审校: 拒掉2个误检, 笔刷修补村民边缘, 微调柏树深度
  → ② 批量生成 3DGS: 7物体排队, 2个失败重跑, 1个降级
  → ③ 场景组装: 原画对齐模式下把柏树#1抬高, 村民#0 移到前景, 打组"村庄"
  → ④ 关键帧: KF0 快照 → 画村民行走线稿 → 自动对齐 IoU 0.88 → KF1 快照
  → ⑤ 合成: Wan2.2 + depth/canny 双控 → 预览 → 导出 mp4
全程 project.json/scene.json 落盘, 关掉浏览器重开无损; CLI 用户可直接读同目录。
```

---

## 6. 非功能设计

| 项 | 方案 |
|---|---|
| GPU 任务串行化 | 单 worker 队列（TripoSplat/ComfyUI 均占满 GPU），优先级：用户交互触发的 > 批量 |
| 大图性能 | 8K 原图仅按需分块加载；mask 叠加在 2K 缩放上编辑，提交时映射回原分辨率 |
| 断点续跑 | 复用 `pipeline/checkpoint.py`；GUI 重启后按 `pipeline_state` 恢复每步状态 |
| 原子写 | 所有 JSON 落盘走 tmp+rename；写失败保留旧版并回报 |
| 可迁移 | 项目目录自包含（相对路径），zip 即备份 |

## 7. 里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| M1 | 后端 project/segment/scene API + 项目主页 + 分割编辑器（含笔刷与 undo） | mock 检测器全流程可审校 |
| M2 | 3DGS 队列页 + Three.js 视口 + 场景组装（gizmo/大纲/原画对齐） | 手动摆位→快照三联图 |
| M3 | 线稿绘制 + IoU 自动对齐 + 关键帧时间轴 + 试播 | 两关键帧插值预览流畅 |
| M4 | stage5 合成页 + 任务中心 + 导出 | 真实 ComfyUI 出片 |

## 8. 与现有代码的对接点

| GUI 能力 | 复用模块 |
|---|---|
| 分割 / 深度 | `revive.stage1.segment.run_segmentation`, `depth.run_depth_estimation` |
| 3DGS 生成 | `revive.stage2.triposplat.generate_object_3dgs` |
| 背景 / 合并导出 | `revive.stage2.gs2d_init`, `assemble.assemble_scene` |
| IoU 对齐 | `revive.stage3.reposition.optimize_repositioning / compute_edge_iou` |
| 补洞 | `revive.stage3.inpaint` |
| 合成 | `revive.stage5.workflow` + `common.comfy.ComfyClient` |
| 数据模型 | `revive.schemas`（Stage*Output 直接作为 API payload 基型） |
| 断点 | `revive.pipeline.checkpoint` |

> 新增代码仅两层：`oilpainting_studio/gui/server/`（FastAPI app + 各 api router + 任务队列）与前端 `OilPaintingStudio/gui/`（Vue3），算法层零改动。
