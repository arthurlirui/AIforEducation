# TechLearnStudio

> 用 hyperframes 把任意技术的文档变成可交互的网页 PPT + 动画，让人类 15 分钟学会一门新技术。

**状态**：设计稿 v0.2（2026-10-21），尚未实现。完整设计见 [`../docs/modules/techlearnstudio.md`](../docs/modules/techlearnstudio.md)。

## 三模块架构

| 模块 | 角色 | 核心动作 | 部署 |
|------|------|----------|------|
| **Studio** | 生产者 | 大模型抓新技术 → 搜教学 topic → 设计 frames.json + MC 动画 → 推送 Backend | 独立进程，cron 或手动 |
| **Backend** | 仓库 | 课程/帧 CRUD、托管静态网页、sandbox、定时自动上新 | 长驻 FastAPI |
| **Frontend** | 消费者 | reveal.js 渲染课件 + MC Player 渲染原理动画 + 交互 | 静态站点 + Vue 壳 |

三者通过 HTTP 解耦：Studio 是 Backend 的特权客户端，Frontend 是普通客户端。

## 目录

```
TechLearnStudio/
├── studio/        生产者：crawler + topics + composer + anim_gen + anim_render + scheduler + publish
├── backend/       仓库：FastAPI + SQLite + CRUD + 静态托管 + sandbox + auto_publish
├── frontend/      消费者：Vue3 + reveal.js + Motion Canvas Player + hyperframes 插件
└── README.md
```

## 技术栈

- Studio：Python 3.11+ · APScheduler · LLM(OpenAI-compatible 多 provider) · Motion Canvas CLI
- Backend：FastAPI · SQLModel · Pyodide(浏览器侧) · Docker(sandbox)
- Frontend：Vue 3 · Vite · TypeScript · reveal.js 5.x · @motion-canvas/player · KaTeX · Monaco

## 覆盖内容

- **编程语言**：Python / Rust / Go / TypeScript（可扩展 adapter）
- **专业课程**：信号与系统、无线通信、大模型原理

## 里程碑

M1 Backend 骨架 → M2 Frontend 播放 → M3 Studio 合成器 → M4 Motion Canvas → M5 多语言 → M6 专业课 → M7 自动上新 → M8 打磨。详见设计文档 §9。
