# 艺境 ArtRealm3D

> AI for Education · 世界名画三维沉浸式体验教学服务平台（前后端完整系统）

把世界名画解构为**多层三维画层**——天空、大地、人物各自独立"呼吸"；章节式镜头
带你从构图分析走向精神内核；以测验巩固所学。

## ✨ 特性

- **三维名画场景**：每幅画拆解为 3–4 个带深度信息的画层（纯程序化渲染，零外部图片依赖），
  Three.js 视差场景支持鼠标环视、图层呼吸微动、画框与景深雾效
- **章节式沉浸导览**：进入画中 → 构图分析 → 时代背景 → 精神内核 → 尾声，
  每章自动驱动镜头聚焦对应画层，配字幕卡与可选中文语音朗读
- **教学闭环**：导览结束自动进入学习检验，后端判分 + 逐题解析 + 评语
- **内置三幅名画**：梵高《星月夜》、葛饰北斋《神奈川冲浪里》、维米尔《戴珍珠耳环的少女》

## 🏗️ 架构

```
ArtRealm3D/
├── backend/                 # FastAPI
│   ├── app/
│   │   ├── data/masterpieces.py    # 名画知识库：背景/精神内核/分层构图/章节/测验
│   │   ├── services/renderer.py    # 程序化分层渲染器 (numpy+PIL, 确定性输出)
│   │   ├── services/assets.py      # 图层资产管线 (处方+渲染器代码签名缓存)
│   │   └── routers/                # /api/masterpieces, quiz, health
│   └── tests/test_backend.py       # 27 个测试
└── frontend/                # Vite + Vue3 + Three.js
    ├── src/
    │   ├── composables/useTourTimeline.js  # 导览章节时间线（纯逻辑，可单测）
    │   ├── three/PaintingScene.js  # 分层视差场景引擎
    │   └── views/                  # Home(目录) / Tour(沉浸导览) / Quiz(测验)
    └── tests/run-tests.mjs         # 时间线纯逻辑测试（node 直接运行）
```

**数据流**：知识库中的"风格处方"（palette + 几何语义）→ 渲染器产出带 alpha 的
RGBA 图层 PNG（按处方 + 渲染器代码哈希签名缓存，代码一变自动重渲染并清理旧缓存）→
前端按 `depth` 摆进 3D 空间 → 章节叙事驱动镜头。

## 🚀 运行

```bash
# 后端 (端口 8300)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8300        # API 文档: http://127.0.0.1:8300/docs

# 前端 (端口 5173, 自动代理 /api 与 /static 到 8300)
cd frontend
npm install
npm run dev                             # 打开 http://localhost:5173
```

> 注意：Vite dev server 默认绑定 IPv6 `localhost`，请用 `http://localhost:5173` 访问。

## 🧪 测试

```bash
cd backend && python -m pytest tests -q     # 27 passed
cd frontend && npm test                     # 导览时间线纯逻辑测试 (node tests/run-tests.mjs)
cd frontend && npm run build                # vite build 通过
```

> 前端测试选用 node 直接运行的纯 JS 脚本（参考 TechLearnStudio 的做法），
> 不引入 vitest 依赖：`useTourTimeline` 被设计为无定时器、无 DOM 的纯状态机
> （组件用 setInterval 驱动 `tick(dtMs)`），测试直接调 tick 即可确定性覆盖
> "切章重臂 / 暂停恢复 / 末章转跳"三个历史 bug 高发场景。

## 📖 API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/masterpieces` | 名画目录 |
| GET | `/api/masterpieces/{id}` | 详情：图层 URL + 章节叙事 + 测验题 |
| POST | `/api/masterpieces/{id}/quiz` | 提交答案 `{answers:[int]}` → 判分 + 解析 |
| GET | `/static/generated/...` | 图层 PNG（带 alpha，供 3D 合成） |

## ➕ 扩展新名画

在 `backend/app/data/masterpieces.py` 中追加一条记录即可：定义 `layers`
（每层一个渲染风格 + 调色板 + 深度）、`chapters`（叙事 + 镜头焦点）、`quiz`。
若需要新的视觉风格，在 `renderer.py` 注册一个绘制函数。无需改动前端。

## 📚 设计文档

见 [docs/design.md](docs/design.md)。
