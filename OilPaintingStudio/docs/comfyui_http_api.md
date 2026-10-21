# ComfyUI HTTP 接口设计文档

> 基于 ComfyUI 官方源码 `server.py`（master 分支）与官方文档
> [docs.comfy.org/development/comfyui-server/comms_routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
> 整理。涵盖本地自托管服务器的全部 HTTP 路由、请求/响应结构、WebSocket
> 协议，以及与本项目 `oilpaint.comfy.ComfyClient` 实现的对照。

---

## 1. 设计概览

### 1.1 架构定位

ComfyUI 是基于 [aiohttp](https://docs.aiohttp.org/) 的异步 HTTP 服务器（`PromptServer`），提供两类对外接口：

- **REST API**：工作流排队、历史查询、文件上传/下载、节点/模型发现、系统状态
- **WebSocket `/ws`**：执行进度、节点状态、错误的实时推送

Web 客户端与第三方程序（如本项目）均通过同一套 API 驱动 ComfyUI。**无内置鉴权**，默认监听 `127.0.0.1:8188`，适合本地调用；公网部署需自行加反向代理鉴权。

### 1.2 核心调用模型

ComfyUI 是**异步任务队列**模型，并非同步推理服务器。一次生成的完整时序：

```
客户端                          ComfyUI
  │  1. POST /upload/image  ─────►  存图到 input/
  │  ◄─── {name, subfolder, type} ─
  │  2. POST /prompt         ─────►  校验 + 入队
  │  ◄─── {prompt_id, number} ─────
  │  3. GET /history/{id}    ─────►  （轮询，未完成返回 {}）
  │  ◄─── {} ──────────────────────
  │  ...                            节点逐个执行
  │  GET /history/{id}      ─────►
  │  ◄─── {outputs, status} ──────  完成
  │  4. GET /view?filename= ─────►  下载产物
  │  ◄─── <binary> ───────────────
```

> **关键点**：`POST /prompt` 仅入队即返回，不等待执行完成。结果通过轮询 `/history` 或 WebSocket `/ws` 获取。

### 1.3 工作流（Prompt）数据格式

`POST /prompt` 的 `prompt` 字段是 **API 格式 JSON**（非 UI 格式），结构为：

```json
{
  "<node_id_string>": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 156680208700286,
      "steps": 20,
      "cfg": 8,
      "model": ["4", 0],          // [被引用节点id, 输出端口序号]
      "positive": ["6", 0],
      "negative": ["7", 0],
      "latent_image": ["5", 0]
    }
  },
  "4": { "class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"} },
  "9": { "class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]} }
}
```

- 顶层 key 是**节点 id 字符串**（UI 导出 API 格式时为数字字符串，自定义可用任意字符串）
- `class_type` 对应注册的节点类名
- `inputs` 中：标量直接写值；引用其他节点用 `["源节点id", 输出端口序号]`
- 从 ComfyUI 网页端「设置 → 开发模式 → 文件 → 导出（API）」获得

---

## 2. 路由总览

源码中所有路由通过 `@routes.get/@routes.post` 注册（`server.py`）。按功能分组：

| 分组 | 方法 | 路径 | 用途 |
|---|---|---|---|
| **任务队列** | POST | `/prompt` | 提交工作流入队 |
| | GET | `/prompt` | 获取队列状态（剩余任务数） |
| | GET | `/queue` | 获取运行中 + 待执行队列 |
| | POST | `/queue` | 清空/删除队列项 |
| | POST | `/interrupt` | 中断当前执行 |
| | POST | `/free` | 卸载模型/释放显存 |
| **历史** | GET | `/history` | 获取全部历史（支持分页） |
| | GET | `/history/{prompt_id}` | 获取指定任务历史 |
| | POST | `/history` | 清空/删除历史 |
| **文件** | POST | `/upload/image` | 上传图像到 input/output/temp |
| | POST | `/upload/mask` | 上传蒙版（含原图合成） |
| | GET | `/view` | 查看/下载图像或任意产物 |
| | GET | `/view_metadata/{folder}` | 获取 safetensors 模型元数据 |
| **节点/模型** | GET | `/object_info` | 全部节点类型详情 |
| | GET | `/object_info/{node_class}` | 单个节点类型详情 |
| | GET | `/models` | 可用模型分类列表 |
| | GET | `/models/{folder}` | 某分类下的模型列表 |
| | GET | `/embeddings` | 可用 embedding 名称 |
| | GET | `/extensions` | 注册了 WEB_DIRECTORY 的扩展 |
| **系统** | GET | `/system_stats` | 系统信息（OS/Python/PyTorch/GPU/VRAM） |
| | GET | `/features` | 服务器特性开关 |
| | GET | `/workflow_templates` | 自定义节点模板工作流 |
| **WebSocket** | WS | `/ws` | 实时执行进度推送 |
| **用户数据** | GET/POST/DELETE | `/userdata`, `/userdata/{file}`, `/userdata/{file}/move/{dest}` | 多用户模式下的用户文件 |
| **新版任务** | GET | `/api/jobs`, `/api/jobs/{job_id}` | 新版作业管理接口 |
| | POST | `/api/jobs/{job_id}/cancel`, `/api/jobs/cancel` | 取消作业 |

> 本项目本地调用主要用：`/system_stats`、`/object_info`、`/upload/image`、`/prompt`、`/history/{id}`、`/view`、`/interrupt`、`/free`。

---

## 3. 核心接口详解

### 3.1 POST `/prompt` — 提交工作流

**请求体**（JSON）：

```json
{
  "prompt": { /* API 格式工作流，见 1.3 */ },
  "client_id": "可选，客户端标识，会写入 extra_data",
  "prompt_id": "可选，UUID；省略则服务器生成",
  "number": "可选 float，排序权重",
  "front": "可选 bool，true 时插队",
  "extra_data": "可选 dict，附加数据",
  "partial_execution_targets": "可选，仅执行部分节点"
}
```

**成功响应**（200）：

```json
{
  "prompt_id": "d086402a-7454-43c5-a753-b338e4870be2",
  "number": 6,
  "node_errors": {}
}
```

**校验失败响应**（400）：

```json
{
  "error": {
    "type": "prompt_outputs_failed_validation",
    "message": "...",
    "details": "...",
    "extra_info": {}
  },
  "node_errors": {
    "7": { "errors": [ { "type": "return_type_mismatch", "message": "...", ... } ] }
  }
}
```

**无 prompt 字段**（400）：`{"error": {"type": "no_prompt", ...}, "node_errors": {}}`

**实现要点**（源码 `post_prompt`）：
- `prompt_id` 若提供必须为规范小写连字符 UUID，否则 400
- 工作流先经 `execution.validate_prompt` 校验（节点是否存在、连接是否合法、必填输入是否齐全）
- 校验通过后 `prompt_queue.put(...)` 入队，立即返回
- `client_id` 被写入 `extra_data`，WebSocket 推送时按此定向消息

### 3.2 GET `/prompt` — 队列状态

**响应**：

```json
{
  "exec_info": { "queue_remaining": 3 }
}
```

仅返回剩余任务数，不含详情。

### 3.3 GET `/history/{prompt_id}` — 任务历史（轮询核心）

**未完成**：返回 `{}`（空对象）

**已完成**：

```json
{
  "d086402a-7454-43c5-a753-b338e4870be2": {
    "prompt": [6, "d086402a-...", { /* 工作流快照 */ }],
    "outputs": {
      "9": {
        "images": [
          {
            "filename": "ComfyUI_00001.png",
            "subfolder": "",
            "type": "output"
          }
        ]
      }
    },
    "status": {
      "status_str": "success",
      "completed": true,
      "messages": []
    },
    "meta": { },
    "node_errors": {}
  }
}
```

**关键字段**：

| 字段 | 说明 |
|---|---|
| `outputs` | dict，key 为输出节点 id（如 `SaveImage` 的 id） |
| `outputs.<id>.images` | `SaveImage` 产物：`[{filename, subfolder, type}]` |
| `outputs.<id>.gifs` | 动图产物（部分视频节点） |
| `outputs.<id>.videos` | 视频产物（部分节点） |
| `status.status_str` | `"success"` / `"error"` |
| `status.completed` | bool，是否执行完毕 |
| `status.messages` | 错误时含 `[["execution_error", {message, node_type, ...}]]` |

> **轮询判定逻辑**：响应非空 → 检查 `status.completed`；若 `status_str == "error"` 则读 `messages` 取错误详情。

**`GET /history`**（全量）支持 query 参数：`max_items=<int>`、`offset=<int>`。

**`POST /history`**：`{"clear": true}` 清空全部，或 `{"delete": ["prompt_id1", ...]}` 删除指定项。

### 3.4 GET `/view` — 下载产物

**Query 参数**：

| 参数 | 说明 |
|---|---|
| `filename` | 必填，文件名（或 `blake3:...` 资源哈希） |
| `subfolder` | 可选，子目录 |
| `type` | 可选，`output`（默认）/ `input` / `temp` |
| `preview` | 可选，返回缩略图，格式如 `webp;90` / `jpeg;80` |
| `channel` | 可选，`rgba`（默认）/ `rgb` / `a`（仅 alpha） |

**响应**：二进制图像数据，`Content-Type` 由 mimetype 推断，`Content-Disposition: filename="..."`。

**实现要点**（源码 `view_image`）：
- 安全校验：禁止 `/` 开头或含 `..` 的路径
- `preview` 模式转 webp/jpeg 缩略
- `channel=rgb` 转 RGB PNG；`channel=a` 返回 alpha 通道
- 危险类型（HTML/SVG/JS）强制 `attachment` 下载，防存储型 XSS

### 3.5 POST `/upload/image` — 上传图像

**请求**：`multipart/form-data`

| 字段 | 说明 |
|---|---|
| `image` | 必填，文件流 |
| `subfolder` | 可选，子目录 |
| `type` | 可选，`input`（默认）/ `output` / `temp` |
| `overwrite` | 可选，`"true"`/`"1"` 覆盖同名；否则自动改名 `name (1).png` |

**响应**（200）：

```json
{
  "name": "reference.png",
  "subfolder": "input",
  "type": "input"
}
```

> 新版还可能含 `asset: {id, asset_hash, size, mime_type, ...}`（asset_manager 启用时）。

**实现要点**（源码 `image_upload`）：
- 路径穿越防护：`commonpath` 校验
- 哈希去重：同名同内容不重复写盘
- 返回的 `name` 即后续 `LoadImage` 节点 `image` 字段应填的值

### 3.6 POST `/upload/mask` — 上传蒙版

额外字段 `original_ref`（JSON 字符串）：`{"filename": ..., "subfolder": ..., "type": ...}` 指向原图。服务器将蒙版 alpha 合成到原图并保存，保留原图元数据。

### 3.7 GET `/object_info` — 节点详情

**响应**：`{ "<node_class>": {node_info}, ... }`

单节点（`/object_info/KSampler`）返回 `{ "KSampler": {...} }`。

**`node_info` 结构**（源码 `node_info()`）：

```json
{
  "input": {
    "required": { "seed": ["INT", {"default": 0, "min": 0, "max": 18446744073709551615}],
                  "steps": ["INT", {"default": 20, "min": 1, "max": 10000}], ... },
    "optional": { ... }
  },
  "input_order": { "required": ["seed","steps","cfg",...], "optional": [...] },
  "output": ["LATENT"],
  "output_name": ["LATENT"],
  "output_is_list": [false],
  "is_input_list": false,
  "name": "KSampler",
  "display_name": "KSampler",
  "description": "",
  "python_module": "nodes",
  "category": "sampling",
  "output_node": false,
  "has_intermediate_output": true
}
```

**用途**：
- 探测某节点是否已安装（如 `LTXVLoader`、`WanVideoLoader`）
- 查询某节点可用的模型名（如 `CheckpointLoaderSimple.input.required.ckpt_name[0]` 是文件名列表）
- 校验工作流参数范围

### 3.8 GET `/system_stats` — 系统状态

**响应**：

```json
{
  "system": {
    "os": "win32",
    "ram_total": 34359738368,
    "ram_free": 12345678,
    "comfyui_version": "0.3.x",
    "python_version": "3.11.x",
    "pytorch_version": "2.x.x",
    "embedded_python": false,
    "argv": [...]
  },
  "devices": [
    {
      "name": "NVIDIA GeForce RTX 4090",
      "type": "cuda",
      "index": 0,
      "vram_total": 25757208576,
      "vram_free": 20000000000,
      "torch_vram_total": 25757208576,
      "torch_vram_free": 20000000000
    }
  ]
}
```

**用途**：健康检查、显存探测。本项目 `health` 子命令用它判断 ComfyUI 是否在线。

### 3.9 GET `/models` 与 `/models/{folder}`

- `/models`：返回可用模型分类列表（如 `["checkpoints", "loras", "vae", "diffusion_models", ...]`）
- `/models/checkpoints`：返回该分类下文件名列表

### 3.10 队列控制

**GET `/queue`**：

```json
{
  "queue_running": [ /* 运行中任务（已脱敏） */ ],
  "queue_pending": [ /* 待执行任务 */ ]
}
```

**POST `/queue`**：

```json
{ "clear": true }              // 清空整个队列
{ "delete": ["prompt_id1"] }   // 删除指定项
```

**POST `/interrupt`**：

```json
{}                              // 全局中断当前执行
{ "prompt_id": "abc-123" }      // 仅当该 prompt 正运行时中断
```

**POST `/free`**：

```json
{ "unload_models": true, "free_memory": true }
```

---

## 4. WebSocket `/ws` — 实时进度

### 4.1 连接

```
ws://127.0.0.1:8188/ws?clientId=<client_id>
```

`clientId` 应与 `POST /prompt` 的 `client_id` 一致，服务器据此定向推送。

### 4.2 消息格式

所有消息为 JSON：`{"type": "<event>", "data": {...}}`，除二进制预览图（`send_bytes`）。

| type | 触发时机 | data 示例 |
|---|---|---|
| `status` | 队列变化 / 连接建立 | `{"status": {"exec_info": {"queue_remaining": 3}}, "sid": "..."}` |
| `execution_start` | prompt 开始执行 | `{"prompt_id": "..."}` |
| `execution_cached` | 命中缓存节点 | `{"nodes": ["4","6"], "prompt_id": "..."}` |
| `executing` | 节点开始执行 | `{"node": "7", "prompt_id": "..."}`；节点结束时 `{"node": null}` |
| `progress` | 长任务进度 | `{"value": 10, "max": 20, "prompt_id": "...", "node": "7"}` |
| `executed` | 节点完成产出 | `{"node": "9", "output": {"images": [{...}]}, "prompt_id": "..."}` |
| `execution_error` | 执行出错 | `{"node_type": "...", "exception_type": "...", "exception_message": "...", "node_id": "7"}` |

### 4.3 二进制预览

采样过程中可能推送二进制预览图（`PREVIEW_IMAGE` 事件），格式：4 字节类型头（`>I`：1=JPEG, 2=PNG）+ 图像字节。CLI/无头场景通常忽略。

### 4.4 客户端→服务器消息

首条消息可为 `{"type": "feature_flags", "data": {...}}` 协商特性；服务器回 `feature_flags`。其余方向消息较少。

> **本项目选择 REST 轮询而非 WebSocket**：CLI 环境下 WebSocket 维护成本高，`GET /history/{id}` 轮询已足够且实现简单。需要实时进度条时再切 WebSocket。

---

## 5. 典型调用时序（图生视频场景）

```
1. 健康检查
   GET /system_stats
   GET /object_info/LTXVLoader          # 确认节点 + 模型可用

2. 上传参考帧
   POST /upload/image  (multipart)
   → {name: "kf_001.png", subfolder: "", type: "input"}

3. 构造工作流（API 格式），LoadImage.image = "kf_001.png"
   POST /prompt  {prompt: workflow, client_id: "oilpaint-xxx"}
   → {prompt_id: "abc-123", number: 1}

4. 轮询（每 2-5 秒）
   GET /history/abc-123
   → {}                                     # 仍在执行
   → {abc-123: {outputs: {save: {images/gifs/videos: [...]}}, status: {completed: true}}}

5. 下载产物
   GET /view?filename=clip_001.mp4&type=output
   → <binary>

6. （可选）释放显存
   POST /free  {unload_models: true}
```

---

## 6. 与本项目 `ComfyClient` 实现对照

| 接口 | 本项目方法 | 一致性 | 备注 |
|---|---|---|---|
| `GET /system_stats` | `health()` | ✅ | 探测在线 + 返回 ok |
| `GET /object_info[/{node}]` | `object_info()` | ✅ | 用于模型/节点可用性探测 |
| `POST /upload/image` | `upload_image()` | ✅ | multipart 上传，返回 `name` |
| `POST /prompt` | `queue_prompt()` | ✅ | 提交 `{prompt, client_id}`，取 `prompt_id` |
| `GET /history/{id}` | `get_history()` | ✅ | 轮询至非空 |
| `GET /view` | `download_view()` | ✅ | 按 filename/subfolder/type 拉取 |
| `POST /interrupt` | — | ⚠️ 未实现 | 建议补充，超时或取消时调用 |
| `POST /free` | — | ⚠️ 未实现 | 建议在批次结束后调用释放显存 |
| `GET /queue` | — | — | 非必需，并发限流已由本地信号量控制 |
| WebSocket `/ws` | — | — | 刻意未用，采用 REST 轮询（见 4.4） |

### 6.1 已正确的实现点

- **client_id**：`ComfyClient.__init__` 生成随机 UUID 作为 client_id，与 `POST /prompt` 的 `client_id` 字段一致 ✅
- **轮询判定**：`get_history` 返回 `None`（未完成）或历史 dict（完成），`run()` 据此循环 ✅
- **产物收集**：`_collect_outputs` 兼容 `images`/`gifs`/`videos` 三种输出键，适配 `SaveImage` 与 `VHS_VideoCombine` ✅
- **错误检测**：检查 `status.status_str == "error"` 抛 `RuntimeError` ✅
- **并发限流**：`asyncio.Semaphore(concurrency)` 控制并行排队数 ✅
- **超时**：单任务 `PER_JOB_TIMEOUT`，视频生成给 1800s ✅

### 6.2 建议增强项

1. **`interrupt()` 方法**：超时或用户取消时调 `POST /interrupt`，避免僵尸任务占用 GPU
2. **`free_memory()` 方法**：批次结束后 `POST /free {unload_models: true}`，降低显存占用
3. **校验失败详情**：`queue_prompt` 当前仅检查响应含 `error`，可解析 `node_errors` 给出缺模型/缺节点的可读提示
4. **`/object_info` 预检**：`health` 子命令已探测节点，可在 `render` 前自动校验工作流用到的 `class_type` 全部存在
5. **WebSocket 进度**：需要实时进度条时，连 `/ws?clientId=<同 prompt 的 client_id>` 监听 `progress`/`executing` 事件

---

## 7. 错误处理参考

| HTTP 状态 / 现象 | 原因 | 处理 |
|---|---|---|
| Connection refused | ComfyUI 未运行 | 提示启动；离线模式保存工作流 JSON |
| 400 + `node_errors` | 工作流节点/模型缺失 | 解析 `node_errors`，提示安装节点或下载模型 |
| 400 + `no_prompt` | 请求体缺 `prompt` 字段 | 检查工作流构造 |
| 400 + `invalid_prompt_id` | `prompt_id` 非 UUID | 省略让服务器生成 |
| `/history/{id}` 持续返回 `{}` | 仍在执行或 id 错误 | 继续轮询；超时后 `interrupt` |
| `status_str == "error"` | 执行期异常 | 读 `messages` 取 `execution_error` 详情 |
| 500 / 超时 | 服务器过载/崩溃 | 重试；必要时重启 ComfyUI |
| `/view` 404 | 文件被清理或路径错误 | 检查 filename/subfolder/type |

---

## 8. 参考

- 官方路由文档：https://docs.comfy.org/development/comfyui-server/comms_routes
- 官方源码 `server.py`：https://github.com/comfyanonymous/ComfyUI/blob/master/server.py
- 官方 OpenAPI 规范：https://github.com/comfyanonymous/ComfyUI/blob/master/openapi.yaml
- 本项目客户端：`src/oilpaint/comfy/client.py`
- 本项目工作流模板：`src/oilpaint/comfy/templates/*.json`
