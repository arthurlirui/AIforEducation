# HistorySandbox (读史) — 模块与文件参考

> **路径**: `HistorySandbox/` ｜ **版本**: 0.1.0 ｜ **依赖**: Python ≥ 3.11, FastAPI, uvicorn, Pydantic, httpx, pytest；前端: Node ≥ 18, Vue 3, Vite, Three.js

## 项目简介

读史是一个 **AI 历史教育三维沙盘推演教学平台**：像沙盘游戏一样"看"历史——三维低多边形沙盘上推演世界与国家尺度的历史事件（疆域进退、行军路线、关键战役），AI 讲解员动态讲述每一步的背景与精神内核；学习者还可以**干预历史**——机动、进攻、结盟、后撤、假想推演，世界模型引擎即时推演出后果（标记为 ✦ 假想，非史实）。

内置 4 个剧本（大航海时代、赤壁之战、丝绸之路、二战·欧洲战场），每剧本 6 幕，共 24 幕推演数据。

## 文件结构

```
HistorySandbox/
├── backend/                          # FastAPI 后端 (端口 8100)
│   ├── app/
│   │   ├── main.py                   # API 路由 (events/narrate/ask/simulate/health)
│   │   ├── models.py                 # Pydantic 模型 (含 WorldCommand / 模拟步)
│   │   ├── config.py                 # 配置 (LLM 可选)
│   │   ├── data/                     # 历史事件推演数据 (沙盘剧本 JSON × 4)
│   │   └── services/
│   │       ├── ai_narrator.py        # AI 讲解/问答 (LLM 可选 + 本地引擎回退)
│   │       └── world_model.py        # 世界模型引擎 (规则动力学 + LLM 反事实)
│   └── run.py                        # uvicorn 启动器 (127.0.0.1:8100)
├── frontend/                         # Vue 3 + Vite + Three.js (端口 5173)
│   └── src/
│       ├── App.vue                   # 主应用 (事件加载/步进播放/推演入口)
│       ├── api.js                    # API 封装
│       ├── sandbox/                  # 三维沙盘引擎
│       │   ├── SandboxEngine.js      # 沙盘渲染 + 射线拾取 + 步应用
│       │   ├── worldGeo.js           # 经纬度 → 世界坐标 + 地形网格
│       │   └── cameraRig.js          # 相机 rig (flyTo/autoRotate/距离钳制)
│       └── components/
│           ├── SidebarEventList.vue  # 剧本列表
│           ├── StepTimeline.vue      # 幕时间线
│           ├── InfoPanel.vue         # 幕信息 (背景/解说/精神内核)
│           ├── NarratorPanel.vue     # AI 讲解 + 问答 (打字机效果)
│           ├── PlaybackControls.vue  # 播放控制
│           └── WorldModelPanel.vue   # 交互推演面板 (五模式)
├── tests/test_backend.py             # 27 个测试
└── pytest.ini
```

## 世界模型引擎

```
POST /api/simulate {event_id, step_id, seed, command, ...}
        │
        ├─ move     移动到 target_position (钳制移动范围)
        ├─ attack   向最近敌军开战 (兵力损耗 + 士气), 无敌军 → 409 结构化提示
        ├─ retreat  向己方区域后撤
        ├─ alliance 与 target_nation 结盟 (改变阵营关系)
        └─ hypothetical  LLM 反事实推演 (本地规则引擎回退)
        │
        ▼
模拟步 (id = 900 + step_id 哨兵, hypothetical=true)
        │  前端 engine.applyStep() 增量应用到沙盘
        ▼
✦ 假想推演 (非史实) — InfoPanel 显示"假想推演"而非幕号
```

- **规则动力学**: 兵力/士气/位置按确定性规则演化；主场防御加成（`_in_area` 检查势力全部疆域多边形——2026-11-08 修复只查首个多边形的 bug）。
- **LLM 可选**: 讲解/问答/反事实都有本地引擎回退，无 Key 无网络可完整运行。
- **409 友好提示**: `CommandUnavailable` 返回 `{reason, message}`；前端解析 `detail.message` 展示中文引导（2026-11-08 修复解析路径）。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | 剧本列表 |
| GET | `/api/events/{id}` | 剧本详情 (幕/势力/沙盘) |
| POST | `/api/narrate` | `{event_id, step_id, style}` → 讲解文本 |
| POST | `/api/ask` | `{event_id, step_id, question, top_k}` → 问答 |
| POST | `/api/simulate` | `{event_id, step_id, seed, command, ...}` → 模拟步 |
| GET | `/api/health` | 健康检查 |

## 运行与测试

```bash
# 后端
cd HistorySandbox/backend && pip install -r requirements.txt
python run.py                          # http://127.0.0.1:8100 (API 文档 /docs)

# 前端 (vite 代理 /api → 8100)
cd HistorySandbox/frontend && npm install && npm run dev
# 打开 http://localhost:5173

# 测试
cd HistorySandbox && python -m pytest tests -q    # 27 passed
```

## 关键实现细节 (踩坑记录)

- **中文滑窗分词**: 本地检索引擎对中文按滑窗切词（无分词依赖）。
- **打字机取消**: NarratorPanel 用 generation token 取消在途打字，快速切幕不串音；watch `[eventId, stepId]` 而非仅 stepId（同幕号换剧本时也要重新拉取——2026-11-08 修复）。
- **单阵营幕 attack**: 某些幕只有一个阵营，无敌人可攻 → 后端 409 + 前端按钮禁用双保险。
- **推演后强度条**: `_updateActorLook` 同步更新兵力条 scale（推演改变 strength 后不再停留在旧值——2026-11-08 修复）。
- **暂停时自动环视**: `engine.rig.autoRotate = !playing`（曾被 `&& false` 死表达式禁用——2026-11-08 修复）。
