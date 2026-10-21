# 油画艺术教学平台 OilPaintingPlatform

一个包含前后端的网站平台，提供**艺术与油画教学**内容，并集成**主流视觉大模型**实现文生图油画创作。

用户只需输入简单的提示词并选择油画艺术风格，平台即可自动合成专业提示词，调用大模型 API 生成符合所选风格的油画作品。

## ✨ 功能特性

- **AI 油画创作** — 输入提示词 + 选择风格 → 自动拼接关键词 → 调用视觉大模型生成油画
- **12 种艺术风格预设** — 印象派、写实主义、古典主义、巴洛克、浪漫主义、文艺复兴、后印象派、表现主义、超现实主义、点彩派、抽象表现主义、中国当代油画
- **多模型接入** — OpenAI DALL·E 3 / 阿里通义万相 / 智谱 CogView / Stable Diffusion WebUI，可随时切换
- **油画教学课程** — 涵盖材料工具、明暗对照法、色彩理论、流派鉴赏、AI 提示词技巧
- **作品画廊** — 自动保存生成结果，可回看提示词、风格与所用模型
- **零配置可演示** — 内置 Mock Provider，无需任何 API Key 即可体验完整流程

## 🏗️ 技术架构

```
OilPaintingPlatform/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 应用入口
│   │   ├── config.py           # 配置（环境变量）
│   │   ├── schemas.py          # Pydantic 数据模型
│   │   ├── routers/            # API 路由
│   │   │   ├── health.py       # GET  /api/health
│   │   │   ├── styles.py       # GET  /api/styles
│   │   │   ├── generate.py     # POST /api/generate
│   │   │   ├── teaching.py     # GET  /api/teaching
│   │   │   └── gallery.py      # GET  /api/gallery
│   │   ├── services/
│   │   │   ├── prompt_builder.py   # 提示词合成
│   │   │   ├── generate_service.py # 生成编排
│   │   │   ├── teaching_service.py # 教学数据
│   │   │   └── providers/          # 视觉大模型适配层
│   │   │       ├── base.py
│   │   │       ├── mock_provider.py       # 占位演示
│   │   │       ├── openai_provider.py     # DALL·E 3
│   │   │       ├── dashscope_provider.py  # 通义万相
│   │   │       ├── zhipu_provider.py      # 智谱 CogView
│   │   │       └── sdwebui_provider.py    # Stable Diffusion
│   │   └── data/
│   │       ├── styles.json     # 风格预设
│   │       └── teaching.json   # 教学文章
│   ├── output/                 # 生成图像存储
│   ├── requirements.txt
│   └── .env.example
└── frontend/                   # Vue 3 前端
    ├── src/
    │   ├── main.js
    │   ├── App.vue
    │   ├── router/index.js     # 路由
    │   ├── stores/app.js       # Pinia 状态
    │   ├── api/index.js        # Axios API 客户端
    │   ├── components/
    │   │   ├── NavBar.vue
    │   │   ├── SiteFooter.vue
    │   │   └── StyleCard.vue
    │   ├── views/
    │   │   ├── Home.vue        # 首页
    │   │   ├── Create.vue      # AI 创作（核心）
    │   │   ├── Teaching.vue    # 教学列表
    │   │   ├── Article.vue     # 文章详情
    │   │   ├── Gallery.vue     # 作品画廊
    │   │   └── About.vue       # 关于
    │   └── assets/main.css
    ├── vite.config.js          # 含 /api 代理到后端
    └── package.json
```

### 工作流程

```
用户输入提示词 + 选择风格
        │
        ▼
Vue 前端 ──POST /api/generate──▶ FastAPI 后端
                                   │
                    ┌──────────────┴──────────────┐
                    │  prompt_builder 合成提示词   │
                    │  (用户提示词 + 风格关键词     │
                    │   + 参考艺术家)              │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  Provider 适配层调用大模型   │
                    │  (DALL·E / 万相 / CogView    │
                    │   / SD WebUI / Mock)         │
                    └──────────────┬──────────────┘
                                   │
                          图像保存到 output/
                                   │
        ◀──返回图像 URL + 合成提示词──
        │
   前端展示 + 归档到画廊
```

## 🚀 快速开始

### 1. 后端

```bash
cd backend

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置 API Key（可选——不配置则使用 mock 演示模式）
cp .env.example .env
# 编辑 .env 填入你拥有的模型 API Key

# 启动
python -m uvicorn app.main:app --reload --port 8000
```

后端启动后：
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

### 2. 前端

```bash
cd frontend

# 安装依赖
npm install

# 开发模式启动（自动代理 /api 到后端 8000）
npm run dev
```

打开 http://127.0.0.1:5173 即可使用。

### 3. 生产构建

```bash
cd frontend
npm run build    # 输出到 dist/
npm run preview  # 本地预览生产构建
```

## 🔑 支持的视觉大模型

| Provider | 模型 | 需要配置 | 说明 |
|----------|------|---------|------|
| `mock` | — | 无 | 内置 SVG 占位图，零配置演示 |
| `openai` | DALL·E 3 | `OPENAI_API_KEY` | OpenAI 官方，支持 revised_prompt |
| `dashscope` | 通义万相 wanx-v1 | `DASHSCOPE_API_KEY` | 阿里云，异步轮询 |
| `zhipu` | CogView-3-plus | `ZHIPU_API_KEY` | 智谱 AI |
| `sdwebui` | SD 1.5 / SDXL | 本地 SD WebUI | 自托管，免费，支持 negative prompt |

在 `.env` 中设置 `DEFAULT_PROVIDER` 来指定默认模型，或在创作页面前端下拉框中临时切换。
如果所选模型不可用（缺 Key 或服务未启动），平台会自动回退到 `mock`，保证 UI 始终可用。

## 📡 API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回可用 provider 列表 |
| GET | `/api/styles` | 获取所有风格预设 |
| GET | `/api/styles/{id}` | 获取单个风格详情 |
| POST | `/api/generate` | 生成油画（核心接口） |
| GET | `/api/teaching` | 获取教学文章列表 |
| GET | `/api/teaching/{id}` | 获取文章详情 |
| GET | `/api/gallery` | 获取作品画廊 |
| GET | `/files/{filename}` | 访问生成的图像文件 |

### 生成接口示例

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "一位少女在黄昏的海边散步",
    "style_id": "impressionism",
    "provider": "mock",
    "size": "1024x1024",
    "n": 1
  }'
```

## 🎨 提示词合成策略

平台不只是把用户提示词原样发给模型，而是根据所选风格自动拼接专业关键词：

1. **用户提示词**（主体描述）作为开头
2. **风格关键词**：如印象派会追加 `visible brushstrokes, vibrant light, broken color, en plein air`
3. **附加关键词**：用户可选填
4. **媒介提示**：自动补充 `oil painting on canvas`
5. **参考艺术家**：如 `in the manner of Claude Monet / Renoir`

这样即使用户只写了一句简单描述，也能得到风格鲜明的油画作品。

## 📚 教学内容

内置 6 篇教学文章：
- 油画入门：材料与工具
- 肥盖瘦原则：油画层级技法
- 印象派的光与色
- 明暗对照法：从卡拉瓦乔到伦勃朗
- 油画中的色彩理论
- AI 油画生成：如何写出好提示词

## 📄 许可

本项目仅供学习交流。生成图像版权归所使用模型的原始服务方所有。
