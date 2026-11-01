# 读史 HistorySandbox

**AI for 历史教育 · 沉浸式三维沙盘推演教学平台**

像沙盘游戏一样"看"历史：三维低多边形沙盘上推演世界与国家尺度的历史事件——
疆域进退、行军路线、关键战役，配合 AI 讲解员动态讲述每一步的背景与精神内核。

## 项目结构

```
HistorySandbox/
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── main.py        # API 路由 (events/narrate/ask/simulate)
│   │   ├── models.py      # Pydantic 模型（含 WorldCommand）
│   │   ├── config.py      # 配置
│   │   ├── data/          # 历史事件推演数据（沙盘剧本）
│   │   └── services/
│   │       ├── ai_narrator.py   # AI 讲解/问答服务（LLM 可选 + 本地引擎）
│   │       └── world_model.py   # 世界模型引擎（规则动力学 + LLM 反事实）
│   └── run.py
├── frontend/              # Vue 3 + Vite + Three.js 前端
│   ├── src/
│   │   ├── App.vue
│   │   ├── api.js
│   │   ├── style.css
│   │   ├── sandbox/       # 三维沙盘引擎（含射线拾取交互）
│   │   │   ├── SandboxEngine.js
│   │   │   ├── worldGeo.js
│   │   │   └── cameraRig.js
│   │   └── components/
│   │       ├── SidebarEventList.vue
│   │       ├── StepTimeline.vue
│   │       ├── InfoPanel.vue
│   │       ├── NarratorPanel.vue
│   │       ├── PlaybackControls.vue
│   │       └── WorldModelPanel.vue   # 交互推演面板
└── tests/test_backend.py  # 后端测试（24 项）
```

## 快速开始

```bash
# 后端
cd backend
pip install -r requirements.txt
python run.py            # http://127.0.0.1:8000  (API 文档 /docs)

# 前端
cd frontend
npm install
npm run dev              # http://localhost:5173

# 测试
cd .. && python -m pytest tests/ -v
```

## 核心功能

- **三维沙盘推演**：低多边形世界地图 + 国界光圈 + 行军箭头 + 事件棋子，逐步播放历史进程
- **世界模型交互推演**：不再只是观看——点击"🧠 交互推演"即可干预沙盘：指挥棋子机动/发起进攻/缔结假想同盟/后撤，或提出反事实假想（"如果没有东南风会怎样？"）；规则引擎（兵种机动半径、兵力+守方地利、种子化随机）即时结算并渲染新局面
- **史实/假想严格区分**：所有世界模型生成的步骤均带"✦ 假想推演 · 非史实"徽标与日期后缀，教育场景下绝不混淆
- **世界/国家双尺度**：从丝绸之路的欧亚大陆到大航海的全球航线，再到赤壁之战的江汉之间
- **内置四大推演剧本**：赤壁之战（208）、丝绸之路（前138–166）、大航海时代（1415–1522）、二战欧洲战场（1939–1945）
- **AI 讲解员**：每一步自动生成沉浸式讲解词；支持自由问答（LLM 可配置，本地模板引擎保底离线可用）
- **精神内核解读**：每个事件提炼价值主线（开拓、联合、反思……），并逐步骤分析历史意义

## AI 配置（可选）

后端默认使用本地模板讲解引擎（零依赖、离线可用）。配置 LLM 后自动升级：

```bash
HISTORY_LLM_BASE_URL=https://api.openai.com/v1   # 任意 OpenAI 兼容接口
HISTORY_LLM_API_KEY=sk-...
HISTORY_LLM_MODEL=gpt-4o-mini
```

未配置或调用失败时自动回退本地引擎，服务永不中断。
