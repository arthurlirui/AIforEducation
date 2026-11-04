# PaintingStudio Desktop — 论文 Demo 实例设计文档

> 桌面端论文 demo：把 Canvas3D 管线浓缩为「一键三步」演示（语义分割 → 深度估计 → 3D 化身），
> 支持 **GPU / CPU / MOCK 三档推理**，依赖缺失或设备不可用时**自动回退**到下一档。
>
> 版本 v1.0 · 2026-11-04 · **已实现**（`oilpainting_studio/desktop/` + `gui/` 第 6 步页面，14 项新测试，全仓 85 测全绿）

---

## 1. 目标与定位

### 1.1 为什么需要桌面 demo

| 场景 | 现有 GUI 工作站的不足 | 桌面 demo 的解决方式 |
|---|---|---|
| 论文答辩 / 展会现场 | 需要启动服务+浏览器，操作路径长 | 双击式桌面窗口（pywebview），一键运行 |
| 审稿人复现 | 环境差异（无 GPU / 无 torch）导致跑不起来 | 三档自动回退，任何机器都有可视化结果 |
| 性能声明 | 没有量化的设备-耗时对照 | 每步计时 + 设备档位标注，历史运行可对比 |

### 1.2 演示叙事（论文 demo 场景）

固定示例画作 →「▶ 运行 Demo」→ 三步时间线依次点亮：

```
STEP 1 · PaintParse 分割    N 个物体 (yolo:cuda:0)        1200 ms   [overlay.png]
STEP 2 · MonoDepth 深度     深度范围 [1.2, 12.0] (mock:gradient)   15 ms   [depth_vis.png]
STEP 3 · MonoSplat 3D 化身  点云 PLY (38,400 点, RGB-D 反投影)      80 ms   [scene.ply]
```

每步产物可下载（论文截图直接取用），总耗时与档位展示在运行条上。

## 2. 架构

```
┌────────────────────────────────────────────────────┐
│            pywebview 桌面窗口 (1440×900)             │
│   复用 gui/dist (Vue3 + Three.js) 第 6 步 Demo 页    │
└───────────────────┬────────────────────────────────┘
                    │ HTTP 127.0.0.1:8712 (仅本机)
┌───────────────────▼────────────────────────────────┐
│        desktop/__main__.py  (uvicorn 内置服务)       │
│  desktop/api.py   /api/demo/*  (7 端点)             │
│  desktop/engine.py  DemoEngine: 三步流程 + 计时      │
│  desktop/device.py  设备探测 + 三档回退策略           │
└───────────────────┬────────────────────────────────┘
                    │ 复用 (不改)
┌───────────────────▼────────────────────────────────┐
│  revive/stage1/segment.py segment_mock (K-Means)    │
│  revive/stage1/depth.py   estimate_depth_mock       │
│  ultralytics YOLO-seg (GPU/CPU 真模型注入点)         │
│  gui/imgio.py (中文路径兼容)                          │
└─────────────────────────────────────────────────────┘
```

双形态交付：`py -m oilpainting_studio.desktop` 开窗口；`PYSTUDIO_DEMO=web` 同一服务供浏览器访问（CI/远程演示）。

## 3. 三档设备策略（核心）

### 3.1 档位定义与回退链

```
GPU  ──(无 CUDA / CUDA 初始化失败)──▶  CPU  ──(torch/ultralytics 缺失)──▶  MOCK
```

| 档位 | 分割后端 | 深度后端 | 典型耗时 |
|---|---|---|---|
| GPU | YOLO-seg on cuda:0 | DA-V2（权重就位时）/ mock | ~1 s |
| CPU | YOLO-seg on cpu | 同上 | ~10 s |
| MOCK | K-Means 聚类 + 连通域 | 纵向梯度 + 亮度调制 | <100 ms |

规则：
1. `auto`（默认）：探测到什么用什么，报告实际档位。
2. 用户可强制 `gpu` / `cpu` / `mock`；**强制档不可用时自动落到实际可用档**，并把回退原因（如"请求 GPU 不可用 → 自动回退 MOCK"）如实显示在 UI 上。
3. 真模型加载失败（权重缺失、CUDA OOM）在**运行时**再次降级到 mock，backend 矩阵实时反映。
4. 混合模式是合法状态：分割走 YOLO:cuda 而 DA-V2 权重缺失时深度走 mock，UI 分别标注。

### 3.2 数据模型（`device.py`）

```python
DeviceReport:                       # GET /api/demo/device 的载荷
  tier: "gpu" | "cpu" | "mock"     # 实际生效档
  torch_version / cuda_available / cuda_device_name / vram_gb
  backends: {segment: BackendStatus, depth: BackendStatus}
BackendStatus: kind / available / device / detail / load_ms / infer_ms

DeviceChoice: requested → effective + reason   # 回退决策记录
```

## 4. API（`/api/demo/*`，7 端点）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/demo/health` | GET | 存活检查 |
| `/api/demo/device?prefer=` | GET | 设备探测 + 回退解析（不初始化引擎） |
| `/api/demo/paintings` | GET/POST | 示例画作注册（上传→缩略图→meta.json） |
| `/api/demo/run` | POST | `{painting, prefer}` → 三步 demo（同步，秒级） |
| `/api/demo/runs` | GET | 历史运行（含各档耗时，性能对照数据源） |
| `/api/demo/artifact/{run_id}/{file}` | GET | 产物文件（overlay/depth_vis/scene.ply） |

demo 单次运行秒级完成，故用同步端点而非 GUI 工作站的异步任务队列——demo 界面即点即得。

## 5. Demo UI（`gui/src/components/DemoView.vue`，第 6 步页签）

- **设备面板**：当前档位徽章（GPU 绿 / CPU 黄 / MOCK 红）+ CUDA 设备名/显存 + 回退原因。
- **后端矩阵**：分割/深度两卡片，标注 `yolo:gpu` / `mock:kmeans` 等实际后端与上次推理毫秒数。
- **档位选择器**：自动 / 强制 GPU / 强制 CPU / 强制 MOCK（论文实验中切换对比用）。
- **三步时间线**：每步卡片 = 步骤名 + 耗时 + 摘要 + 产物缩略图。
- **下载条**：overlay.png / depth_vis.png / scene.ply 一键下载（论文插图直接可用）。
- **运行历史**：run_id / 档位 / 总耗时 / 画作，多档位对比一目了然。

## 6. 与 GUI 工作站的关系

| | GUI 工作站（第 1–5 步） | 桌面 demo（第 6 步） |
|---|---|---|
| 受众 | 日常创作用户 | 论文评审/答辩观众 |
| 路径 | 完整五阶段可交互编辑 | 一键三步自动演出 |
| 服务 | :8710 独立进程 | :8712 pywebview 内置 |
| 任务 | GPU 异步队列 + 进度轮询 | 同步秒级返回 |
| 数据 | projects/<名>/ 完整目录 | projects/_demo/ 轻量产物 |

两者共享前端 dist、imgio 兼容层与 revive 算法；demo 页签在工作站里也可直接使用（同源 `/api/demo/*` 需工作站也挂载 demo router，桌面模式下原生具备）。

## 7. 测试（`tests/test_desktop_demo.py`，14 项）

- **设备策略** 4 项：auto 探测（有 CUDA 机器断言 GPU）、强制 mock、报告可序列化、回退原因文案
- **引擎** 6 项：mock/cpu/auto 三档参数化全流程、run 字典契约、缺文件报错
- **API** 4 项：health/device、画作上传（重名 409）+ mock 运行 + 产物下载 + 历史、auto 档端到端、错误码（404/非法路径）

全仓回归：**85 项测试全部通过**（GUI 13 + revive 20 + video 38 + desktop 14）。

## 8. 使用

```bash
# 桌面窗口 (Windows/macOS/Linux, pywebview)
py -m oilpainting_studio.desktop

# 浏览器模式 (无窗口环境)
PYSTUDIO_DEMO=web py -m oilpainting_studio.desktop   # → http://127.0.0.1:8712

# 注册示例画作 (一次)
curl -F "name=村庄" -F "painting=@village.png" \
     http://127.0.0.1:8712/api/demo/paintings
```

论文实验建议：对同一画作分别以 `gpu` / `cpu` / `mock` 各跑一次，运行历史的耗时对照即设备可扩展性（scalability）证据。
