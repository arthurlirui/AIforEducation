# TechLearnStudio

> 用 hyperframes 把任意技术的文档变成可交互的网页 PPT + 动画，让人类 15 分钟学会一门新技术。

**状态**：M1–M7 已基本实现（64 项 pytest 通过，含 e2e；前端 25 项纯函数测试通过；前端可构建播放）。M8 打磨与部分子项为降级实现，详见下"实现状态"。完整设计见 [`../docs/modules/techlearnstudio.md`](../docs/modules/techlearnstudio.md)。

## 三模块架构

| 模块 | 角色 | 核心动作 | 部署 |
|------|------|----------|------|
| **Studio** | 生产者 | 大模型抓新技术 → 搜教学 topic → 设计 frames.json + 动画 → 推送 Backend | 独立进程，cron 或手动 |
| **Backend** | 仓库 | 课程/帧 CRUD、托管静态网页、sandbox、定时自动上新 | 长驻 FastAPI |
| **Frontend** | 消费者 | reveal.js 渲染课件 + SVG/SMIL 原理动画 + 交互 | 静态站点 + Vue 壳 |

三者通过 HTTP 解耦：Studio 是 Backend 的特权客户端，Frontend 是普通客户端。

## 目录

```
TechLearnStudio/
├── studio/        生产者：crawler(7 内容源) + composer(LLM+规则) + anim_client(经 HTTP 取 backend 动画) + scheduler + publish
├── backend/       仓库：FastAPI + SQLModel/SQLite + CRUD + 静态托管 + sandbox(stub) + 搜索(内存)
├── frontend/      消费者：Vue3 + reveal.js + 自研 hyperframes 插件 (JS)
└── tests/         e2e 冒烟（起真实 uvicorn 子进程）
```

## 实现状态（2026-10-29）

| 里程碑 | 状态 | 说明 |
|--------|------|------|
| M1 Backend | ✅ | 6 路由 + SQLModel + admin 鉴权，真实 DB 运行过 |
| M2 Frontend | ✅（降级） | hyperframes 插件完整；reveal.js/highlight/KaTeX 为 CDN 动态加载（离线不可用，公式块在 KaTeX 加载失败时降级为纯文本解释）；无 TS；**代码块只读**（无 Monaco，不可编辑后再运行） |
| M3 Studio | ✅ | crawler 7 源（内置离线内容，真实抓取留接口）+ composer LLM 降级 |
| M4 动画 | ✅（替代实现） | 自研 SVG/SMIL 动画（卷积/所有权/OFDM/注意力 4 模板），非 Motion Canvas；模板唯一实现在 backend（`app/services/anim_gen.py`），studio compose 时经 HTTP 获取 fallbackSvg，离线降级为静态占位图 |
| M5 多语言 | ✅ | Rust/Go/TS 源就绪；**sandbox 为 stub（回显不执行）** |
| M6 专业课 | ✅ | 信号/无线/大模型源就绪 |
| M7 自动上新 | ✅ | APScheduler 巡检 + diff + 发布 |
| M8 打磨 | ⬜ | 搜索为内存占位；无学习路径/进度持久化 |

## 主要待办

1. **真实 sandbox**（核心卖点缺口）：`backend/app/sandbox/runner.py` 接入 Pyodide 或 Docker
2. **前端依赖本地化**：reveal.js/highlight/KaTeX 改 npm 依赖，保证离线播放
3. M8 打磨（搜索 FTS、学习路径、进度持久化）；Monaco 代码编辑

## 技术栈

- Studio：Python 3.11+ · APScheduler · LLM(OpenAI-compatible 多 provider 回退)
- Backend：FastAPI · SQLModel · SQLite
- Frontend：Vue 3 · Vite · reveal.js 5.x（CDN）

## 覆盖内容

- **编程语言**：Python / Rust / Go / TypeScript（可扩展 adapter）
- **专业课程**：信号与系统、无线通信、大模型原理

## 运行与测试

```bash
pip install -r backend/requirements.txt
pip install -r studio/requirements.txt   # APScheduler / httpx（Studio 侧）
pytest -v                      # 64 项（backend 21 + studio 41 + e2e 2；e2e 起真实 uvicorn 子进程）
cd frontend && npm install && npm run dev
cd frontend && npm test        # 前端 hyperframes 纯函数测试（25 项）
```

注意：Backend 的写接口（`/api/admin/*`）需要 `TLS_ADMIN_TOKEN` 环境变量；
**未配置时所有写操作直接拒绝**（fail-safe），开发时请显式设置，例如
`TLS_ADMIN_TOKEN=dev-token uvicorn app.main:app`。
