# TechLearnStudio 模块设计文档

> 状态：设计稿 v0.1 · 2026-10-21
> 作者：AIforEducation 工作组
> 定位：面向人类快速学习新技术/专业课的「超帧」(hyperframes) 演示式学习平台

---

## 0. 一句话定位

**TechLearnStudio** 读取任意技术的官方文档/源码/讲义，自动生成**帧驱动的可交互网页 PPT 与动画**，把"技术原理 + 设计思路"拆解成人类 15 分钟即可消化的学习路径。前后端分离，内容可自动更新，覆盖 Python / Rust / Go / TypeScript 等编程语言，以及信号与系统、无线通信、大模型等专业课程。

## 1. 为什么需要它

| 痛点 | 现状 | TechLearnStudio 的回答 |
|------|------|------------------------|
| 官方文档太长，新人找不到主线 | 读 5 小时仍不知道"为什么这么设计" | LLM 抽取「设计动机→核心抽象→最小可运行示例」三段式叙事 |
| 视频教程信息密度低 | 30 分钟视频里 5 分钟干货 | 静态网页 PPT + 局部动画，用户自定节奏，可跳可回 |
| 动画演示工具（Manim / Motion Canvas）门槛高 | 需要手写 Python/TS 代码 | hyperframes DSL：声明式描述一帧，引擎自动渲染过渡 |
| 技术迭代快，内容易过期 | 一本书出版即过时 | 文档巡检 cron + diff 触发增量重生成，旧帧保留版本号 |

## 2. 核心概念：Hyperframes（超帧）

### 2.1 定义

一个 **hyperframe**（超帧，简称 frame）是学习内容的最小可呈现单元，等价于"一页可交互的网页"。它不是静态 PPT 页，而是一个自带状态机的微型 Web 应用：

```
Frame = {
  id, title, layout,           # 结构
  blocks: [...],               # 文本/代码/公式/图/可运行示例，每个可带 fragment 顺序号
  notes: speaker_notes,        # 演讲者备注（reveal.js speaker notes）
}
```

渲染由 reveal.js 负责：一帧 = 一个 `<section>`，block 的 `fragment` 决定分步进场顺序，动画用网页标准（CSS / Web Animations / D3 / GSAP）直接嵌入，不自写时间线引擎。

一节课件 = 一个 frame 序列，用户可以：

- **线性播放**：按空格逐帧、逐 fragment 前进（reveal.js 原生）。
- **随机跳转**：左侧大纲点击任意帧直接跳；reveal.js 支持深链 `#/frame-id`。
- **交互暂停**：在可运行示例帧改代码、点运行，输出在帧内展开。

### 2.2 为什么叫 "hyper"

- **超链接**：任意帧内任意元素可链接到另一帧（跨章节跳转），形成知识图谱而非线性幻灯。
- **超媒体**：帧内可嵌文本、代码、公式（KaTeX）、矢量图（SVG）、Canvas 动画、可运行 sandbox。
- **超时间线**：同一帧可有多条并行时间线（讲解轨、动画轨、代码执行轨），互不阻塞。

### 2.3 与现有工具的区别

| 工具 | 形态 | 动画 | 交互 | 自动生成 | 多语言内容 |
|------|------|------|------|----------|------------|
| Reveal.js | 静态幻灯 | CSS 过渡 + fragments | 弱 | 否 | 手写 |
| Motion Canvas | 代码驱动的动画视频 | 强（编程式） | 无 | 否 | 手写 TS |
| Manim | Python 数学动画 | 强 | 无 | 否 | 手写 Python |
| Slidev | 开发者向幻灯 | 中 | 中 | 否 | 手写 MD |
| **TechLearnStudio** | **基于 reveal.js 的可交互课件** | **强（fragments + 任意 HTML/Web Animations/GSAP）** | **强（sandbox + 控件）** | **是（文档→课件管线）** | **是（插件化内容源）** |

## 3. 总体架构

平台由 **三个独立模块** 组成，关注点严格分离：**Studio 生产内容，Backend 存储托管，Frontend 播放交互**。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TechLearnStudio 平台                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────────────── Studio（生产者）─────────────────────┐   │
│   │  LLM 抓取新技术内容 → 搜索教学 topic → 设计动画视频内容     │   │
│   │                                                             │   │
│   │  ContentCrawler ──▶ TopicDiscover ──▶ Composer ──▶ AnimGen  │   │
│   │  (抓文档/讲义)      (LLM 找新 topic)   (frames.json)  (MC)  │   │
│   │                                         │                   │   │
│   │   Scheduler (cron 定期跑) ◀─────────────┘                   │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │ POST /api/admin/* (推送成果)       │
│                                ▼                                    │
│   ┌─────────────────────── Backend（仓库）──────────────────────┐   │
│   │  增删改查动画数据 + 托管生成的网页 + 定期自动上新           │   │
│   │                                                             │   │
│   │  Course/Frame CRUD ── Frame Store (SQLite)                  │   │
│   │  静态网页托管 (reveal.js + MC 视频) ── /static              │   │
│   │  Sandbox (Pyodide/Docker) ── /api/sandbox/run               │   │
│   │  Auto-Publish (定时把 Studio 推送的新内容发布上线)          │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │ HTTP /api/* + /static               │
│                                ▼                                    │
│   ┌─────────────────────── Frontend（消费者）──────────────────┐    │
│   │  显示动画的技术视频 HTML 网页 + 交互                        │    │
│   │                                                             │    │
│   │  reveal.js (课件结构/分步) + Motion Canvas (原理动画)       │    │
│   │  课程库 / 大纲 / 播放控制 / sandbox 交互 / 搜索             │    │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

三模块职责一句话：

| 模块 | 角色 | 核心动作 | 部署 |
|------|------|----------|------|
| **Studio** | 生产者 | 大模型抓新技术 → 搜教学 topic → 设计 frames.json + MC 动画 → 推送给 Backend | 可独立进程/容器，cron 或手动触发 |
| **Backend** | 仓库 | 课程/帧 CRUD、托管静态网页、sandbox、定时自动上新 | 长驻 FastAPI 服务 |
| **Frontend** | 消费者 | 渲染动画课件 HTML、交互、搜索 | 静态站点 + Vue 壳 |

三者通过 HTTP API 解耦：Studio 是 Backend 的一个"特权客户端"，Frontend 是普通客户端。Studio 可离线跑、可多实例并行生产不同 topic；Backend 是唯一数据源；Frontend 无状态。

两条渲染通道（与前文一致）：
- **reveal.js** —— 课件结构、文字/公式/代码/分步呈现（"读"的层面）。
- **Motion Canvas** —— 帧内复杂原理动画（卷积滑窗、OFDM 子载波、注意力矩阵、所有权指针迁移等"看"的层面），帧精确时间线编排，产出可嵌入网页的实时 Canvas 渲染或预渲染视频。

三模块内部组成：

- **Studio（生产者）** — ContentCrawler 抓文档/讲义；TopicDiscover 用 LLM 搜新教学 topic；Composer 合成 `frames.json`；AnimGen 生成 Motion Canvas 动画场景并渲染；Scheduler 定期跑或手动触发；通过 Backend 的 admin API 推送成果。
- **Backend（仓库）** — Course/Frame 增删改查；Frame Store（SQLite）；静态网页托管（reveal.js 课件 + MC 视频）；Sandbox（Pyodide/Docker）；Auto-Publish 定时把 Studio 推送的新内容发布上线。
- **Frontend（消费者）** — reveal.js 渲染课件结构与分步；Motion Canvas Player 渲染原理动画；课程库/大纲/播放控制/sandbox 交互/搜索。

## 4. 顶层目录结构

```
TechLearnStudio/
├── studio/                          # 生产者（见 §4a）
│   ├── crawler/                     #   抓文档/讲义
│   ├── topics/                      #   LLM 搜新教学 topic
│   ├── composer/                    #   合成 frames.json
│   ├── anim_gen/                    #   Motion Canvas 场景生成 + 模板库
│   ├── anim_render/                 #   MC 渲染服务（CLI 调用 + 缓存）
│   ├── scheduler/                   #   cron 定期跑 + diff 增量
│   ├── llm/                         #   LLM 适配（多 provider）
│   ├── publish/                     #   推送成果到 Backend admin API
│   ├── tests/
│   └── pyproject.toml
├── backend/                         # 仓库（见 §4b）
│   ├── app/
│   │   ├── main.py                  #   FastAPI 入口
│   │   ├── config.py
│   │   ├── db.py                    #   SQLite + SQLModel
│   │   ├── models.py                #   Course/Frame/VersionDelta/Source
│   │   ├── routers/
│   │   │   ├── courses.py           #   课件 CRUD + 列表（前端读）
│   │   │   ├── frames.py            #   单帧读取
│   │   │   ├── admin.py             #   Studio 推送/上下架（写权限）
│   │   │   ├── sandbox.py           #   在线运行代码
│   │   │   ├── search.py            #   全文搜索
│   │   │   ├── sources.py           #   内容源元信息
│   │   │   └── health.py
│   │   ├── static/                  #   托管生成的课件网页 + MC 视频
│   │   ├── sandbox/                 #   代码沙箱（Pyodide/Docker）
│   │   └── auto_publish.py          #   定时把 Studio 推送的新内容发布上线
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/                        # 消费者（见 §5）
│   └── src/{plugin,motion-canvas,components,stores,views}
├── docs/modules/techlearnstudio.md  # 本文件
└── README.md
```

三模块通过 HTTP 解耦，可独立部署：Studio 可离线/多实例并行生产不同 topic；Backend 长驻服务是唯一数据源；Frontend 是无状态静态站点。

## 4a. Studio 模块（生产者）

职责：**调用大模型抓取新科技内容 → 搜索新教学 topic → 设计 frames.json + Motion Canvas 动画 → 推送给 Backend**。

### 4a.1 内部流水线

```
[Scheduler: cron 或手动触发]
   │
   ▼
[1. Crawler]    按内容源 adapter 抓文档/讲义/论文  ──▶ raw_docs
   │             (python_docs / rust_docs / go_docs / ts_docs /
   │              course_signal / course_wireless / course_llm)
   ▼
[2. TopicDiscover] LLM 扫 raw_docs + 趋势源，产出候选教学 topic：
   │              - 新技术（如 "Python 3.13 free-threading"）
   │              - 旧技术新角度（如 "从零推导 OFDM"）
   │              - 与已有课件去重，按"学习者价值"排序
   ▼
[3. Composer]   对选中 topic 合成 frames.json（见 §4a.3）
   │              - Outline：动机→概念→示例→陷阱→进阶
   │              - Frame Build：选 layout、抽代码、生成公式/SVG
   │              - Fragment Plan：标 reveal.js 分步顺序
   ▼
[4. AnimGen]    需要原理动画的帧 → 生成 Motion Canvas scene（见 §4a.4）
   │              - 从 anim_lib/ 匹配模板 + LLM 填参
   │              - anim_render/ 调 MC CLI 预渲染 mp4（SHA-256 缓存）
   ▼
[5. QA]         规则校验：
   │              - 代码在 sandbox 跑通
   │              - MC scene 试渲染通过
   │              - 每帧阅读时长 30s–90s
   ▼
[6. Publish]    通过 Backend admin API 推送：POST /api/admin/courses + frames + mp4
                Backend 校验入库 → Auto-Publish 定时发布上线
```

### 4a.2 ContentCrawler（内容源 adapter）

```python
class ContentSource(ABC):
    kind: str
    @abstractmethod
    async def fetch(self) -> list[RawDoc]: ...
    @abstractmethod
    def fingerprint(self, docs: list[RawDoc]) -> str: ...
    @abstractmethod
    def parse(self, docs: list[RawDoc]) -> list[Section]: ...
```

内置 adapter：

| adapter | 来源 | 取法 |
|---------|------|------|
| `python_docs` | docs.python.org | 抓 sitemap → 按 page 拉 HTML |
| `rust_docs` | doc.rust-lang.org | 同上 + The Book 目录 |
| `go_docs` | go.dev/doc | 同上 |
| `ts_docs` | typescriptlang.org/docs | 同上 |
| `course_signal` | 教师提供的 PDF/讲义 | 本地上传 + PDF 抽文本 |
| `course_wireless` | 同上 | 同上 |
| `course_llm` | 论文/讲义 + 模型卡 | 混合：PDF + HuggingFace 模型页 |

新增技术只需写一个 ~80 行的 adapter。

### 4a.3 Composer 合成管线

输入：一个 `ContentSource` 产出的原始文档集 + 一个 topic。输出：一节 `frames.json`。

```
raw_docs + topic
   │
   ▼
[1. Ingest]      清洗→分节→建立 TOC
   ▼
[2. Outline]     LLM 抽取「学习路径」：动机→概念→示例→陷阱→进阶
   │              产出 outline.json（每章 = N 帧）
   ▼
[3. Frame Build] 逐帧构造：
   │              - 选 layout（标题帧/对比帧/代码帧/图解帧/测验帧）
   │              - 抽取/改写代码为可运行最小示例
   │              - 生成 KaTeX 公式块
   │              - 生成 SVG/Canvas 动画描述
   ▼
[4. Fragment Plan] 编排分步呈现：
   │              - 给每个 block 标 fragment 顺序（先问题→后方案→再代码）
   │              - SVG/Canvas 动画用标准 CSS/Web Animations 描述
   ▼
[5. QA]          规则校验：
   │              - 代码必须能在 sandbox 跑通
   │              - 公式必须有解释块
   │              - 每帧阅读时长 30s–90s
   ▼
frames.json → Publish
```

LLM 仅在 2/3/4 步介入，每步有结构化输出 schema（Pydantic 校验），失败降级规则模板，保证离线可跑。

### 4a.4 AnimGen — Motion Canvas 动画生成与渲染

reveal.js fragments 适合"顺序开关"式分步呈现，但**帧精确的原理动画**（卷积核滑窗逐采样相乘、OFDM 子载波正交叠加、注意力矩阵权重流动、Rust 所有权指针迁移）需要可编程时间线。由 Motion Canvas 承担。

**分工**：

| 内容类型 | 渲染方 | 理由 |
|----------|--------|------|
| 文字/列表/标题分步 | reveal.js fragments | 顺序开关即可 |
| 代码 + 行高亮 + 运行 | reveal.js + sandbox | 交互需 DOM |
| 公式步进推导 | reveal.js + KaTeX fragment | 每步一个 fragment |
| **原理动画（时间线驱动）** | **Motion Canvas** | 帧精确、可编程、可预渲染视频 |
| SVG 静态图 + 简单 CSS 动画 | reveal.js 内联 | 轻量，不必动用 MC |

判断规则：`block` 里出现 `motionCanvas` 字段即走 MC 通道；只有 `svgAnim`/`canvas` 走 reveal 内联通道。

**工作流**：

```
帧需要原理动画
   │
   ▼
[1. 选模板]   从 anim_lib/ 选可复用场景模板（参数化 MC scene TS 代码）
   ▼
[2. 填参数]   LLM 从文档抽取关键数值/结构，填入模板参数
   ▼
[3. 生成]    产出 scene.ts + project.ts（标准 MC 项目文件）
   ▼
[4. 渲染]    anim_render/ 调 MC CLI：
              - video 模式（默认）：mc render → mp4，按 scene 代码 SHA-256 缓存
              - live 模式（按需）：启 mc player，前端 WebSocket 接收帧
   ▼
block.motionCanvas = { sceneRef, params, renderMode, fallbackSvg }
```

**可复用动画模板库（anim_lib/）**：

| 模板 | 用途 | 关键参数 |
|------|------|----------|
| `convolution` | 信号卷积：核滑过信号、逐点相乘累加 | `signal`, `kernel`, `mode` |
| `ofdm_subcarriers` | OFDM：多正交子载波叠加成符号 | `n_subcarriers`, `symbols`, `show_fft` |
| `attention_flow` | 注意力：Q×K 权重流动 + softmax 热力图 | `seq_len`, `heads`, `weights` |
| `ownership_move` | Rust 所有权：指针迁移、原变量变灰 | `vars`, `move_from`, `move_to` |
| `channel_response` | 无线信道：多径 + 衰落 + 频率响应 | `paths`, `delays`, `gains` |
| `gradient_descent` | 梯度下降：损失曲面 + 步进轨迹 | `surface_fn`, `start`, `lr`, `steps` |
| `tree_traversal` | 数据结构：树/图遍历高亮 | `tree`, `order` |

模板设计原则：参数化确定性（同参数同输出便于缓存）、纯函数式 scene（不发网络不读文件）、固定时长（声明 `durationFrames`）。

**渲染服务（anim_render/renderer.py）**：

```python
async def render_scene(scene_code: str, mode: str = "video") -> AnimResult:
    h = sha256(scene_code)
    if mode == "video" and cache.has(h):
        return AnimResult(kind="video", url=cache.url(h))
    # 写入临时 MC project（warm template，依赖已装），执行 mc render / mc player
    ...
```

- 预渲染优先：默认 video 模式，离线生成 mp4，前端用 `<video>` 播放，零运行时依赖、可 CDN。
- 实时模式按需：用户想拖时间线/改参数时请求 live 模式，后端起 MC player，空闲 60s 自动关。
- 缓存：scene 代码 SHA-256 命中即返回旧 mp4，文档未变不重渲染。
- 降级：渲染超时/失败 → 显示 `fallbackSvg` 静态图 + 文字说明，课件永远可读。

### 4a.5 Scheduler（定期自动上新）

- **调度**：APScheduler 按 `Source.poll_cron` 定时触发 Crawler → TopicDiscover → Composer → AnimGen → Publish。
- **diff 增量**：对每节内容算 `fingerprint`（章节级 SHA-256），与上次比较，只对变化章节重生成，产出新 `Frame.version`，写入 `VersionDelta`。
- **多实例**：Studio 可起多进程并行生产不同 topic，互不阻塞；Backend 入库时按 `course_id` 串行化。
- **手动触发**：支持 CLI 单独跑某个 topic 或某个源，用于调试与紧急上新。

## 4b. Backend 模块（仓库）

职责：**增删改查动画数据 + 托管生成的网页 + 定期自动上新**。

### 4b.1 数据模型（SQLModel）

```python
class Course(SQLModel, table=True):
    id: str                 # slug，如 "python-asyncio"
    title: str
    category: str           # "language" | "course"
    subject: str            # "python" | "signal-system" | ...
    source_id: str          # 关联内容源
    version: int            # 课件版本号
    frames_count: int
    status: str             # "draft" | "published" | "archived"
    created_at: datetime
    updated_at: datetime

class Frame(SQLModel, table=True):
    id: str                 # "{course_id}#{n}"
    course_id: str
    index: int
    title: str
    layout: str             # "title"|"two-col"|"code-focus"|"diagram"|"quiz"
    blocks_json: str        # 内容块（见 §6.1），fragment 顺序即 reveal.js 分步
    notes: str              # 演讲者备注（reveal.js speaker notes）
    version: int            # 帧版本（增量重生成时只升变更帧）

class Source(SQLModel, table=True):
    id: str
    kind: str               # "web"|"git"|"pdf"|"rss"
    url: str
    poll_cron: str          # "0 3 * * *" 每日 3 点
    last_hash: str          # 内容指纹
    last_checked: datetime

class VersionDelta(SQLModel, table=True):
    id: str
    course_id: str
    from_version: int
    to_version: int
    changed_frames: str     # JSON: [frame_id,...]
    reason: str             # "doc updated" | "manual"
    created_at: datetime
```

### 4b.2 API 概览（分读写两组）

**前端读 API（公开）**：

```
GET  /api/courses                    课件列表（含 category 过滤）
GET  /api/courses/{id}               课件元信息 + 帧索引
GET  /api/courses/{id}/frames        全部帧（或 ?since_version=N 增量）
GET  /api/courses/{id}/frames/{n}    单帧
GET  /api/courses/{id}/diff?v=..     版本差异
GET  /api/search?q=                  全文搜索课件/帧
POST /api/sandbox/run                {lang, code} → {stdout, stderr, time_ms}
GET  /api/sources                    内容源列表 + 状态
GET  /api/health
```

**Studio 写 API（admin，需 token 鉴权）**：

```
POST /api/admin/courses              创建/更新课件（含 frames + 附件）
POST /api/admin/courses/{id}/publish 发布上线（draft → published）
POST /api/admin/courses/{id}/archive 下架
POST /api/admin/sources              注册新内容源
DELETE /api/admin/courses/{id}       删除
```

### 4b.3 静态托管

- `/static/courses/{id}/` — 每个课件的 reveal.js HTML + 资源（CSS/JS/SVG）。
- `/static/courses/{id}/anim/` — 该课件 Motion Canvas 预渲染的 mp4，按 scene hash 命名。
- Backend 在 `POST /api/admin/courses` 入库时把 Studio 推送的网页与视频落盘到对应目录，发布时更新索引。
- Frontend 既可走 API 拉 `frames.json` 动态渲染，也可直接打开 `/static/courses/{id}/index.html` 离线看（reveal.js 单 HTML 模式）。

### 4b.4 Sandbox（在线运行）

| 语言 | 方案 | 限制 |
|------|------|------|
| Python | 浏览器内 Pyodide（WASM） | 无网络、500MB 内存、10s 超时 |
| TypeScript | 浏览器内 sucrase + quickjs | 同上 |
| Go | 后端 Docker `golang:alpine` 单文件编译运行 | 离线镜像、5s 超时 |
| Rust | 后端 Docker `rust:alpine` 单文件 | 同上（首次编译慢，缓存 crate） |

所有 sandbox 共用 `judge.py`：捕获 stdout/stderr、强制超时、白名单 import。代码帧默认绑定一个"运行"按钮，输出区在帧内展开。

### 4b.5 Auto-Publish（定时自动上新）

- Studio 推送的课件默认入 `draft` 状态。
- Backend 定时任务（可配置 cron，如每小时）扫描 `draft` 课件，通过校验后批量置 `published`，更新前端可见索引。
- 也可配置"Studio 推送即发布"模式跳过 draft 等待。

## 5. 前端设计

### 5.1 技术栈

- **reveal.js 5.x** — 成熟的开源演示框架，原生 HTML/CSS/JS 幻灯，键盘导航、fragments 分步进场、演讲者备注、overview、PDF 导出全内置。选择它而非自研引擎，因为：
  - **生态丰富**：`reveal.js/plugins` 官方插件（math/KaTeX、highlight、search、menu、zoom、chalkboard）+ 社区插件覆盖绝大多数需求。
  - **任意 HTML 动画可直接嵌**：SVG 路径动画、D3、Canvas、GSAP、CSS `@keyframes`、`<canvas>`、`<iframe>` 都是一个 `<section>` 里的普通网页内容——直接复用网上大量高质量 HTML 动画素材。
  - **fragments 即天然的"分步呈现"**：先问题→后方案→再代码的叙事顺序用 `class="fragment"` 即可，无需自写时间线。
  - **导出与分享**：单 HTML 文件可离线打开；PDF 导出用于打印讲义。
- **Vue 3 + Vite + TypeScript** — 仅作为 reveal.js 外壳（课程库、大纲、播放控制 UI、sandbox 交互壳），不重新实现幻灯渲染。与 OilPaintingPlatform 技术栈对齐。
- **Pinia** — 课件缓存、播放状态。
- **KaTeX** — 经 reveal.js math 插件接入。
- **Shiki 或 highlight.js** — 代码高亮（highlight.js 是 reveal.js 内置插件，零配置；Shiki 作为可选升级）。
- **Monaco Editor** — 代码帧内的可编辑区（轻量模式），用户改完点"运行"调 sandbox。
- **hyperframes 插件层**（自研，~250 行 TS，见 §5.3）— 在 reveal.js 之上补四件事：从 `frames.json` 生成 `<section>`、跨帧超链接路由、sandbox 运行按钮绑定、Motion Canvas block 挂载。**不重新实现幻灯内核，也不重新实现动画引擎。**
- **Motion Canvas** — 帧精确的代码驱动动画引擎，用于原理动画（卷积滑窗、OFDM 子载波、注意力流动等）。前端用官方 `@motion-canvas/player` Web Component 嵌入实时动画；预渲染视频用 `<video>`。后端 anim 服务调 MC CLI 渲染。见 §4.8 / §5.4。

### 5.2 页面结构

```
┌──────────────────────────────────────────────────────────────┐
│  TechLearnStudio   [课程库] [学习路径] [搜索]      [暗色] [设置]│  顶栏（Vue 壳）
├────────────┬─────────────────────────────────────────────────┤
│            │                                                 │
│  大纲      │            reveal.js 演示区                      │
│  ─────     │   ┌─────────────────────────────────────────┐   │
│  ▸ 动机     │   │  <section> 标题/公式/代码/动画/控件       │   │
│  ▸ 概念     │   │   fragments 分步进场                      │   │
│  ▼ 示例     │   │                                         │   │
│    · 代码   │   │   ← → 翻页 （reveal.js 原生快捷键）       │   │
│    · 图解   │   │   [运行代码]  [重置]  [演讲者备注 S]       │   │
│  ▸ 陷阱     │   └─────────────────────────────────────────┘   │
│  ▸ 进阶     │                                                 │
│            │   进度 ▬▬▬▬▬●▬▬▬▬▬▬▬▬  帧 3/18                │
└────────────┴─────────────────────────────────────────────────┘
```

### 5.3 hyperframes 插件层（自研，轻量）

reveal.js 已解决幻灯渲染、导航、分步、导出；hyperframes 插件只补 reveal.js 没有的三件事，规模约 200 行 TS，不是一个"引擎"：

1. **序列化渲染**：读 `frames.json`，把每帧转成一个 reveal.js `<section>`（含 `data-frame-id`、`data-layout` 属性），blocks 渲染成对应 HTML。这一步是纯模板映射，无状态机。
2. **跨帧超链接**：`<a data-frame-link="rust-ownership#4">` → 调 `Reveal.slide(indexOfFrame)`。reveal.js 原生支持 `#/section-id` 深链，插件只做 id → index 的解析与跳转动画。
3. **sandbox 绑定**：扫描带 `data-runnable` 的代码块，注入"运行"按钮，点击调 `/api/sandbox/run`，输出区展开在代码块下方。

**动画交给 reveal.js 原生能力 + 网页标准**，不自写时间线引擎：

| 动画需求 | 实现方式 |
|----------|----------|
| 元素分步进场 | `class="fragment"` + `data-fragment-index`（reveal.js 原生） |
| 进出过渡风格 | `class="fragment fade-up/fade-in/zoom-in/..."`（reveal.js 内置多种） |
| 公式步进推导 | 每步一个 fragment，KaTeX 渲染 |
| SVG 路径绘制 | 内联 SVG + CSS `stroke-dashoffset` 动画或 D3，作为普通 HTML 嵌入 |
| 数值滚动 / 复杂时间线 | 帧内 `<script>` 调 Web Animations API 或 GSAP（按需引入） |
| 高亮代码行 | highlight.js `data-line-numbers` + fragment 高亮 |

```ts
// hyperframes 插件 API（~250 行）
interface HyperframesPlugin {
  render(course: Course): HTMLElement        // frames.json → reveal <section>s
  goToFrame(frameId: string): void           // 解析 id → Reveal.slide()
  bindRunnables(root: HTMLElement): void     // 给代码块装运行按钮
  mountMotionCanvas(block: MotionCanvasBlock, container: HTMLElement): void
                                             // 把 MC block 挂载到帧内（见 §5.4）
}
```

> 设计取舍：默认动画走 reveal.js fragments（声明式、稳）；需要帧精确时间线的原理动画走 Motion Canvas 通道（见 §5.4）。SVG 简单动画仍用内联 CSS/Web Animations 直接嵌入，网上动画素材可直接搬运。

### 5.4 Motion Canvas Player 前端集成

前端用 Motion Canvas 官方的 `@motion-canvas/player` Web Component 嵌入实时动画，预渲染视频则用 `<video>`。两者都作为 reveal.js 一个 `<section>` 内的普通 HTML 元素，由 hyperframes 插件的 `mountMotionCanvas` 装载。

#### 5.4.1 两种播放形态

| `renderMode` | 前端载体 | 交互 | 适用 |
|--------------|----------|------|------|
| `video`（默认） | `<video src="{mp4 url}" controls>` | 播放/暂停/拖动 | 离线课件、CDN 分发 |
| `live` | `<motion-canvas-player>` Web Component + 后端 MC player WebSocket | 拖动时间线、改参数重渲染 | 用户想"玩"动画时按需启用 |

```html
<!-- video 模式：reveal <section> 内 -->
<section data-frame-id="signal-conv#4" data-layout="diagram">
  <h2>卷积：核滑过信号</h2>
  <div class="mc-anim" data-mc-block="signal-conv#4">
    <video src="/api/anim/file/abc123.mp4" controls preload="none"></video>
    <button data-mc-live="signal-conv#4">改用实时模式 ↻</button>
  </div>
  <p class="fragment">每一格 = 核与对应信号段的逐点相乘累加。</p>
</section>

<!-- live 模式（用户点上面按钮后切换） -->
<motion-canvas-player src="/api/anim/live/abc123"></motion-canvas-player>
```

#### 5.4.2 与 reveal.js fragments 的协同

MC 动画和 fragments 是**两条独立时间线**，但可协同：

- 默认：MC 动画作为帧内一个独立元素，进帧时自动播放一次；fragments 文字按空格分步出现。
- 协同模式（block 带 `syncWithFragments: true`）：MC player 监听 reveal.js `fragmentshown`/`fragmenthidden` 事件，把动画时间线对齐到 fragment 步——例如 fragment 1 触发"核滑到第 1 格"动画段。由 hyperframes 插件做事件桥接（~30 行）。

#### 5.4.3 性能与降级

- `prefers-reduced-motion`：MC 视频静音自动播放改为显示首帧 + 播放按钮。
- 加载失败 / 后端 MC 未启用：显示 `fallback_svg`（Composer 在生成时一并产出）+ 文字说明，课件永远可读。
- live 模式进程空闲 60s 自动关，前端按钮变回 video 模式。

### 5.5 帧布局组件

| layout | 用途 | 关键元素 |
|--------|------|----------|
| `title` | 章节封面 | 大标题 + 副标题 + 进度 |
| `two-col` | 对比讲解 | 左概念 / 右代码 或 左问题 / 右方案 |
| `code-focus` | 代码为主 | Monaco + 行高亮 + 运行按钮 + 输出区 |
| `diagram` | 图解动画 | SVG + 路径动画 + 标注；复杂时嵌 MC Player |
| `formula` | 公式推导 | KaTeX 步进式展开 + 文字解释 |
| `quiz` | 即时测验 | 单选 + 提交反馈 + 跳回相关帧 |
| `summary` | 章节小结 | 要点卡片 + 下一章预告 |

## 6. Hyperframes 内容格式（规范）

### 6.1 Block 类型

```ts
type Block =
  | { type: 'text', md: string, fragment?: number }
  | { type: 'code', lang: string, src: string, runnable: boolean, highlight?: number[], fragment?: number }
  | { type: 'formula', tex: string, explain?: string, fragment?: number }
  | { type: 'diagram', svg: string, svgAnim?: string, fragment?: number }
  | { type: 'motionCanvas', sceneRef: string, params: object, renderMode: "video"|"live",
      fallbackSvg?: string, syncWithFragments?: boolean, fragment?: number }   // 原理动画，见 §4.8
  | { type: 'canvas', script: string, fragment?: number }   // 轻量 Canvas 动画（标准 Web API）
  | { type: 'callout', kind: 'tip'|'warn'|'pitfall', md: string, fragment?: number }
  | { type: 'quiz', q: string, opts: string[], answer: number, why: string, link?: string, fragment?: number }
  | { type: 'link', to: string, label: string }   // 跨帧超链接（hyperframes 插件解析）
```

`fragment` 为可选数字，省略则随上一元素一起出现。选择规则：简单顺序开关用 `fragment`；轻量 SVG/CSS 动画用 `diagram.svgAnim` 或 `canvas.script`；**帧精确原理动画**用 `motionCanvas`（走 Motion Canvas 通道）。

### 6.2 一个完整帧示例（Rust 所有权）

```json
{
  "id": "rust-ownership#3",
  "title": "为什么需要所有权？",
  "layout": "two-col",
  "blocks": [
    { "type": "text", "md": "## 问题\nC/C++ 里同一块内存可能被多个指针持有 → **释放两次**或**悬垂指针**。", "fragment": 0 },
    { "type": "diagram", "svg": "...", "fragment": 1,
      "svgAnim": "stroke-dashoffset 绘制两个指针 → 内存块连线，CSS @keyframes" },
    { "type": "callout", "kind": "pitfall", "md": "运行时错误，难以排查。", "fragment": 2 },
    { "type": "text", "md": "## Rust 的答案\n**单一所有权 + 编译期检查**。", "fragment": 3 },
    { "type": "code", "lang": "rust", "runnable": true, "src": "fn main() {\n    let s = String::from(\"hi\");\n    let t = s;          // 移动\n    // println!(\"{}\", s); // 编译错误：s 已被移动\n    println!(\"{}\", t);\n}", "highlight": [2, 3], "fragment": 4 },
    { "type": "link", "to": "rust-ownership#4", "label": "下一帧：借用与引用 →" }
  ],
  "notes": "强调'编译期'三个字——Rust 把 GC 的成本挪到了编译时。"
}
```

渲染结果：reveal.js 一个 `<section>`，6 个 block 按 `fragment` 顺序分步进场（按空格逐个出现），代码块带"运行"按钮（hyperframes 插件注入）。复杂动画（如指针连线）由 `svgAnim` 字段以标准 CSS/SVG 表达，直接嵌网页，不自写时间线引擎。

### 6.3 课件清单（首批规划）

| 课程 | 类别 | 帧数（估） | 内容源 |
|------|------|-----------|--------|
| Python 异步编程 | language | 18 | docs.python.org/asyncio |
| Rust 所有权与借用 | language | 14 | The Book ch.4 |
| Go 并发：goroutine 与 channel | language | 16 | go.dev/doc/effective_go |
| TypeScript 类型体操 | language | 20 | typescriptlang.org/docs |
| 信号与系统：卷积的本质 | course | 22 | 教师讲义 |
| 无线通信：OFDM 原理 | course | 24 | 教师讲义 + 论文 |
| 大模型：注意力机制从零讲 | course | 20 | Transformer 论文 + 讲义 |

每节目标学习时长 15–25 分钟，单帧 30–90 秒。

## 7. 自动更新流程（端到端）

```
[APScheduler: 每日 03:00]
        │
        ▼
for source in sources:
    docs = await source.fetch()
    fp = source.fingerprint(docs)
    if fp != source.last_hash:
        changed = diff_sections(source.last_docs, docs)
        for section in changed:
            frames = await composer.compose(section, course_id)
            frame_store.save(frames, version=course.version+1)
        version_delta.record(...)
        source.last_hash = fp
        notify_frontend(course_id)   # SSE 推送
```

- 首次合成走完整管线；后续只重生成变化章节。
- LLM 调用走多 provider 轮询（OpenAI / 智谱 / Pollinations 免费档），失败降级规则模板。
- 每帧带 `version`，前端可显示"本帧基于 v3 文档，已更新到 v4"并一键查看 diff。

## 8. 与 monorepo 的关系

- 放在 `AIforEducation/TechLearnStudio/`，与 `OilPaintingPlatform/`、`GestureCoach/` 平级。
- 共享 `docs/` 文档体系（本文件归入 `docs/modules/`）。
- 不复用其他子项目代码，但**对齐技术栈**：FastAPI + Vue3 + Vite + Pinia，与 OilPaintingPlatform 一致，便于维护者切换。
- LLM 客户端设计参考 OilPaintingPlatform 的多 provider 模式（含免费 Pollinations 档）。

## 9. 里程碑

| 里程碑 | 模块 | 内容 | 验收 |
|--------|------|------|------|
| M1 Backend 骨架 | Backend | FastAPI + SQLite + Course/Frame CRUD + 静态托管 | `/api/health` 通；手写课件能 CRUD 并静态访问 |
| M2 Frontend 播放 | Frontend | Vue3 + reveal.js + hyperframes 插件 + sandbox 交互 | 播放一节 5 帧手写课件，fragment 分步 + 代码运行 |
| M3 Studio 合成器 | Studio | Crawler(python_docs) + Composer + Publish → Backend | 一键生成"Python 异步编程"18 帧，经 admin API 入库并上线 |
| M4 Motion Canvas | Studio + Frontend | AnimGen + anim_render + 前端 MC Player | 卷积滑窗动画自动生成、预渲染 mp4、嵌入课件，video/live 可切 |
| M5 多语言 | Studio | Rust/Go/TS 内容源 + sandbox | 三门课各一节自动生成并运行 |
| M6 专业课 | Studio | 信号/无线/大模型源（PDF）+ 对应动画模板 | 三门专业课各一节，含至少一个 MC 原理动画 |
| M7 自动上新 | Studio + Backend | Scheduler cron + diff 增量 + Auto-Publish | 模拟文档更新，Studio 自动推送、Backend 自动发布、前端收到版本提示 |
| M8 打磨 | 全部 | 暗色模式、搜索、学习路径、进度持久化 | 端到端冒烟测试通过 |

## 10. 风险与对策

| 风险 | 对策 |
|------|------|
| LLM 生成的代码无法运行 | Composer QA 步骤强制 sandbox 跑通，失败则降级到官方文档原文块 |
| 文档站点反爬 | adapter 优先用官方 sitemap/RSS；限速 + User-Agent；PDF 讲义走本地上传 |
| 动画在低端机卡顿 | reveal.js 检测 `prefers-reduced-motion` 降级为瞬时切换；MC 默认 video 模式由后端预渲染，前端只播 mp4，不占本机算力 |
| LLM 成本 | 仅大纲/帧结构/旁白用 LLM；代码与公式优先从原文抽取；免费 provider 优先 |
| 专业课内容版权 | 默认本地讲义上传；不缓存原文到仓库，只存生成的 frames.json |
| MC 渲染慢/失败 | scene 代码 SHA-256 缓存；首次渲染超时降级为 `fallbackSvg` 静态图 + 文字；live 模式进程空闲 60s 自动关 |
| MC 项目 npm install 慢 | 后端预置一个 warm 的 `project_template/`，依赖已装好；增量 scene 只复制代码不重装 |
| LLM 生成的 scene 跑不通 | AnimGen QA 步骤强制 `mc render` 试跑短预览，失败降级到模板匹配或 fallbackSvg |

## 11. 开放问题（待定）

1. hyperframes DSL 是否需要可视化编辑器？（M7 后视用户反馈决定）
2. 是否支持"教师上传一份 PPT 自动转 hyperframes"？（可作为 M8 扩展）
3. 学习进度是否要接入 monorepo 的用户体系？（目前无统一账号，先用 localStorage）
4. 是否支持用户在课件里**改 MC 动画参数实时重渲染**？（live 模式已具备能力，UI 待设计，M8 扩展）

---

*本文档为设计稿，实现以 M1 骨架为起点，逐步落地。*
