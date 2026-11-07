# ArtRealm3D (艺境) — 模块与文件参考

> **路径**: `ArtRealm3D/` ｜ **版本**: 0.1.0 ｜ **依赖**: Python ≥ 3.11, FastAPI, uvicorn, NumPy, Pillow, pytest；前端: Node ≥ 18, Vue 3, Vite, Three.js, axios

## 项目简介

艺境是一个**世界名画三维沉浸式体验教学服务平台**（前后端完整系统）。把世界名画解构为多层三维画层——天空、大地、人物各自独立"呼吸"；章节式镜头带学习者从构图分析走向精神内核；导览结束自动进入学习检验（后端判分 + 逐题解析 + 评语）。

核心理念：**零外部图片依赖**——全部画层由程序化渲染器按"风格处方"（palette + 几何语义）确定性生成，带 alpha 的 RGBA 图层 PNG 按内容签名缓存。

内置三幅名画：梵高《星月夜》、葛饰北斋《神奈川冲浪里》、维米尔《戴珍珠耳环的少女》。

## 文件结构

```
ArtRealm3D/
├── backend/                       # FastAPI 后端 (端口 8300)
│   ├── app/
│   │   ├── main.py                # 应用工厂 + 静态托管 /static/generated → data/generated
│   │   ├── config.py              # settings (端口/输出目录/URL 前缀/CORS)
│   │   ├── schemas.py             # MasterpieceBrief / QuizSubmission / QuizResult
│   │   ├── data/
│   │   │   ├── masterpieces.py    # 名画知识库: 背景/精神内核/分层构图/章节/测验
│   │   │   └── generated/         # 渲染缓存 (mid/sig/manifest.json + 各层 PNG)
│   │   ├── services/
│   │   │   ├── renderer.py        # 程序化分层渲染器 (numpy+PIL, 确定性输出)
│   │   │   └── assets.py          # 图层资产管线 (内容签名缓存, 损坏自愈)
│   │   └── routers/
│   │       ├── masterpieces.py    # GET /api/masterpieces, GET /{mid}, POST /{mid}/quiz
│   │       └── health.py          # GET /api/health
│   └── tests/test_backend.py      # 22 个测试
└── frontend/                      # Vite + Vue3 + Three.js (端口 5173)
    └── src/
        ├── three/PaintingScene.js # 分层视差场景引擎 (呼吸微动+指针视差+章节聚焦)
        ├── api/index.js           # axios 封装 (20s 超时)
        ├── router/index.js        # / → /painting/:id → /quiz/:id 懒加载
        └── views/
            ├── Home.vue           # 目录页
            ├── Tour.vue           # 沉浸导览 (章节字幕卡+时间线+语音朗读)
            └── Quiz.vue           # 学习检验 (判分后显示每题解析)
```

## 数据流

```
知识库 "风格处方" (palette + 几何语义)
        │  render_layers_sorted()  — 首次请求时渲染
        ▼
带 alpha 的 RGBA 图层 PNG (按内容签名缓存到 data/generated/mid/sig/)
        │  manifest.json: [{role, depth, semantics, url}]
        ▼
前端 PaintingScene 按 depth 摆进 3D 空间 (z = depth × 0.42)
        │  章节叙事 (chapters[].focus) 驱动镜头
        ▼
导览结束 → POST /quiz 判分 → 逐题解析
```

## 关键设计

- **测验防作弊**: `GET /api/masterpieces/{mid}` 不下发 `quiz[*].answer / explain`，客户端只能从判分结果的 `per_question` 中获得正确答案与解析（2026-11-08 修复）。
- **缓存签名**: `_layer_sig` 对 (mid, layers JSON) 取 SHA-256 前 16 位；manifest 读取容错——损坏缓存自动丢弃重渲染，不再 500。
- **渲染器贴图粘贴**: 星晕/珍珠光晕均以 RGBA 自身为 mask 粘贴（无 mask 会把透明区转出的纯黑方块盖到画面上——2026-11-08 修复星夜黑方块）。
- **Three.js 色彩空间**: three r152+ 需显式 `tex.colorSpace = THREE.SRGBColorSpace`，否则画面偏灰发白。
- **异步加载竞态**: `_loadLayers` await 后检查 `disposed`，页面切走时释放已加载纹理。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/masterpieces` | 目录（MasterpieceBrief 列表） |
| GET | `/api/masterpieces/{mid}` | 详情 + 图层 manifest（不含测验答案） |
| POST | `/api/masterpieces/{mid}/quiz` | 提交答案 `{answers: [int]}` → QuizResult |
| GET | `/api/health` | 健康检查 |

## 运行与测试

```bash
# 后端
cd ArtRealm3D/backend && pip install -r requirements.txt
uvicorn app.main:app --port 8300        # API 文档: http://127.0.0.1:8300/docs

# 前端 (自动代理 /api 与 /static 到 8300)
cd ArtRealm3D/frontend && npm install && npm run dev
# 打开 http://localhost:5173 (Vite 默认绑 IPv6, 用 localhost 不要用 127.0.0.1)

# 测试
cd ArtRealm3D/backend && python -m pytest tests -q   # 22 passed
```

## 已知边界

- 程序化渲染是**风格化抽象**，非原画复刻；图层角色固定为 sky/hills/waves/village/cypress/pearl/girl 等语义层。
- 语音朗读依赖浏览器 `speechSynthesis`（Chrome 的 cancel+立即 speak 偶发丢失，已知浏览器怪癖）。
- 渲染缓存签名只覆盖数据不覆盖渲染代码——改 renderer 后需删 `data/generated/` 重新生成。
