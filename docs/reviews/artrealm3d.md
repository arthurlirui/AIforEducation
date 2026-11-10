# ArtRealm3D 代码审阅报告（2026-11-09）

全部 14 个后端 py + 12 个前端文件均已逐行阅读；关键疑点（stroke 纹理 no-op、缓存 stale、历史修复）均通过实际运行代码或比对产物验证。以下只列**读码/实测确认**的问题。

---

## 一、模块结构

| 模块 | 文件 | 职责（一行） |
|---|---|---|
| 应用入口 | `backend/app/main.py` | FastAPI 工厂：CORS、路由注册、挂载静态图层目录 |
| 配置 | `backend/app/config.py` | 路径/CORS 等设置，环境变量可覆盖 |
| 数据层 | `backend/app/data/masterpieces.py` | 三幅名画的知识库：元数据/图层处方/章节/测验（纯 dict） |
| 渲染器 | `backend/app/services/renderer.py` | numpy+PIL 程序化绘制各图层 PNG（确定性输出） |
| 资产管线 | `backend/app/services/assets.py` | 按签名缓存图层 PNG 到磁盘，产出 manifest 与 URL |
| API 路由 | `backend/app/routers/masterpieces.py` | 目录/详情/测验判分三个端点 |
| Schema | `backend/app/schemas.py` | Pydantic 响应模型（大半未使用，见后） |
| 测试 | `backend/tests/test_backend.py` | 22 个后端测试（数据/渲染/资产/API） |
| 3D 引擎 | `frontend/src/three/PaintingScene.js` | Three.js 分层视差场景：加载、呼吸动画、章节镜头、dispose |
| 导览页 | `frontend/src/views/Tour.vue` | 章节计时器、字幕卡、语音朗读、进度条 |
| 测验页 | `frontend/src/views/Quiz.vue` | 答题、交卷、判分结果展示 |
| 目录页 | `frontend/src/views/Home.vue` | 名画卡片目录 + 悬停 3D 倾斜预览 |
| API 客户端 | `frontend/src/api/index.js` | axios 封装（3 个接口） |
| 路由/入口 | `frontend/src/router/index.js`, `main.js`, `App.vue` | Vue Router 三路由 + 应用挂载 |

---

## 二、后端审阅

### 2.1 缓存层（services/assets.py）—— 本项目最高优先级问题

**[HIGH] 缓存签名不含渲染代码版本，代码更新后返回 stale 图层**
- 位置：`backend/app/services/assets.py:14-17`
```python
def _layer_sig(mid: str) -> str:
    m = get_masterpiece(mid)
    blob = json.dumps(m["layers"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{mid}:{blob}".encode()).hexdigest()[:16]
```
- 确认：签名输入只有 `mid` + 图层处方 JSON。`renderer.py` 虽被 import，但其**代码内容不参与签名**。任何对渲染器（含 `BLACK_ALPHA_THRESHOLD`、各 `_xxx` 绘制函数、`W/H`）的修改后，sig 不变 → `ensure_assets` 命中旧 manifest → 继续下发旧 PNG。URL 不变也意味着浏览器端 ETag/Last-Modified 缓存（Starlette StaticFiles 按 mtime+size 生成，文件根本不会被重写）同样无法失效。
- **实证**：2026-11 的"星夜黑方块"修复后，磁盘上 `starry-night/2b218c3d94cf1d7d/sky.png` 与修复后代码的重新渲染结果**完全一致**——说明当时是有人手动删除缓存目录才让修复生效的。这正是缺失代码签名所迫的人工操作；下一次改渲染器若忘了手动清缓存，修复将静默失效。
- **修复设计（具体）**：对渲染器源码做内容哈希并纳入签名：
```python
# assets.py 顶部
import hashlib, shutil
from pathlib import Path
from . import renderer

def _renderer_code_sig() -> str:
    """哈希渲染器源码：任何代码改动都会轮换缓存签名。"""
    try:
        src = Path(renderer.__file__).read_bytes()
    except (OSError, TypeError):   # frozen/zipapp 部署的兜底
        src = getattr(renderer, "FALLBACK_VERSION", "0").encode()
    return hashlib.sha256(src).hexdigest()[:12]

_RENDERER_SIG = _renderer_code_sig()   # import 时算一次，多 worker 结果一致

def _layer_sig(mid: str) -> str:
    m = get_masterpiece(mid)
    blob = json.dumps(m["layers"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{mid}:{_RENDERER_SIG}:{blob}".encode()).hexdigest()[:16]
```
  - 为什么足够：渲染是确定性的（`test_deterministic` 通过），PNG 字节完全由「renderer.py 代码 + 图层处方」决定；处方已在 sig 中，补上代码哈希即完整覆盖。
  - 为什么顺带解决 ETag 问题：sig 嵌在 URL 里（`assets.py:54`），代码一变 URL 即变，浏览器/CDN 拿到新 URL 自然绕开旧缓存；不需要动 StaticFiles。
  - 简单替代方案：在 renderer.py 放 `RENDERER_VERSION = "2"` 常量并入 sig——可行但依赖人工 bump，文件哈希更稳。
  - **配套改动 1（清理旧签名目录）**：`assets.py:30-31` 之后加：
```python
parent = settings.output_dir / mid
if parent.exists():
    for old in parent.iterdir():
        if old.is_dir() and old.name != sig:
            shutil.rmtree(old, ignore_errors=True)
```
  避免每次代码改动都遗留一套永不删除的旧 PNG（当前无任何 GC 机制）。
  - **配套改动 2（回归测试）**：monkeypatch `assets._RENDERER_SIG` 后断言 `ensure_assets` 落在新目录、URL 变化。

**[LOW] 冷缓存并发写非原子**
- 位置：`assets.py:44-57`。两个并发请求在缓存缺失时都会全量渲染并 `write_bytes` 直接写目标文件；静态 GET 理论上可读到写了一半的 PNG。渲染确定性使重复写入字节相同，风险低，但建议写 `fname + ".tmp"` 再 `os.replace`，并可为同一 mid 加进程内锁省一次重复渲染。

**[LOW] 死代码**：`assets.py:65-70` `chapter_scene` 无人调用，且 docstring 声称 "enriched with camera focus targets" 实际只原样返回 chapters。建议删除。

### 2.2 渲染器（services/renderer.py）

**[MEDIUM] `_stroke_texture` 是彻底的 no-op（已实测证实）**
- 位置：`backend/app/services/renderer.py:70-87`
```python
overlay = arr.copy()
...
dr = ImageDraw.Draw(Image.fromarray(overlay.astype(np.uint8), "RGB"))  # 画在临时副本上
for ...: dr.line(...)                                                   # 笔触画进这个临时图
overlay = np.asarray(Image.fromarray(overlay.astype(np.uint8), "RGB"))  # ← 却从「未被动过的 numpy overlay」重新读回
out = arr * (1 - strength) + overlay * strength
```
  第 80 行的 `astype()` 是拷贝，笔触画进的是那个临时 PIL 图；第 85 行又从原始 `overlay` 数组重新转图读回——**所有笔触被丢弃**。实测（Pillow 12.2.0）：`_stroke_texture(img, 0.30, seed=5)` 输出与输入逐位相同（`max diff: 0`）。即所有图层的"笔触质感"从未生效，README 宣传的 painted feel 实际不存在；同时 `render_layers_sorted` 的 docstring（第 441-443 行）声称 `BLACK_ALPHA_THRESHOLD=12` "tolerates the stroke-texture noise"——这个 noise 根本不存在。
- **修复（带重要警告）**：
```python
def _stroke_texture(img, strength=0.12, seed=3):
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32)
    overlay_img = img.copy()          # 唯一的绘制载体
    dr = ImageDraw.Draw(overlay_img)
    for x, y, ln, a in zip(xs, ys, lens, angs):
        ...
        dr.line(...)
    overlay = np.asarray(overlay_img).astype(np.float32)
    out = arr * (1 - strength) + overlay * strength
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
```
  **警告：不能只做这一步。** 前景层在黑底上取色 `arr[y,x] + N(0,18)`，黑底处笔触颜色常达 30-54，远超 `BLACK_ALPHA_THRESHOLD=12`（renderer.py:446），一旦笔触真实生效，前景层会出现大量本应透明却变不透明的暗色斑点（相当于重新引入"黑方块"级别的回归）。正确修法必须**只在基图有内容的像素上落笔**，例如 `if arr[y, x].max() < 24: continue`，或对 stroke 前后 alpha 做按位与。修完后务必跑全量渲染测试并人工核对三幅画。

**[LOW] 死代码与写法问题**
- `renderer.py:39-52` `_gradient_horizontal` 全项目无人调用；第 51 行 `... if False else ...` 是恒走 else 的死分支（恰好选中了形状正确的那支）。建议删除整个函数。
- `renderer.py:16` `import colorsys` 未使用。
- `renderer.py:456-459` `a = np.asarray(rgba)` 后就地改 `a[..., 3]`：该数组与 PIL readonly 图像共享缓冲，就地写虽当前可工作但脆弱，建议 `np.asarray(rgba).copy()`。

### 2.3 数据层与 API（data/masterpieces.py, routers/）

**[LOW] schemas 死代码**：`schemas.py:22-43` 的 `ChapterFocus/Chapter/QuizQuestion/MasterpieceDetail` 均未挂到任何路由（详情端点未设 `response_model`）。要么给 `api_get_masterpiece` 挂上 `MasterpieceDetail`（顺带获得响应文档与校验），要么删除。

**安全审查结论（无 critical）**：
- **路径穿越：安全。** `routers/masterpieces.py:20` 先经 `get_masterpiece` 字典查找，`mid` 只能是三个白名单 id；`ensure_assets` 拼路径（`assets.py:30`）仅在命中后才执行。`fname` 来自数据文件中的 role。StaticFiles 只挂载 `data/generated`（`main.py:31-35`）。
- **静态暴露：安全。** 磁盘上的 `manifest.json` 不含 `layer_dir`（该字段仅在返回值内存中追加，`assets.py:60`；已读盘上 manifest 确认）。API 只回传 `layers` 列表（`routers/masterpieces.py:25`），不泄服务器绝对路径。
- **CORS**：`main.py:19-25` `allow_credentials=True` + 固定 origin 白名单，开发场景可接受。
- **[LOW] 测验答案的可绕过性**：GET 详情已剥离 answer/explain（见下节），但任何人可直接 `POST /quiz` 用任意答案换取完整答案键。对教学演示可接受；若在意可加"每题提交后不可重试"或服务端会话，非必须。

### 2.4 测试盲区（backend/tests/test_backend.py，22 tests collected，与 README 一致）

- **[MEDIUM] quiz 防泄露修复无回归测试**：`test_detail_with_layers`（第 154-170 行）未断言 `d["quiz"]` 各项**不含** `answer/explain`。这是 2026-11 刚修的历史 bug，一旦有人改回 `{k: v for ...}` 就会静默回归。一行断言即可守住。
- **[LOW]** manifest 损坏自愈路径（`assets.py:36-42`）无测试。
- **[LOW]** 缓存失效测试缺失（会随本报告的 sig 修复一并补上）。
- **[LOW]** `test_backend.py:78` `if r["role"] in ("sky","background","sea") and r["role"] != "sea"` 双重条件令人误读，实意是"除 sea 外的背景层必须全不透明"（great-wave 海浪需要透明镂空，故意排除）——建议写成 `in ("sky", "background")` 并加注释。
- 前端零测试（见 3.4）。

---

## 三、前端审阅

### 3.1 Three.js 场景（three/PaintingScene.js）

**[MEDIUM] dispose() 不完整：backdrop 与画框资源泄漏**
- 位置：`frontend/src/three/PaintingScene.js:207-221`。`dispose` 只遍历 `this.layers`；而 `_initScene` 中创建的：
  - backdrop 平面（第 64-69 行：`PlaneGeometry(90,60)` + `MeshBasicMaterial`）
  - 画框 4 根 bar（第 72-85 行：4×`BoxGeometry` + 共享 `frameMat` MeshStandardMaterial）
  均未保存引用、未 dispose。用户每进出一次导览页就泄漏一组 GPU 几何/材质；反复切换三幅画会累积。另外建议补 `this.renderer.forceContextLoss()` 释放 WebGL 上下文。
- 修复：把 backdrop/frameGroup 存到 `this.backdropMesh`、`this.frameGroup`，dispose 中一并释放；或 `this.scene.traverse` 统一释放 geometry/material/map。

**已确认做对的部分**（历史修复验证）：
- `_loadLayers` 异步竞态（第 102-106 行）：dispose 后丢弃已加载纹理，不再向 scene 追加孤儿网格。✔
- `tex.colorSpace = THREE.SRGBColorSpace`（第 113 行）修复偏灰发白。✔
- 图层合成顺序正确：`renderOrder = 100 + depth`（第 118 行）+ `depthWrite: false` + `transparent: true`，后到前透明叠加，与后端 zdraw/alpha 语义吻合。纹理加载失败有灰色兜底材质（第 110 行）。

**[LOW] 呼吸动画帧率依赖**：`PaintingScene.js:179` `this.breathT += 0.016` 假定 60fps；144Hz 屏幕上呼吸速度快 2.4 倍。建议 `THREE.Clock` 的 delta 累加。

**[LOW] `extreme-close-up` 的珍珠取景硬编码**：`PaintingScene.js:158` `x = layer.role === 'pearl' ? 3.2 : 0` 是魔法数，换画或改平面尺寸会偏移；可接受，但建议由后端 focus 提供目标点。

### 3.2 导览交互（views/Tour.vue）

**历史修复「导览计时器」验证：已彻底修复。** `Tour.vue:50-66` 上下章均调用 `applyChapter` 后 `resumeTour()`；`resumeTour`（第 75-84 行）先 `clearInterval` 两个定时器再按**新章节**的 duration 重臂。`gotoChapter`、`startTour` 同样走此路径，无残留旧时长路径。✔

**[LOW] 暂停后继续，进度条与章节失拍**
- 位置：`Tour.vue:75-84`。`applyChapter` 会 `progress.value = 0`（第 40 行），但从"已暂停"浮层点继续只调 `resumeTour()`——章节定时器重开**完整时长**，进度条却从暂停时的旧值继续走。结果：进度条提前到 100% 后冻结在满格，而章节还在播。修复：`resumeTour` 内（或继续按钮处）重置 `progress.value = 0`。

其余确认正常：unmount 时 `stopTour` + `scene.dispose` + `stopSpeech`（第 110-113 行）；speechSynthesis 朗读有开关与 cancel；数据加载失败有错误面板。

### 3.3 测验交互（views/Quiz.vue）

**历史修复「quiz 答案泄露」验证：已彻底修复。**
- 后端：`routers/masterpieces.py:28-31` 从 GET 详情剥离 `answer/explain`（schema 层无泄露，因为详情端点未用含答案的 response_model）。
- 前端：`Quiz.vue:91-97` 正确答案与解析只从 POST 判分结果的 `result.per_question` 读取，devtools 的详情响应里已无答案。✔
- 遗留：缺回归测试（见 2.4）。

### 3.4 其余前端（Home.vue / api / router / vite.config）

- `Home.vue`：无问题。卡片 tilt 每次 mousemove 读 `getBoundingClientRect`，3 张卡片规模下可接受。
- `api/index.js`：干净；20s 超时对首次冷渲染（同步渲染在 FastAPI 线程池执行，不阻塞事件循环）足够。
- `vite.config.js`：`/api` 与 `/static` 代理到 8300，与后端一致。
- **[LOW] 前端零测试**：Tour 的计时器逻辑（历史 bug 高发区）内嵌在组件里难以单测。建议把"当前章+计时+进度"抽成 `useTourTimeline(chapters)` composable，用 vitest 对"切章重臂、暂停恢复、末章转跳"做纯逻辑测试——这正是上次翻车的区域。

---

## 四、历史修复验证汇总

| 项 | 结论 |
|---|---|
| 导览计时器 bug | **已彻底修复**（Tour.vue:50-84 全部换章路径均重臂定时器）；残留一个低危进度条失拍小问题 |
| 星夜黑方块（前景 alpha/halo） | **已彻底修复**（renderer.py:121、402 均以 halo 自身为 mask 粘贴；实测磁盘缓存与修复后重渲染逐位一致）——但该次修复靠**手动清缓存**生效，正是缓存签名缺陷的直接后果 |
| quiz 答案泄露 | **已彻底修复**（router 剥离 + 前端只读判分结果）；缺回归测试 |
| **缓存签名不含代码版本（待办）** | **确认存在，位于 assets.py:14-17**，修复设计见 2.1 |

---

## 五、总体评价 + 优先改进 Top 3

**总体评价**：小而完整的教学项目，架构清晰（处方 → 确定性渲染 → 内容寻址缓存 → 3D 合成），历史修复质量高且都留了注释说明因果；安全面（路径、静态暴露、答案泄露）现状良好。主要短板集中在两点：缓存签名只覆盖数据不覆盖代码（已知待办，已被黑方块修复事件实证其危害）；以及一个**静默失效的核心视觉特性**（stroke 纹理 no-op）暴露出渲染层缺视觉回归手段。

**Top 3 优先改进**：

1. **落地缓存代码签名（HIGH）** — 按 2.1 设计：`_renderer_code_sig()` 哈希 renderer.py 源码并入 `_layer_sig`，附带旧签名目录 GC、原子写入与"改代码必换目录"的回归测试。这是唯一一个已经实际造成过"修复不生效"的问题。
2. **修 `_stroke_texture` no-op，但必须连同 alpha 阈值一起修（MEDIUM）** — 按实测算，直接让笔触生效会在前景层引入超过 `BLACK_ALPHA_THRESHOLD=12` 的暗色斑点，重演黑方块级回归；修复必须限制笔触只落在基图有内容的像素上，并以三幅画的全量人工比对 + 更新 renderer.py:441 的注释收尾。
3. **补齐 PaintingScene.dispose() + 关键回归测试（MEDIUM）** — dispose 释放 backdrop/画框几何与材质并 `forceContextLoss()`；同时为"quiz 详情不含答案"补一行断言、把 Tour 计时器抽成可单测的 composable。这三件事共同把已有的历史修复从"靠人记住"变成"靠测试守住"。
