# TechLearnStudio 代码审阅报告（2026-11-09）

审阅范围：全部 37 个 py + 5 个前端源文件 + 全部测试 + 配置 + 设计稿对照（`docs/modules/techlearnstudio.md`）。所有发现均经实际读码确认。

---

## 一、模块结构与实现状态

### Backend（仓库，FastAPI 长驻）

| 模块 | 职责（一行） | 状态 |
|---|---|---|
| `backend/app/main.py` | FastAPI 入口 + CORS + /static 挂载 | ✅ |
| `backend/app/config.py` | TLS_ 前缀环境配置 | ✅ |
| `backend/app/db.py` | SQLite/SQLModel engine + CRUD 助手 | ✅ |
| `backend/app/models.py` | Course/Frame/Source/VersionDelta 四模型 | ⚠️ Source/VersionDelta 定义后**从未被任何代码读写** |
| `routers/courses.py` | 公开读 API（列表/详情/帧） | ✅（draft 可被公开读取，见 B8） |
| `routers/admin.py` | X-Admin-Token 鉴权的写 API（推送/上下架/删除） | ✅ |
| `routers/sandbox.py` | POST /api/sandbox/run 代码执行入口 | ⚠️ 端点在，**执行为 stub** |
| `routers/search.py` | 内存标题子串搜索 | ✅（M8 占位，README 已声明） |
| `routers/anim.py` | 动画渲染代理（转发到 studio.anim_gen） | ⚠️ 运行时 sys.path 注入耦合 studio 源码 |
| `routers/health.py` | 健康检查 | ✅ |
| 设计稿 §4b.2 `routers/sources.py`（GET /api/sources） | 内容源元信息 | ❌ 未实现 |
| 设计稿 §4b.5 `auto_publish.py`（Backend 定时发布 draft） | 定时自动上新 | ❌ 未实现（被 Studio 直接 publish 替代，语义偏离设计） |
| 设计稿 §4b.4 Sandbox（Pyodide/Docker） | 在线运行代码 | ❌ **未实现**（`sandbox/runner.py` 纯回显） |
| 设计稿 §4b.3 静态课件落盘托管 | 推送时把 HTML/SVG/mp4 落盘 /static/courses/{id}/ | ❌ 未实现（只挂载了空目录 `app/static/`，推送不写任何文件） |

### Studio（生产者）

| 模块 | 职责（一行） | 状态 |
|---|---|---|
| `crawler/sources.py` | 7 个内容源 adapter（fetch/fingerprint/parse） | ⚠️ 全部离线硬编码，真实抓取（sitemap/PDF）未实现；且 **parse() 完全忽略 fetch() 的内容** |
| 设计稿 §4a.1 步骤2 `topics/`（TopicDiscover，LLM 搜新 topic） | 候选 topic 发现与去重 | ❌ 未实现（`studio/topics/` 空目录） |
| `composer/pipeline.py` | 规则模板合成 frames + LLM 增强 | ⚠️ 已实现但**无 schema 校验、无 QA 跑通门**（设计稿 §4a.3 承诺的 Pydantic 结构化校验不存在） |
| `composer/samples.py` | 内置 3 节示例课程 | ✅ |
| `anim_gen/generator.py` | SVG/SMIL 参数化动画模板（替代 Motion Canvas） | ✅ 4/7 模板（channel_response/gradient_descent/tree_traversal 缺） |
| 设计稿 §4a.4 `anim_render/`（MC CLI 渲染 + mp4 SHA-256 缓存 + live 模式） | 动画渲染服务 | ❌ 未实现（仅空 `project_template/` 目录） |
| `llm/client.py` | OpenAI/智谱/Pollinations 多 provider 回退 | ✅（`available` 语义有瑕疵，见 S3） |
| `publish/client.py` | 推送 + 发布到 Backend admin API | ✅ |
| `scheduler/scheduler.py` | run_once 巡检（fetch→diff→compose→publish）+ APScheduler cron | ✅（状态内存态不持久化，见 S9） |

### Frontend（消费者）

| 模块 | 职责（一行） | 状态 |
|---|---|---|
| `src/App.vue` | 课程库 + 播放器 Vue 壳（动态 CDN 加载 reveal.js） | ✅（KaTeX/Monaco 缺，见 F1/F2） |
| `src/plugin/hyperframes.js` | frames→`<section>` 渲染 + 跨帧链接 + sandbox 按钮 + MC 挂载 | ⚠️ 已实现（JS 而非设计稿的 TS），**HTML 转义不完整**（见 B1） |
| 设计稿 §5.1 Pinia/stores/views/TypeScript | 状态管理与多视图 | ❌ 未实现（单 App.vue） |
| 设计稿 §5.4 Motion Canvas Player（video/live） | 原理动画播放 | ❌ 未实现（仅内嵌 fallbackSvg 静态 SVG） |
| 设计稿 M8：学习路径/进度持久化/暗色切换/搜索升级 | 打磨 | ❌ 未实现（README 已声明） |
| reveal.js/highlight 本地化（npm 依赖） | 离线播放 | ❌ 仍 CDN（README 已声明） |

### 测试

`tests/test_e2e.py`（真实 uvicorn 子进程，2 项）、`backend/tests`（8 项）、`studio/tests`（36 项）、`frontend/tests/run-tests.mjs`（纯函数，独立于 pytest）。pytest 合计 46 项。

---

## 二、Sandbox 安全（任务重点）

**结论：当前不存在任意代码执行风险——因为根本不执行任何代码。**

- `backend/app/sandbox/runner.py:21-27`：`run()` 只回显 `[sandbox stub] {lang} code received`，无 exec/subprocess/docker 调用。全仓 grep 无 `exec(`、`subprocess`、`docker`、`pyodide` 执行路径。
- **critical（产品缺口，非漏洞）**：`runner.py:1-5` — sandbox 是平台核心卖点（设计稿 §4b.4、README"主要待办 1"），目前完全未实现。前端"▶ 运行"按钮（`hyperframes.js:38`）发出的请求只会得到回显文案，用户体验是假运行。
- **medium**：`backend/app/routers/sandbox.py:25-29` — 端点公开无鉴权、`RunRequest.code` 无长度上限、无速率限制。Starlette/uvicorn 默认不限请求体大小，现在即可用超大 body 打内存（DoS 面）；更重要的是**在接入真实执行器之前必须先补边界**，否则未来一次提交就把无鉴权 RCE 上线。建议：
  1. 按设计稿 §4b.4 把 Python/TS 放**浏览器侧 Pyodide**（iframe `sandbox` 属性 + CSP，代码根本不出浏览器），后端只保留 Go/Rust 的 Docker 通道；
  2. Docker 侧硬约束：`--network none`、`--read-only` + tmpfs、非 root 用户、`--memory/--cpus` rlimit、pids-limit、seccomp 默认 profile、短超时 + 硬 kill；
  3. 先加请求体上限（如 64KB）与每 IP 速率限制，再谈执行。

---

## 三、分模块审阅发现

### 3.1 Backend

**B1. high — LLM/推送内容到前端的存储型 XSS 链（多条向量，均已确认）**
这是全项目最完整的安全链条：内容源 = LLM 输出（不可信）或 admin 推送的 `blocks_json`（自由字符串，`admin.py:23` 不做任何校验），前端用 `v-html`（`App.vue:40`）渲染：
- `frontend/src/plugin/hyperframes.js:19-29` `renderText()` — `block.md` **完全不转义**直接进 HTML（其它 block 类型都转义了，唯独正文不转义）。`md: "<img src=x onerror=alert(1)>"` 即注入。
- `hyperframes.js:15-17` `escapeHtml()` 只转义 `& < >`，**不转义引号**，但被大量用于双引号属性上下文：`data-tex`(:46)、`data-why`(:79)、`data-frame-link`(:88)、`data-mc-block`(:64)。`tex: '" onmouseover="alert(1)'` 即可逃逸属性。
- `hyperframes.js:36` `data-lang="${lang}"`、`:79` `data-answer="${block.answer}"` — **完全未转义**的属性插值。
- `hyperframes.js:65` `fallbackSvg` 原样注入（motionCanvas block 的 `fallbackSvg` 是任意字符串）；`:178` 把 `/api/anim/render` 响应 `data.content` 直接 `innerHTML`（配合 S6 的参数注入）。
建议：`escapeHtml` 补 `"`/`'` 转义；`renderText` 走真 markdown 渲染器（marked + DOMPurify）；`fallbackSvg`/anim 响应按 `image/svg+xml` 严格解析后白名单挂载，或整块放 `<img src=data:...>` / 沙箱 iframe。

**B2. medium — 版本号增量是"假的"，frame 级 diff 未实现**
- `backend/app/routers/admin.py:40,61` — 每次推送**所有帧**统一 `version+1`；`db.py:109-118` `upsert_frames` 是先删后插的替换式。设计稿 §4a.5/§7 的"只对变化章节重生成、帧级 VersionDelta、`?since_version=N` 增量拉取"完全没有对应实现。
- `backend/app/models.py:37-53` — `Source` 与 `VersionDelta` 两个表定义后**零引用**（全仓 grep 确认），`Source.last_hash` 的持久化位从未被写入；`config.py:16` `auto_publish_cron` 也是从未被读取的占位。
建议：要么实现 frame 级 diff 并写 VersionDelta，要么删掉死模型和死配置，避免误导后续维护者。

**B3. medium — version 自增存在 get-then-set 竞态**
`admin.py:39-40`：`existing = db.get_course(...)` → `version = existing.version + 1` → `upsert`，无事务锁。设计稿 §4a.5 明确要求"Backend 入库时按 course_id 串行化"，未实现。两个 Studio 实例并发推送会丢一次版本号。建议：upsert 放进单事务并在 SQL 里 `version = version + 1`，或对 course_id 加进程级锁。

**B4. medium — SQLite 并发写脆弱**
`backend/app/db.py:16` — `check_same_thread=False` 但未开 WAL、未设 `timeout`。FastAPI 同步端点跑在线程池，并发写会触发 `database is locked`。建议：`connect_args={"check_same_thread": False, "timeout": 30}` + `PRAGMA journal_mode=WAL`。

**B5. low — `upsert_course` 覆盖 `created_at`**
`db.py:58-59` — `for k in course.model_fields: setattr(existing, k, ...)` 把新建 Course 的默认 `created_at`（now）也拷贝过去，每次更新都重置创建时间。建议：跳过主键与 `created_at`。

**B6. low — admin token 非常量时间比较 + 默认 token**
`admin.py:15` 用 `!=` 比较（应 `secrets.compare_digest`）；`config.py:15` 默认 `dev-admin-token`，未设 env 即可被任意人推送/删除课程。建议：生产缺 env 直接 fail-fast。

**B7. low — CORS `*` + credentials**
`config.py:14` + `main.py:20-26` — `allow_origins=["*"]` 且 `allow_credentials=True`，Starlette 会回显任意 Origin。当前无 cookie 认证影响有限，仍应收紧为显式白名单。

**B8. low — draft/archived 课程可被公开按 id 读取**
`courses.py:17-22,25-29` — 详情与帧接口不检查 status，未发布内容可被直接枚举读取。列表过滤了（`db.py:44-45`），详情没有。

**B9. low — `@app.on_event("startup")` 已弃用**（`main.py:43`），应迁移 lifespan。

### 3.2 Studio — Composer 生成管线

**S1. high — LLM 输出零校验，坏输出直接崩溃管线或炸掉前端整课渲染**
- `studio/composer/pipeline.py:180` — `steps = outline_resp["steps"][:7]`：LLM 返回 `{"steps": {...}}` → `TypeError`；返回字符串则每个字符变成一帧标题。
- `pipeline.py:195-202` — `step_title.lower()` 假设 str，非 str 直接 `AttributeError`；整个 `compose_with_llm` 循环体无 try/except。
- `pipeline.py:210-212` — `blocks = frame_resp["blocks"]` 不检查是否为 list、元素是否为 dict、type 是否已知、`fragment` 是否 int、代码 `src` 是否 str，LLM 的任意形状输出原样进 `blocks_json` 入库。前端 `hyperframes.js:113` `blocks.map(renderBlock)` 无逐块容错，一个 `null` block 抛 `TypeError` → `framesToHTML` 整体抛出 → `App.vue:96` `renderSlides` 无 catch → 播放器白屏。
- 设计稿 §4a.3 明确承诺"每步有结构化输出 schema（Pydantic 校验）"，**未实现**；设计稿 §10 的"QA 步骤强制 sandbox 跑通，失败降级"也**未实现**——`pipeline.py:95,232` 无条件给代码块标 `runnable: True`，从未跑通过任何代码（sandbox 本身是 stub）。
建议：定义 Pydantic Block/FrameSpec schema（与设计稿 §6.1 的 9 种 block 对齐），`chat_json` 结果 `model_validate`，失败逐帧降级到规则块；前端 `renderBlock` 加逐块 try/catch。

**S2. medium — anim 帧 import 依赖 sys.path 隐式约定**
`pipeline.py:103-105` `from anim_gen import generate` 依赖 `studio/` 已在 sys.path（靠 conftest/pytest.ini 摆好），作为库被独立导入会 ImportError。建议相对导入 `from ..anim_gen import ...`。

### 3.3 Studio — LLM Client

**S3. low — `available` 恒为 True，与文档语义相反**
`studio/llm/client.py:55-61,63-65` — Pollinations provider 无条件追加（api_key="dummy"），`available` 永远 True。docstring 说"无 key 且 Pollinations 不可达时 unavailable"——不成立；测试 `test_m3_llm.py:12-13` 的注释也承认了这点。后果：离线机器上 `compose_with_llm` 每帧仍要发起网络调用（每 provider 30s 超时，7 步大纲最多 8 次调用）才降级。建议：加短超时（3-5s）+ 一次探测失败后在进程内标记 provider 不可用。

**S4. low — 静默吞掉所有 provider 错误**
`client.py:90-91` — `except Exception: continue`，无日志、无重试、无区分（DNS 错/429/401）。调试时无法知道为什么降级了。建议至少 `logging.warning`。

### 3.4 Studio — anim_gen + Backend anim 端点（组合链）

**S5. high — 后端运行时 import studio 源码，破坏三模块独立部署**
`backend/app/routers/anim.py:30-35,49-54` — 请求期把 `Path(__file__)/../../../..` + `/studio` 插进 `sys.path` 再 `from anim_gen import ...`。设计稿 §3 的核心架构承诺是"三者通过 HTTP 解耦、可独立部署"，此实现使 backend 二进制必须与 studio 源码树同仓部署；路径层级 hardcoded，目录一挪就 500。建议：把 anim 模板挪进 backend（或独立服务），studio 通过 HTTP/文件推送产物。

**S6. medium — 公开端点参数无校验，可注入 SVG（接 B1 构成 XSS）+ 500 DoS**
- `studio/anim_gen/generator.py:41-42` — `_convolution_svg` 把 `params["signal"]` 的元素**未转义**插进 `<text>{v}</text>`；`POST /api/anim/render`（无鉴权）传 `{"sceneRef":"convolution","signal":["</text><img src=x onerror=alert(1)>"]}` 即返回带脚本载体的 SVG，前端 `hyperframes.js:178` innerHTML 渲染。
- `generator.py:173` `f'{w:.2f}'` — weights 传非数值直接 `ValueError` → 500；`generator.py:183` signal 传字符串时 `abs(v)` TypeError → 500。公开端点可随意打出未处理异常。
建议：参数用 Pydantic 校验（list[float]），SVG 文本节点统一转义，或该端点加 admin 鉴权 + 结果缓存。

**S7. low — `save_svg` 缓存 hash 忽略真实参数**
`generator.py:248` — `scene_hash(result.scene_ref, {})` 永远用空 params 算 hash，不同参数的渲染结果同名互相覆盖（设计稿 §4a.4 的 SHA-256 缓存语义错误）。当前调用方恰好只传 `{}`，属于埋雷。

**S8. low — `run_once` 报告状态失真**
`scheduler.py:85-88` — 不推送时 details 也记 `"status": "published"`，报告与事实不符。

### 3.5 Studio — Scheduler + Publish（cron）

**S9. medium — 巡检状态内存态，重启即全量重发，非幂等**
- `scheduler.py:35` `_states: dict` 模块级内存（注释自认"M7+ 可换 SQLite"）。进程重启 → 所有 `last_hash` 丢失 → 全部源判为"变化"→ 14 门课重推、每门 `version+1`、内容没变版本号却涨（前端"本帧基于 v3 已更新到 v4"的提示会变成狼来了）。设计稿的持久化位（`Source.last_hash` 表）已建模未使用。
- `scheduler.py:91` — `_states[sid]` 在**整源所有 section 发布成功后**才写。第 2 节发布失败 → 整个源状态不落 → 下轮把已成功的第 1 节也重发。部分失败无断点。
- 建议：state 落 SQLite（Source 表就是为此设计的），或至少每 section 粒度记录。

**S10. medium — 并发无锁**
- 单进程内 APScheduler 默认 `max_instances=1` 能防 cron 自重叠，但 `run_now()`（`scheduler.py:144-146`）与 cron 触发可并发跑两个 `run_once`；设计稿 §4a.5 还明确支持"多实例并行生产"，跨进程完全无锁，叠加 B3 的 version 竞态。
- 建议：`run_once` 入口加文件锁/DB 乐观锁；backend 侧按 course_id 串行化（设计稿原话）。

**S11. low — 标题改名产生重复课程而非版本更新**
`scheduler.py:99-102` — `course_id = f"{sid}-{md5(title)[:8]}"`，文档小节标题一变，course_id 就变，旧课保留、新课并存，永不收敛。

**S12. low — 语义偏离设计：直接 publish 跳过 draft**
`publish/client.py:30-38` `publish_and_publish` 推完立即 publish。设计稿 §4b.5 是"Studio 推送默认 draft，Backend 定时校验后批量发布"（给人工审核留窗口）。当前实现没有任何人工闸门，LLM 生成的未验证内容（结合 S1 无 QA）直接上线。

### 3.6 Studio — Crawler

**S13. medium — fingerprint 与 parse 脱节，"自动更新"是空壳**
`crawler/sources.py:57-71`（及所有 7 个 adapter）— `parse(docs)` **完全忽略传入的 docs**，返回硬编码 Section。即 fingerprint 变化触发的"增量重生成"，重新发布的仍是同一份硬编码内容。README 声明了"内置离线内容、真实抓取留接口"，但目前的结构里接上真实 fetch 后 parse 也不会随之工作——接口形同虚设。设计稿 §4a.2 的 sitemap 抓取、PDF 讲义上传均未实现。

### 3.7 Frontend

**F1. medium — KaTeX 从未加载，公式块永远渲染不出来**
`hyperframes.js:45` 注释写"用 KaTeX CDN（App.vue 引入）"，但 `App.vue:99-125` 只加载 reveal.js/highlight/notes 三个脚本，全仓 grep 无任何 katex 引用（`index.html` 也没有）。信号与系统/无线通信/大模型三门课的 `formula` 帧只显示 explain 文本，`data-tex` 挂在没人消费的属性上。这是 M2"hyperframes 插件完整"声明的直接反例。

**F2. low — Monaco 未实现，代码不可编辑**
设计稿 §2.1"用户改代码、点运行"与 §5.1 Monaco：当前代码块是只读 `<pre><code>`（`hyperframes.js:37`），运行时取 `codeEl.textContent`（:150），用户无法修改即运行。README 未把此项列入"降级"清单。

**F3. low — 同帧多个 quiz 共享单选组**
`hyperframes.js:77` — radio `name="quiz"` 硬编码全局同名，一帧放两个测验会互相取消选择。应用 block 级唯一 name。

**F4. low — 依赖 CDN（已声明）+ 列表 markdown 不渲染**：`- item` 只会变成带 `<br>` 的纯文本（`renderText` 只处理标题/加粗/换行）。离线不可用与渲染保真度均为已知降级。

### 3.8 测试与配置（含历史修复验证）

**历史修复 1：pytest testpaths — 已彻底修复 ✅**
`pytest.ini:2` — `testpaths = tests backend/tests studio/tests`，全量收集 46 项（backend 8 + studio 36 + e2e 2）；`backend/pytest.ini`、`studio/pytest.ini` 保留供子目录独立运行。验证通过。

**历史修复 2：publish._post mock 泄漏 — 已彻底修复 ✅**
- `studio/tests/test_studio.py:25-36` 与 `studio/tests/test_m7_scheduler.py:23-34` — 均改为 `setup_module` 内保存 `_orig_publish_post`、`teardown_module` 恢复，注释准确记录了"导入期保存会误存别人装的 mock"这一原缺陷。
- e2e（`tests/test_e2e.py:39` 显式传 `e2e-token` 给子进程）不经过 in-process mock，闭环成立。顺序运行下无泄漏路径。
- 残余小风险：仍是模块级全局替换而非 pytest `monkeypatch` fixture，`pytest-xdist` 下每 worker 独立进程反而安全；若未来引入同进程并行测试框架需重构。判定：**修复彻底**。

**T1. medium — 新发现：studio/conftest.py 的"统一 DB"在全量跑时静默失效**
- `studio/conftest.py:7-11` 在收集 `studio/tests` 时才设置 `TLS_DB_PATH=_test_unified.db`，但收集顺序为 `tests → backend/tests → studio/tests`，`backend/tests/test_backend.py:11-12` 在 import 期已创建 `settings` 单例（指向 `backend/tests/_test.db`）。此后改 env 无效，studio 全部 36 项测试实际跑在 **backend 的 `_test.db`** 上（靠各自 `reinit_engine()` + 宽松断言如 `>= 14` 才碰巧全绿），`_test_unified.db` 从未被创建。
- 证据：工作区残留 `backend/tests/_test.db`（backend teardown 删掉后又被 studio 测试重建，无人清理）。
- 建议：删除误导性的 studio/conftest DB 逻辑，改为在根 conftest 统一设置 `TLS_DB_PATH`（在收集任何测试模块之前），或 backend/studio 各用 `tmp_path` fixture。

**T2. 测试盲区清单（均经确认无覆盖）**
- LLM 畸形输出：`steps` 非列表、`blocks` 非数组、block 为 `null` —— compose_with_llm 会崩（S1），无测试。
- 并发：version 竞态（B3）、scheduler 重叠运行（S10）—— 无测试。
- 幂等/恢复：scheduler 部分失败后的重发行为、进程重启丢 state（S9）—— 无测试。
- 安全：`/api/anim/render` 恶意 params（S6）、超长 code body（sandbox DoS 面）、前端转义——`run-tests.mjs:16-19` 只测了 `& < >`，引号属性注入与 `renderText` 不转义正好是测试盲区。
- draft 课程公开可读（B8）—— 无测试（现状行为即是如此）。
- e2e 不覆盖 `/api/anim/*` 端点；前端测试（`npm test`）游离于 pytest 之外，只跑 pytest 的 CI 会漏掉它。

**T3. low — README 数据漂移**：`README.md:24,62` 称"43 项（backend 9 + studio 25 + e2e 2 + 前端 1）"，实际 pytest 46 项（backend 8、studio 36），commit 信息（46 测）与 README 不一致。

**T4. low — 残留空目录**：`app/`、`app/static/`、`studio/app/static/`、`studio/data/`、`studio/topics/`、`studio/anim_render/project_template/`、根 `data/`（README 自认待清理）。

**T5. low — 依赖声明缺口**：`backend/requirements.txt` 无 apscheduler，studio 无任何依赖清单，按 README 装完依赖跑 `StudioScheduler.start()` 即 `ModuleNotFoundError`。

---

## 四、总体评价 + 优先改进 Top 3

**总体评价**：这是一个骨架诚实、测试纪律良好的 M1-M7 原型。三模块分层清晰，46 项测试含真实子进程 e2e，历史上两次测试基建修复（testpaths、mock 泄漏）都修得干净彻底，降级路径（LLM 不可用回规则模板、动画 fallback）有意识地设计了。但离设计稿的"核心卖点"还有实质距离：**sandbox 不执行、TopicDiscover 不存在、Motion Canvas 被换成了 4 个 SVG 模板、增量版本是假的（全帧 version+1 + 死模型）、爬虫 parse 与 fetch 脱节**——README 对大部分缺口有声明，但"hyperframes 插件完整"与"M7 ✅"两处声明偏乐观。安全面上，当前最大的问题不是 sandbox（它因为不执行而无风险），而是**LLM 输出 → 前端 innerHTML 的完整 XSS 链**：转义层四处漏风且恰好是测试没照到的地方。

**优先改进 Top 3**：

1. **修复前端渲染转义链（B1，工作量小、收益最大）**：`escapeHtml` 补引号 → `renderText` 接 DOMPurify → `data-answer`/`data-lang`/`fallbackSvg`/anim 响应全部收敛。这是在接入真实 LLM 之前必须堵住的洞，因为 compose_with_llm 的输出不经任何校验直达 `v-html`。
2. **给 LLM 输出加 Pydantic schema 校验 + 逐帧降级（S1）**：定义 §6.1 的 Block/FrameSpec 模型，`chat_json` 结果 validate 失败即用规则块；前端 `renderBlock` 加逐块 try/catch。没有这一层，真实 LLM 一接入，坏输出会随机炸掉合成管线或整课白屏。
3. **sandbox 落地前先画好边界（§二）**：按设计稿把 Python/TS 放浏览器侧 Pyodide（iframe sandbox，代码不出浏览器），后端只留 Go/Rust 的 Docker 通道（`--network none --read-only` 非 root + rlimit）；同时立刻给 `/api/sandbox/run` 加请求体上限与速率限制——这个无鉴权端点现在就是 DoS 面，未来接执行器时它会是无鉴权 RCE 面。

次优先：scheduler 状态落 SQLite 修幂等（S9/T2）、`anim.py` 解除对 studio 源码的运行时 import（S5）、补 apscheduler 依赖声明（T5）。
