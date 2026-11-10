# HistorySandbox 代码审阅报告（2026-11-09）

## 一、模块结构

| 模块 | 职责 |
|---|---|
| `backend/app/models.py` | Pydantic 领域模型：剧本/幕/棋子/箭头/地形/WorldCommand 等全部数据结构 |
| `backend/app/config.py` | 环境变量覆盖配置（LLM 三元组、CORS、超时） |
| `backend/app/services/__init__.py` | 内存剧本注册表：启动时从 `data/event_*.json` 加载 4 剧本，惰性单例 |
| `backend/app/services/ai_narrator.py` | LLM 旁白/问答服务 + 本地模板引擎保底 + 中文滑窗分词检索 |
| `backend/app/services/world_model.py` | 世界模型推演引擎：行动合法性校验、机动钳制、种子化战斗结算、LLM 反事实分支 |
| `backend/app/main.py` | FastAPI 路由：events/narrate/ask/simulate 四组端点 + 409/422 语义 |
| `backend/app/data/*.json` | 4 剧本 × 6 幕数据（含 7 类中式舆图地形与古地名 label） |
| `frontend/src/App.vue` | 顶层编排：剧本选择、幕播放状态机、世界模型交互状态、假想步接管 |
| `frontend/src/api.js` | fetch 封装（4 个 API 函数） |
| `frontend/src/sandbox/SandboxEngine.js` | Three.js 沙盘引擎：大陆/地形/势力/棋子/箭头/高亮渲染 + 射线拾取 + 逐帧动画 |
| `frontend/src/sandbox/worldGeo.js` | 手绘低模大陆轮廓 + 18 个地标点数据 |
| `frontend/src/sandbox/cameraRig.js` | 球坐标轨道相机 + flyTo 补间 |
| `frontend/src/components/*` (6) | 侧栏/时间轴/信息面板/旁白面板/播放按钮/交互推演面板 |
| `tests/test_backend.py` | 后端冒烟测试 24 项（离线、LLM 关闭） |

---

## 二、逐模块审阅

### 2.1 后端 — world_model.py（推演引擎）

**[world_model.py:331-336] high — LLM 返回非 dict JSON 时 /api/simulate 直接 500**
`_llm_hypothetical` 里 `json.loads(content)` 成功即返回，但 `simulate_hypothetical` 第 336 行立刻 `data.get("actor_moves", [])`。LLM 若返回 JSON 数组、字符串或被截断的合法标量（`"ok"`），`data.get` 抛 `AttributeError`，一路穿透到 `api_simulate` 未捕获 → 500。这类输出在真实 LLM（尤其 max_tokens=600 截断时）并不罕见。
建议：`_llm_hypothetical` 返回前校验 `isinstance(data, dict)`，否则返回 None 走本地回退；同时在 `_build_hyp_prompt` 已写明"不要 markdown"，建议在解析前剥掉 ` ```json ` 围栏（`content.strip().removeprefix("```json").removesuffix("```")`），否则最常见的围栏输出会静默降级为本地推演，用户察觉不到 LLM 从未生效。

**[world_model.py:155-178] medium — 状态机：连续推演不累积（move→attack 会丢掉 move）**
`simulate_command` 每次从历史步 `base` 深拷贝 actors 开始推演；而 App.vue:70 的 `runSimulation` 始终用 `currentStepId`（历史幕号）作 `step_id`。用户先"机动"再"进攻"时，第二次推演从历史基态重新分支，机动被静默丢弃——但沙盘上仍显示第一次的假想局面，用户会以为主线连续。前端 WorldModelPanel 还把 `hypStep.actors`（假想位置）展示给用户选棋子，进一步暗示可链式推演。
建议（二选一，需明确语义）：(a) 前端在二次推演时把 `hypStep`（id=900+x）作为 step 上传，后端 `get_step` 增加对假想步的内存会话支持；(b) 明确"每条命令独立分支"，执行完一条命令后前端自动清掉假想态并提示"已从本幕史实重新推演"。

**[world_model.py:221-237] medium — alliance 命令不校验 target_nation 合法性**
`_check_command_applicable` 对 alliance 无任何检查：传入不存在的 `target_nation`（绕过 UI 直接调 API）会生成"与 bogus-id 携手"的旁白（`_nation_name` 回退为原始 id），且该势力在沙盘上无棋子时 marker 落在 `base.camera or (0,0)`，即非洲外海。也不校验"与进攻方自己结盟"这类无意义输入。
建议：alliance 分支校验 `cmd["target_nation"] in {n.id for n in event.nations}`，否则抛 `CommandUnavailable("unknown_nation", ...)`。

**[world_model.py:180-188] low — 非战斗单位可发起进攻**
attack 只检查"存在敌对棋子"，不检查 attacker.kind。`city`/`battle`/`trade` 棋子均可"进攻"，还可对 `kind=battle` 的标记开战。教学场景建议限定 `actor.kind in ("army", "fleet", "person")` 并在 `_check_command_applicable` 报 `non_combatant`。

**[world_model.py:144] low — `seed=0` 被 `or 42` 吞掉**
`random.Random(cmd.get("seed") or 42)`：显式传 `seed=0` 会静默变成 42，破坏"同 seed 同结果"的可复现约定（测试 test_simulate_attack_deterministic_same_seed 恰好避开 0）。改为 `seed = cmd.get("seed"); seed = 42 if seed is None else seed`。

**[world_model.py:118-132] 409 修复验证：已彻底 ✓**
`_check_command_applicable` 对单阵营幕 attack 抛 `CommandUnavailable("no_enemy", ...)`，`main.py:101-102` 转 409 结构化 detail，`tests/test_backend.py:255-262` 直接断言 409 + reason + 中文提示。三层闭环，无残留路径（enemies 为空的历史路径 185-187 行仍保留 None→422 作兜底，防御性冗余而非漏洞）。

### 2.2 后端 — ai_narrator.py（LLM 旁白 + 中文分词）

**[ai_narrator.py:28-29] XSS 验证：后端已净化 + 前端无 v-html ✓（但净化不完整）**
`_sanitize` 剔除 `<>{}\` 且前端全部用 Vue `{{ }}` 插值（全仓 grep 无 v-html/innerHTML），当前无 XSS 通道。但 `_sanitize` 的字符黑名单思路脆弱：它挡不住 `javascript:` 之类内容，且 world_model.py:362-365 的 LLM 假想 narrative 只做**长度截断**、**不做 _sanitize**——两条 LLM 输出路径净化标准不一致。建议统一走 `_sanitize`（把它提到公共模块），并在前端坚持"永不引入 v-html"的约束写进注释。

**[ai_narrator.py:128-150] 中文滑窗分词：实现正确，两处小瑕疵（low）**
- 137-141 行：只对长度 3-8 的整词生成 2-4 字滑窗，长度 >8 的长词不生成任何滑窗，超长专名会只按整词匹配。建议对 >8 的词也切前 4 字。
- 218 行 `if any("精神" in r or "意义" in r for _, r in [(0, " ".join(refs))])` 是一个绕圈的恒等写法（等价于直接 in 判断），可读性差，非 bug。
- `_extract_terms` 没有单测直测（test_ask_hits_corpus 只测端到端），滑窗边界（size 2/3/4 与 len==size 的关系 `if len(t) > size`）属于典型的回归敏感区，见测试盲区一节。

**[ai_narrator.py:100-115] low — narrate 对 LLM 关闭时每次请求都重建 prompt 中已含的上下文，无缓存**
教育场景同一幕会被多个学生反复请求，本地回退路径计算极快无碍；但 LLM 路径无结果缓存，同一 (event, step, style) 12 秒超时内重复打满 LLM。建议加一个简单的 LRU（key=(event_id, step_id, style)）。

### 2.3 后端 — services/__init__.py / main.py / models.py / config.py

**[services/__init__.py:14-21] low — 剧本加载无容错**
某个 `event_*.json` 解析失败（改数据时手误很常见）会让整个后端启动后所有接口 500（`_load_all` 在首次调用时抛 Pydantic ValidationError）。建议 try/except 每个文件并打日志跳过，或启动时 fail-fast（uvicorn 起不来比运行时 500 更好排查）。

**[models.py:8-9] low — `Faction` Literal 定义后全仓未使用（死代码）**，且 15 个白名单阵营与 4 个剧本实际的 nation id 并不对应；要么删掉，要么真正用作 nation id 校验。

**[main.py:78-83] low — `/api/ask` 的 `question` 与 `top_k` 无上界**
`AskRequest.question: str` 不限长（可传 1MB 文本进 LLM prompt），`top_k` 无上限。建议 `question: str = Field(max_length=500)`、`top_k: int = Field(ge=1, le=10)`。`WorldCommand.question` 同理。

### 2.4 前端 — NarratorPanel.vue（旁白/打字机）

**[NarratorPanel.vue:34-45] high — stale 旁白竞态：11-08 的修复不彻底，仍可复现**
11-08 提交（6f3a3ec）修的是"同幕号换剧本不刷新 + 首挂载不拉取"（watch 改为 `[eventId, stepId]` + onMounted），但**乱序响应竞态仍在**：`fetchNarration` 里 `await fetchNarration(...)` 之后没有任何"我是否还是最新请求"的检查。快速连点时间轴：step1 请求 A 在途（LLM 开启时超时 12s），切到 step2 发请求 B；若 A 后返回，A 的 `typeOut` 拿到更大的 token，**把 step2 的旁白整体覆盖成 step1 的旧文案**。`typeToken` 只能取消"正在打字"的旧任务，无法丢弃"晚到的旧响应"。
修复（约 3 行）：
```js
let fetchToken = 0
async function fetchNarration() {
  if (!props.eventId || !props.stepId) return
  const my = ++fetchToken
  const mod = await import('../api.js')
  try {
    const n = await mod.fetchNarration(props.eventId, props.stepId, 'immersive')
    if (my !== fetchToken) return          // 已被更新的请求取代，丢弃
    await typeOut(n.text, 14)
  } catch { if (my === fetchToken) { /* 原错误处理 */ } }
}
```
`submit()` 的问答路径同理（连续提问时 `answers.value[len-1]` 会覆盖错条目），建议同样加 token。

### 2.5 前端 — App.vue / WorldModelPanel.vue / api.js

**[App.vue:76-81] 409 前端解析验证：已修 ✓（遗留一处小脆弱）**
`/\{.*\}/s.exec(e.message)` 取首 `{` 到尾 `}` 再 `parsed?.detail?.message`，与 FastAPI 的 `{"detail":{"reason","message"}}` 包装匹配，test_simulate_endpoint_409 覆盖了后端半边。遗留：更稳的做法是让 api.js 在 `request()` 里直接 `resp.json()` 解析 detail 后挂在 `err.detail` 上，而不是靠字符串考古。建议重构为后者。

**[App.vue:102-111] medium — 假想态与自动播放互相踩踏**
进入交互推演面板时若 `playing=true`，9 秒后 `scheduleNext` 的定时器仍会触发 `goToStep` → 清空 `hypStep`，用户正在端详的假想局面被无声切走。`enterWorldModel()` 没有暂停播放。建议 `enterWorldModel` 里 `playing.value=false; clearTimeout(playTimer)`，或在 `goToStep` 中检测 `wmActive` 时先弹确认。

**[App.vue:139] low — "播放"续播假设 step id 连续**
`if (currentStepId.value >= steps[steps.length-1].id) goToStep(1)` 以及 StepTimeline 的 next（`find(x => x.id === currentStepId + 1)`）都依赖 id 连续（当前 4 剧本都是 1..6，成立）。加一个后端数据测试"step id 必须为 1..N 连续"防患（见测试盲区）。

**[api.js:1] low — `const BASE = import.meta.env.DEV ? '' : ''` 双分支都是空串**
死代码；生产构建下前端必须与后端同源部署否则 404。要么删掉表达式，要么接 `import.meta.env.VITE_API_BASE`。

### 2.6 前端 — SandboxEngine.js（Three.js 沙盘）

**★ 核心待办：3D 古地名标签未渲染 — 根因确认**

数据链路完整：4 个剧本 JSON 均含 `label` 字段（赤壁 19 处：长江/汉水/襄阳/江陵/夏口/柴桑/樊城/乌林/赤壁/华容道…；丝路含葱岭/敦煌/龟兹…），Pydantic `Terrain.label`（models.py:46）下发，`test_terrain_served_by_api`（test_backend.py:310-319）已验证 API 完整传输。

根因（SandboxEngine.js）：
- `_buildTerrain` 245-269 行：把每个带 label 的地形收集进 `this._terrainLabels`（261-267 行，含 text/pos/type/note）；
- `_buildContinents` 222-234 行：把 18 个地标收集进 `this._landmarks`；
- **全仓 grep 确认：这两个数组以及 actors/markers/arrows 上设置的 `userData.label`（692/718/765/807 行）从未被任何渲染代码消费。** 引擎里不存在 CSS2DRenderer、不存在 Sprite/CanvasTexture、不存在 DOM 投影层——`_tick` 只做补间/脉冲/渲染。数据被收集后即沉没，这就是古地名不显示的完整原因（不是 z-order/被地形遮挡/坐标错位——是根本没有绘制调用）。

**修复设计（推荐：CanvasTexture Sprite，引擎内闭环，约 60 行）**

1. 新增 `this._labelGroup = new THREE.Group()`，加入 scene（与 `_terrainGroup` 并列）。
2. 新增标签工厂：
```js
function makeTextSprite(text, { color = '#f0e6c8', fontSize = 42 } = {}) {
  const pad = 12
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.font = `${fontSize}px "PingFang SC", "Microsoft YaHei", serif`
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2
  canvas.width = w; canvas.height = fontSize + pad * 2
  const c2 = canvas.getContext('2d')           // resize 后 ctx 重置，需重设 font
  c2.font = ctx.font
  c2.textBaseline = 'middle'; c2.textAlign = 'center'
  c2.strokeStyle = 'rgba(11,16,32,0.9)'; c2.lineWidth = 6   // 深色描边保证在亮色地形上可读
  c2.strokeText(text, canvas.width / 2, canvas.height / 2)
  c2.fillStyle = color
  c2.fillText(text, canvas.width / 2, canvas.height / 2)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  const s = 0.045                                    // 世界单位/像素
  sprite.scale.set(canvas.width * s, canvas.height * s, 1)
  sprite.renderOrder = 10
  return sprite
}
```
3. 在 `_buildTerrain` 261 行处改为真正创建 sprite 并 `_labelGroup.add(sprite)`：
   - 锚点修正：折线类（mountain/river）当前取 `t.points[0]`（河流=源头，长江标签会落在四川方向），应取 `points[Math.floor(points.length/2)]`；点状类（city/fort/forest/desert/wasteland）维持 `[0]`。
   - 按类型抬高 y：mountain `y = 3.6 * size + 1`（雪顶之上），city/fort `y = 2.2 * size`（楼阁/敌楼之上），forest/desert/wasteland `y = 1.6`。
   - 按类型配色：河流 `#7fb8e8`、山 `#d8c9a3`、城/要塞 `#f1c40f`（呼应 Accent），note 可留作后续 tooltip。
4. `_landmarks` 同样生成 sprite（世界尺度剧本才有意义；region/country 剧本可与 `event.map.scale === 'world'` 判断联动显隐，避免与地形标签重叠）。
5. `_tick` 中按相机距离做淡出与避让（可选优化，首版可不做）：`sprite.material.opacity = clamp(1.6 - dist/400, 0, 0.95)`，远景自动隐藏防止 19 个标签糊成一团。
6. `setScenario`/`dispose` 清理：`_clearGroup(this._labelGroup)` 时**必须补 `m.map?.dispose?.()`**——当前 `_clearGroup`（813-823 行）只 dispose material 不 dispose texture，不补会每次换剧本泄漏一批 CanvasTexture。
7. 为 actors/markers 的 `userData.label` 顺手补一个 hover tooltip（`_onPointerUp` 已有 raycast 骨架，加 `pointermove` 命中即显示 DOM tooltip），棋子名称与假想战场名即可同时解决。

### 2.7 前端 — cameraRig.js / worldGeo.js

**[cameraRig.js:20-23, SandboxEngine.js:84] medium — 事件监听器泄漏**
`CameraRig` 在 `window` 上挂 pointermove/pointerup，`SandboxEngine` 在 `window` 上挂 resize，`dispose()`（SandboxEngine.js:881-885）只 cancel RAF 和移除 dom，两个 window 监听器永久残留。SPA 内多次进入/退出该页面会累积监听器并引用已 dispose 的 renderer。建议构造时保存 bound handler，`dispose()` 中 `removeEventListener`；CameraRig 增加 `dispose()` 由引擎调用。

**[SandboxEngine.js:652-656] low — 棋子移除不释放 GPU 资源**
`applyStep` 中消失的棋子只 `remove` 不 dispose geometry/material（_fxGroup 走 `_clearGroup` 有 dispose，_actorGroup 的逐个移除没有）。换幕频繁时累积泄漏。建议抽出 `_disposeObject(entry.mesh)` 复用。

**[SandboxEngine.js:105] low — `setSelected` 用 `geometry.type === 'CylinderGeometry' && y < 0` 魔法识别底盘**
若未来棋子加别的圆柱件会误染。建议在底盘 mesh 上显式 `base.userData.isBase = true`。

### 2.8 数据 — 4 剧本 JSON

- 赤壁：19 处地形、7 类齐全、step 1..6 连续，三势力 we/shu/wu 齐全，schema 校验测试全过 ✓
- 丝路 1023 行增量、大航海、二战欧洲均含 label 与多幕箭头；step id 均为 1..6 连续 ✓
- **[data] low**：赤壁的 `"type": "desert"` 用于"江心沙洲"、`"wasteland"` 用于"云梦泽"，属对 TerrainType 的语义借用（注释里 desert=沙漠），渲染成沙色圆盘而非沙洲/沼泽意象，教学上可能引起误解；可考虑扩展 `shoal`/`marsh` 类型或在 note 中说明。

### 2.9 测试盲区

- **前端 0 测试**：14 个文件（含 887 行的 SandboxEngine 与全部状态编排）无任何 vitest/组件/渲染测试。古地名标签这类"数据到了引擎但没人画"的回归，恰好落在这个盲区。
- **LLM 路径 0 测试**：`_llm_chat`/`_llm_hypothetical` 无 mock 测试。2.1 节的 500 崩溃、markdown 围栏静默降级都在此盲区。建议用 `respx`/monkeypatch httpx mock 三种返回：正常 dict、围栏 JSON、非 dict。
- **乱序响应无测试**：NarratorPanel 竞态需前端测试基建（fake timers + 可控 promise resolve 顺序）。
- **数据约束缺一条**：建议加 `assert [s.id for s in ev.steps] == list(range(1, len(ev.steps)+1))`（App.vue 播放/下一幕逻辑依赖连续 id）。
- **pytest 配置脆弱（low）**：pytest.ini 写 `asyncio_mode = auto`（pytest-asyncio 风格），而测试标的是 `@pytest.mark.anyio`（anyio 插件）；requirements.txt 里没有 pytest/pytest-asyncio/anyio。当前能跑通依赖环境恰好同时装了两套插件，换 CI 环境易碎。建议明确二选一并写入 requirements（推荐纯 anyio：删掉 `asyncio_mode` 行）。

---

## 三、已知修复/待办核实结论

| 项 | 状态 |
|---|---|
| 409 结构化解析（单阵营 attack 无敌人） | **已彻底修复**：world_model.py:127-132 抛 CommandUnavailable → main.py:101 转 409 → App.vue:76-81 解析 detail.message → test_backend.py:255 全链路覆盖。唯一建议：解析逻辑上收到 api.js。 |
| 旁白 stale（同幕号换剧本不刷新/首挂载不拉取） | **已修**（watch `[eventId, stepId]` + onMounted）✓；**但乱序响应竞态仍在**（见 2.4，high），需补 fetchToken。 |
| **3D 古地名标签未渲染** | **确认未实现**：label 数据从 JSON→Pydantic→API→`_terrainLabels`/`_landmarks` 全链路就绪，引擎中不存在任何消费这两数组的绘制代码。修复设计见 2.6（Sprite 方案，含河流锚点取中点、类型化抬升/配色、texture dispose、距离淡出）。 |

---

## 四、总体评价 + 优先改进 Top 3

**总体评价**：这是一个结构清晰、教育语义严谨的小型全栈项目。后端"规则引擎保底 + LLM 增强 + 永不断服"的分层设计与"史实/假想严格区分"（900 哨兵 id、✦ 徽标、日期后缀）做得相当克制且自洽；中文滑窗分词和种子化战斗结算虽简单但有测试锚定。短板集中在三处：前端渲染层是全仓唯一"零测试 + 有已确认功能缺失"的模块；LLM 输出的防御性校验只做了一半（world_model 分支既会 500 又会静默降级）；旁白竞态修复不彻底。数据质量（4 剧本 6 幕 + 19 处古地名标注）明显高于代码对它的利用程度——标签数据早已备好，只差最后一跳的渲染实现。

**优先改进 Top 3**：

1. **实现 3D 古地名标签渲染（high，用户可直接感知的教学核心功能缺失）**——按 2.6 设计：`makeTextSprite` + `_labelGroup`，河流/山脉锚点取折线中点、城/要塞按类型抬高与配色，同步修 `_clearGroup` 补 `map.dispose()`，`_tick` 加距离淡出。约 60-80 行即可点亮 4 个剧本共 60+ 处已备好的古地名。
2. **封死 LLM 输出的两条失控路径（high）**——world_model.py:331 后加 `isinstance(data, dict)` 校验 + 剥 markdown 围栏（消 500 与静默降级）；NarratorPanel.vue 补 fetchToken 丢弃乱序响应（彻底关掉 stale 旁白）。两处都是 <10 行的修复，且都建议配 mock 测试（当前 LLM 路径零覆盖）。
3. **统一推演分支语义并补前端最小测试基建（medium）**——先决策"连续命令是否累积"（2.1 状态机问题），然后引入 vitest：至少覆盖 App.vue 的播放状态机、NarratorPanel 竞态（fake timers）、SandboxEngine 的 `lonLatToWorld`/`_buildTerrain` 标签收集（防古地名回归）；顺手清掉 window 监听器泄漏与 `seed=0`、`BASE` 死代码等 low 项。
