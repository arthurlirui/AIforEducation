# OilPaintingPlatform — 模块与文件参考

> **路径**: `OilPaintingPlatform/` ｜ **版本**: MVP（未设独立版本号） ｜ **依赖**: 后端 FastAPI + uvicorn + httpx；前端 Vue 3 + Vite + Pinia + Vue Router + Axios

## 项目简介

前后端分离的**油画艺术教学 + AI 文生图**网站。用户输入提示词并选择油画风格，平台自动合成专业提示词，调用视觉大模型 API 生成油画作品。内置 Mock Provider，**零 API Key 即可体验完整流程**。

## 文件结构

```
OilPaintingPlatform/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 入口: 8 路由挂载 + /files 静态托管 + CORS
│   │   ├── config.py              # 环境配置 (各 provider API Key 端点)
│   │   ├── schemas.py             # 请求/响应 Pydantic 模型 (含 ProviderCredentials)
│   │   ├── routers/               # 8 个 API 路由
│   │   │   ├── health.py          # GET /api/health
│   │   │   ├── styles.py          # GET /api/styles — 12 风格
│   │   │   ├── teaching.py        # GET /api/teaching — 6 篇教学文章
│   │   │   ├── gallery.py         # GET /api/gallery — 作品画廊
│   │   │   ├── prompts.py         # GET /api/prompts — 28 提示词模板 (分类筛选)
│   │   │   ├── providers.py       # GET /api/providers — 可用模型列表
│   │   │   └── generate.py        # POST /api/generate — 文生图 (400/502 异常处理)
│   │   ├── services/
│   │   │   ├── prompt_builder.py  # 提示词合成引擎: 用户词+风格关键词+媒介+艺术家+负面词
│   │   │   ├── prompt_service.py  # 模板查询服务
│   │   │   ├── generate_service.py # 生成编排: 选 provider → 构提示词 → 调 API → 落盘
│   │   │   ├── teaching_service.py # 教学文章查询
│   │   │   └── providers/         # 6 个图像生成 Provider
│   │   │       ├── base.py        # ImageProvider 抽象基类 + ProviderRegistry 注册表
│   │   │       ├── mock_provider.py       # SVG 占位图 (零依赖回退)
│   │   │       ├── pollinations_provider.py # 免费无 Key
│   │   │       ├── openai_provider.py     # DALL·E 3 (b64 落盘)
│   │   │       ├── dashscope_provider.py  # 通义万相 (异步轮询)
│   │   │       ├── zhipu_provider.py      # CogView
│   │   │       └── sdwebui_provider.py    # A1111 WebUI API
│   │   └── data/                  # JSON 数据 (风格/文章/模板/画廊索引)
│   ├── output/                    # 生成图片落盘目录
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.vue / main.js / router/index.js / stores/app.js (Pinia)
    │   ├── api/index.js           # 全端点 Axios 客户端
    │   ├── components/            # NavBar / SiteFooter / StyleCard
    │   └── views/                 # 6 页面
    │       ├── Home.vue           # 首页
    │       ├── Create.vue         # 核心创作页: 风格搜索+provider 设置+生成
    │       ├── Teaching.vue       # 课程列表
    │       ├── Article.vue        # 文章详情
    │       ├── Gallery.vue        # 作品画廊
    │       └── About.vue
    └── vite.config.js             # /api /files 代理到 8000
```

## 核心机制

### Provider 抽象

```
ImageProvider (抽象基类)
   ├── name / is_available() / generate(prompt, size, credentials) -> ImageResult
   ▼
ProviderRegistry
   ├── register()/get()/list_available()
   └── 缺 API Key → 自动回退 mock（保证任何时候都能出图）
```

- 前端可传 **per-request 凭据**（`ProviderCredentials`），存 localStorage 不落盘后端
- `generate.py` 路由统一 400（参数错）/ 502（上游失败）异常处理与耗时统计

### 提示词合成

`prompt_builder.py` 拼接顺序：用户提示词 + 风格关键词 + 媒介提示 + 参考艺术家 + 负面提示词。

### 数据持久化

- 静态内容：`styles.json`（12 风格）/ `teaching.json`（6 文章）/ `prompts.json`（28 模板）
- 画廊：`gallery.json`（追加写、上限 200 条）；图片落盘 `backend/output/`，经 `/files` 访问

## 运行

```bash
# 后端
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
# 前端
cd frontend && npm install && npm run dev   # vite 代理 /api → 8000
```

## 已知边界（待办）

- **零测试**：无 pytest/vitest，待补 prompt_builder 与 ProviderRegistry 单测
- `/api/generate` 为同步阻塞端点，长生成期间占用 worker（待改任务队列+轮询）
- 画廊 JSON 追加写有并发竞态；无用户体系（待引入 SQLite）
- README 模型表缺 Pollinations 条目（文档待更新）
