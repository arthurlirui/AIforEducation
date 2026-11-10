# OilPaintingStudio 代码审阅报告（2026-11-09）

## 0. 模块结构总览

| 模块 | 职责（一行） |
|---|---|
| `oilpainting_studio/common/config.py` | .env + settings.yaml + styles.yaml 三层配置加载 |
| `oilpainting_studio/common/llm_client.py` | OpenAI 兼容 LLM 客户端（JSON 模式、退避重试、哨兵错误串） |
| `oilpainting_studio/common/comfy/client.py` | ComfyUI HTTP 客户端（上传→排队→轮询→拉产物，信号量限流） |
| `oilpainting_studio/common/comfy/workflows.py` | 工作流模板加载 + 按节点 id/字段路径注入参数 |
| `oilpainting_studio/common/utils/image.py` | 帧序列 → mp4 合成（cv2.VideoWriter） |
| `oilpainting_studio/common/utils/vram.py` | 显存释放（empty_cache/gc） |
| `oilpainting_studio/video/screenplay/*` | LLM 结构化剧本生成（重试回灌修正 + pydantic 校验） |
| `oilpainting_studio/video/pipeline/director.py` | 剧本→关键帧→I2V→剪辑四阶段编排与 meta 落盘 |
| `oilpainting_studio/video/pipeline/keyframe.py` / `animate.py` | SDXL img2img 油画关键帧 / LTX·Wan I2V 工作流构建 |
| `oilpainting_studio/video/pipeline/edit.py` / `ffmpeg_tool.py` | ffmpeg 归一化→concat→BGM/字幕烧录 / ffmpeg 定位封装 |
| `oilpainting_studio/video/mesh2video/*` | 3D 白膜渲染 + ComfyUI 风格化视频（独立管线） |
| `oilpainting_studio/video/audio/*` | BGM 按情绪选取 / TTS 预留空实现 |
| `oilpainting_studio/revive/_imio.py` | cv2 中文路径兼容层（imdecode/imencode） |
| `oilpainting_studio/revive/stage1/*` | YOLO 分割 + DA-V2 深度 + 控制线稿解析（均带 mock 回退） |
| `oilpainting_studio/revive/stage2/*` | TripoSplat 3DGS 生成（mock 反投影回退）+ 场景组装注册表 |
| `oilpainting_studio/revive/stage3/*` | 线稿引导 3DGS 重定位 + inpaint 补缺 + 关键帧合成 |
| `oilpainting_studio/revive/stage4/__init__.py` | 编辑场景多关键帧渲染（RGB/depth/edge 三联图） |
| `oilpainting_studio/revive/stage5/*` | ComfyUI Wan/LTX ControlNet 动画（mock 插值回退） |
| `oilpainting_studio/revive/pipeline/*` | 四模块编排 + checkpoint 续跑 + 显存释放钩子 |
| `oilpainting_studio/revive/eval.py` | 风格一致性/边缘对齐/深度忠实度评估钩子 |
| `oilpainting_studio/gui/models.py` | project.json/scene.json/Task 的 pydantic 模型 |
| `oilpainting_studio/gui/store.py` | 项目存储层（tmp+rename 原子写、undo/redo、版本翻版） |
| `oilpainting_studio/gui/tasks.py` | 单 worker 线程 GPU 串行任务队列（进度/日志/取消） |
| `oilpainting_studio/gui/adapters.py` | GUI → revive 算法适配（stage1 导入/stage2 翻版/stage5 占位） |
| `oilpainting_studio/gui/imgio.py` | GUI 侧中文路径安全 imread/imwrite |
| `oilpainting_studio/gui/api/routers.py` | 全部 REST API（projects/objects/gs/scene/keyframes/compose/tasks/undo） |
| `oilpainting_studio/gui/server.py` | FastAPI app 组装 + registry/queue 全局单例 |
| `oilpainting_studio/desktop/device.py` | 三档设备探测 + resolve_choice 回退决策 |
| `oilpainting_studio/desktop/engine.py` | 论文 demo 三步引擎（分割→深度→点云 PLY） |
| `oilpainting_studio/desktop/api.py` | /api/demo/* 路由 + 独立可测 app |
| `oilpainting_studio/desktop/__main__.py` | pywebview 桌面入口（uvicorn 8712 + 静态托管 + gui routers） |
| `gui/src/*` | Vue3 五步工作台 + Demo 页（api.js/i18n.js/three.js 封装） |

---

## 1. desktop/ 模块

**D1. `oilpainting_studio/desktop/__main__.py:42-49`（本次未提交改动）— medium — 挂载 gui routers 造成 demo GPU 推理绕过任务队列**
新增代码把 9 个 gui router 挂进桌面 app（修复了"工作台页面 404 无反应"，修复本身正确且必要：所有 router 均在 `app.mount("/", StaticFiles)` 之前注册，路由优先级正确）。但 `/api/demo/run` 是同步端点、直接在请求线程里跑 YOLO，而 gui 的 `/gs/run` 走 `TaskQueue` 串行 —— 两者共用同一块 GPU 却互不知晓。用户在 Demo 页跑推理时同时提交 TripoSplat 任务会真实竞争显存。
建议：给 demo run 也包一层轻量互斥（与 TaskQueue 共享一把 GPU 锁），或至少在 demo run 进行中让 gs 任务排队等待。

**D2. `oilpainting_studio/desktop/api.py:126-152` — medium — run_demo 并发共享引擎非线程安全**
`_get_engine` 只保证引擎创建互斥；返回后 `engine.run()` 无锁并发执行。两个并发 `/api/demo/run` 会同时使用 `self._yolo`（ultralytics 模型非线程安全）并交叉修改 `self.report.backends[...].infer_ms`（engine.py:173/191）。另外 `run_id` 精确到秒（api.py:144），同秒两次运行共用 `out_dir`，run.json 相互覆盖。
建议：`engine.run` 外加 per-engine Lock；run_id 加毫秒或 uuid 后缀。

**D3. `oilpainting_studio/desktop/device.py:184-206` — low — resolve_choice auto 语义正确，但 prefer 无校验**
已知坑验证：`"auto": report.tier` 映射已正确（auto 直接采用探测档，不再出现 auto 被解析成弱档的问题）；gpu 不可用回退 CPU/MOCK 且 reason 如实上报，测试 `test_resolve_choice_fallback_reason` 覆盖到位。但 `DemoRunRequest.prefer: str = "auto"`（api.py:123）不校验取值，`prefer="foo"` 静默按 auto 处理。建议改 `Literal["auto","gpu","cpu","mock"]`。

**D4. `oilpainting_studio/desktop/engine.py:198` — low — 点数估算误导**
`num_pts = ply 文件大小 // 60`：ASCII PLY 每行长度随坐标位数变化，除数 60 是拍的；UI 显示 "N, 点" 作为精确数字。建议解析 header 的 `element vertex` 值。

**D5. `oilpainting_studio/desktop/api.py:78-82 / 166-170` — low — 产物目录无清理**
`runs/` 与 `paintings/` 只增不减；每次 demo 落 overlay/depth/mask 多张 PNG + 全分辨率 ASCII PLY（大图可数十 MB），长期运行磁盘无限增长。建议加保留条数（如 runs 保留最近 30 个）。

**D6. `oilpainting_studio/desktop/api.py:189-190` — low（信息项）— app 定义顺序坑已修复**
`app = FastAPI()` 与 `/api/demo/health` 定义在 router 之后，`test_desktop_demo.py` 直接 `from ...desktop.api import app` 可用；已知坑确认已处理。

---

## 2. gui 后端（store / tasks / adapters / api）

**G1. `oilpainting_studio/gui/adapters.py:176-223` — high — run_compose_task 从不真正调用 ComfyUI，却上报 `comfy_used: True`**
代码只 `import ComfyClient/build_wan_workflow` 成功就把 `comfy_ok=True`（adapters.py:187-191），随后无论真假都走 10 步 sleep + 三张纯色帧占位视频，返回 `{"comfy_used": comfy_ok}`。前端 i18n 文案（`composeHint`）宣称"ComfyUI 可用时走 revive.stage5 工作流"——与实现不符：即使 ComfyUI 在线，用户拿到的也永远是占位视频，且 `comfy_used=true` 误导用户以为走了真推理。`ComposeRunRequest` 的 `keyframe_ids/depth_weight/canny_weight/aspect` 也全部被丢弃（routers.py:536 只取 model/prompt/duration）。
建议：要么真正接 `revive.stage5.run_stage5`（异步、把 keyframes 传入），要么把字段/文案改名为占位演示并如实返回 `comfy_used: False`。

**G2. `oilpainting_studio/gui/api/routers.py:322-352` — medium — patch_scene 部分失败污染 undo 栈**
多 patch 循环里：每个 patch 先 `push_undo` 再继续；若第 2 个 patch 命中不存在节点抛 404，第 1 个 patch 的 undo 条目已入栈、但 `save_scene` 未执行 —— 撤销会"还原"一个从未落盘的状态，redo/undo 语义从此错乱（测试只测了单 patch 404，未测混合 batch）。
建议：先校验全部 patch（节点存在、未锁定），再统一应用+入栈。

**G3. `oilpainting_studio/gui/api/routers.py:198-248` — medium — mask 笔刷并发丢失更新**
`PUT /objects/{oid}/mask` 是同步请求处理器，不走 TaskQueue；两次并发提交各自 `imread(mask)→画圈→imwrite`，后者覆盖前者，且两次 `mask_version += 1` 基于同一快照——版本号与内容不一致。同时 `paint_mask` 里 `tmp` 文件在 `imread` 失败分支有清理，但 `imwrite(mask_path)` 抛异常时 `tmp.unlink` 不执行（routers.py:222-229），遗留 `.tmp.png`。
建议：给 ProjectStore 增加 per-object 写锁；tmp 清理放 finally。

**G4. `oilpainting_studio/gui/adapters.py:152-165` — medium — stage2.json 合并逻辑导致重跑后记录/场景指向旧版 PLY**
重跑某物体（同 object_id）时，新 record 因 `oid in known` 被丢弃，`stage2.json` 里永远留着 v1 的 `ply_rel`；`build_scene_from_stage2` 随后把 scene 节点的 `source_ply` 更新为 v1（store.py:264-266 用的是 payload 里的旧记录）。前端 `plyUrl` 用 `gs_version` 兜底所以 3D 视图正确，但 CLI 互操作读取 stage2.json/scene.json 会拿到过期 PLY 路径。
建议：合并时按 object_id **替换**而非追加去重。

**G5. `oilpainting_studio/gui/tasks.py:79-97` — medium — TaskInfo 跨线程读写无锁，model_dump 可能竞态**
worker 线程 `task.log.append(...)`、`task.progress = ...`，请求线程 `t.model_dump(mode="json")`（routers.py:553/561）并发遍历同一 list —— pydantic 序列化 log 列表时可遇 `RuntimeError: list changed size during iteration`（低概率但真实）。`cancel_requested` 有锁保护（正确），result 赋值在锁外。
建议：log 改 `deque(maxlen=N)` 或 dump 时在锁内 copy；`task.result` 赋值移入锁内。

**G6. `oilpainting_studio/gui/store.py:46-51` — low — 原子写本身正确，但并发写同一目标文件仍可碰撞**
tmp+rename 链路验证正确：`path.with_suffix(".json.tmp")` + `replace()`（Windows os.replace 原子）。已知坑"store 原子写正确性"确认已处理。但 `save_object/save_scene/save_keyframes` 不持 `self._lock`（只有 `save_meta/set_stage/import_stage1` 持锁），两个请求线程并发写同一 meta.json 会共用同一个 tmp 文件名交叉写。建议所有落盘方法统一过锁或 tmp 名加随机后缀。

**G7. `oilpainting_studio/gui/store.py:349-370` — low — ProjectRegistry.get 双检缺失**
两个线程同时 miss 缓存会各自 `ProjectStore.open` 并最后写入 `_stores`（最后一个获胜），旧实例上的 `_undo` 栈随之丢失。低概率但 undo 栈是内存态（重启即丢，见 G8），一旦发生用户无感知丢失历史。建议用 `setdefault` 语义。

**G8. `oilpainting_studio/gui/store.py:75-76` — medium（设计缺陷）— undo/redo 栈仅存内存，进程重启即清空**
`_undo/_redo` 是实例 list，桌面 app 或 server 重启后 50 步历史全部蒸发，而 footer 显示 "undo: N / 50" 暗示持久能力。模型注释（models.py:79-87）写着"位图操作 before/after 为快照相对路径"，实际 `mask.paint` 存的是整图 base64 在内存里（routers.py:255-257），大幅笔刷下 UndoEntry 内存占用可观（每笔一张全图）。
建议：UndoEntry 落盘到 `project/.undo/`（mask 存文件），启动时回载；至少在文档/UI 标明非持久。

**G9. `oilpainting_studio/gui/api/routers.py:596-618` — low — mask.paint 的 redo 不恢复 mask_version**
undo 时 `mask_version -= 1`，redo 时不变（`0 if redo else 1`）；一次 undo+redo 后版本比实际内容少 1，前端 `?v=` cache-busting 可能显示旧缓存。建议 redo 对称 +1（有上限）。

**G10. `oilpainting_studio/gui/api/routers.py:508-525` — low — 线稿上传不校验 base64/PNG**
`base64.b64decode(payload["png_b64"])` 无 `validate=True`、解码后不验图，任意字节直接落盘 `stage3/lineart/<kid>.png`；对比 `paint_mask` 有完整校验（400 分支）。且覆写已有线稿不入 undo 栈（破坏 §3.3 约定）。建议对齐 paint_mask 的校验并 push_undo。

**G11. `oilpainting_studio/gui/adapters.py:53-58` — low — 背景文件搬移的 elif 分支死代码**
`src.resolve() == dst.resolve()` 时 `src.name == dst_name` 恒成立，`elif src.name != dst_name` 永不为真；另外 `shutil.move` 在 revive 未产出背景文件时会抛 FileNotFoundError 直接 fail 任务（无友好报错）。

**G12. `oilpainting_studio/gui/store.py:196-241` — low — import_stage1 不清理 stage1 根下的中间产物**
revive 在 `stage1/` 根写 `mask_obj00_*.png`/`crop_obj00_*.png`，导入 objects/ 布局后原文件不删；每次"重新分割"（label 变化时文件名不同）都会累积一套。stage1.json 的 objects 路径指 objects/ 布局（正确），旧文件纯属垃圾。

---

## 3. gui 前端（Vue3）

**F1. `gui/src/components/DemoView.vue:15,47`（本次未提交改动）— low — `loaded` 状态写了从未读**
新增 `const loaded = ref(false)`，仅在 `retryAll` 尾部置 true，模板与逻辑均未消费——死状态，应删除或用于区分"首次加载中/已加载"。

**F2. `gui/src/components/DemoView.vue:44-48,62-64`（本次改动）— low — 重试成功与失败不可区分、runDemo 内的刷新失败误报为 demo 失败**
`retryAll` 先清 `connError` 再 `Promise.all`：三个请求部分成功部分失败时横幅仍会再次出现（可接受），但横幅消失的一瞬用户看到的是空数据。另外 `runDemo` 成功后调用 `loadDevice()/loadRuns()`，若此刻网络抖动，会被外层 catch 捕获并 alert "demo 失败"——实际 demo 已成功。建议把成功后的刷新单独 try/catch。

**F3. `gui/src/components/DemoView.vue:87-92`（本次改动）— low — 后端不可达时空状态与横幅同时显示**
连接失败时 `paintings` 保持 `[]`，底部 `v-if="!paintings.length"` 的 "暂无示例画作 — 用 curl -F 上传" 提示与红色横幅同屏，误导用户去上传。建议 `v-if="!paintings.length && !connError"`。

**F4. `gui/src/i18n.js:113-115, 218-220`（本次改动）— 验证通过（一处既有瑕疵）**
新增 `connError/connErrorHint/retry` 中英词条齐全，函数式词条经 `t()` 分发正确。交叉校验全部组件使用的 ~130 个 key：zh/en 均有定义（唯一例外：`en.keyframesTitle`（i18n.js:178）无任何组件使用且 zh 缺失——孤儿词条，建议删除）。已知坑"TestClient 跟随重定向"对应的 `follow_redirects=False` 用法在测试中正确。

**F5. `gui/src/api.js:75-84` — medium — waitTask 超时后任务仍在跑且不取消**
默认 300s 超时（SegmentView/GsView/SceneView 均用默认值）；真实 GPU TripoSplat 多物体批次完全可能超过 5 分钟 → 前端抛"任务超时"红色错误，但后端任务继续占用 GPU，用户再点"生成"会追加第二个 GPU 任务排队。超时分支不调用 `api.cancelTask`。建议超时时先 cancel 再抛错；或改为无限轮询+提供取消按钮（UI 已有 cancel API 却没有任何组件暴露它——`cancelTask` 在 api.js:69 定义后零调用，功能缺口）。

**F6. `gui/src/components/SceneView.vue:34` — low — PLY URL 的 oid 提取方式脆弱**
`Number(n.node_id.split('-')[1])` 依赖 `build_scene_from_stage2` 的 `obj-XX-label` 命名；若未来 node_id 格式变化静默 NaN。建议 scene 节点直接存 object_id 字段（模型已有 source_ply，可复用）。

**F7. `gui/src/three.js:147` — low — PLY 加载失败静默吞掉**
`undefined, () => { /* PLY 加载失败静默 */ }`：gs_version>0 但文件被外部删除时，视口里物体凭空消失且无任何提示。建议至少 console.warn + 通知回调。

**F8. `gui/src/components/KeyframeView.vue:29-39` — low — 50ms setTimeout 等 DOM 是竞态写法**
`select(kf)` 用 `setTimeout(50)` 等待 canvas ref 就绪再加载底图；快速切换关键帧时两个 Image.onload 竞态，后完成的覆盖先完成的（可能画错底图）。建议用 `nextTick` + 请求序号守卫。

---

## 4. revive 管线

**R1. `oilpainting_studio/revive/stage3/__init__.py:73,138,149,163,171,176`、`stage4/__init__.py:132-144`、`stage5/__init__.py:100-143`、`eval.py:31,52`、`pipeline/director.py:134,147`、`stage3/lineart_parse.py:20`、`common/utils/image.py:21,26` — high — "全仓 _imio 替换"并未完成，约 25 处裸 cv2.imread/imwrite 残留**
已知坑验证结论：**中文路径修复只覆盖了 stage1/stage2 与 GUI 层**，stage3/4/5、eval、director checkpoint 加载、lineart_parse、common/utils/image 全部仍是裸 cv2 调用。触发路径真实存在：
- `revive/cli.py run --lineart 中文路径线稿.png` → `load_lineart`（lineart_parse.py:20）cv2.imread 返回 None → 静默退回"使用物体原始 mask"，用户的线稿被无提示忽略；
- `run_pipeline(..., resume_from_stage)` → `director._load_stage1` 对中文 painting_path `cv2.imread` 得 None → `image.shape` 直接 AttributeError 崩溃（director.py:134-135 无 None 检查）；
- `stage3/__init__.py:73` 的 `original_mask` 为 None 时，后续 `compute_hole_mask(None, ...)`（140-142）在 `new_mask is not None` 分支下崩溃；
- `common/utils/image.py:21` `first.shape` 对 None 同样裸崩。
建议：把 `_imio.imread_/imwrite_` 统一到 common 并全量替换上述文件；至少先修 lineart_parse 与 director 两处用户可直接命中的。

**R2. `oilpainting_studio/revive/stage1/segment.py:224`、`depth.py:84`、`stage2/triposplat.py:155` — medium — `except (ImportError, Exception)` 吞掉一切异常**
`ImportError` 是 `Exception` 子类，元组冗余且语义误导：真正的推理期错误（CUDA OOM、权重损坏、形状错误）全被降级成 "mock"，用户以为在跑真模型实际是 K-Means。尤其 depth.py:84 —— DA-V2 半路抛错也静默换 mock 深度，`eval_depth_fidelity` 于是评估的是假深度。建议：捕获 `(ImportError, FileNotFoundError)` 走 mock，其余异常上抛或至少 logger.error + 在 Stage 输出里记录 `fallback_reason`。

**R3. `oilpainting_studio/revive/stage2/triposplat.py:185` — medium — `source="triposplat" if False else "mock"` 硬编码**
即使将来 `generate_with_triposplat` 实装，record.source 也永远是 "mock"；当前写法还留下恒假分支污染语义。建议根据是否走了 except 分支设置。

**R4. `oilpainting_studio/revive/stage4/__init__.py:123-125` — medium — 手绘关键帧线稿叠加逻辑是死代码**
`if i < len(stage3.__pydantic_fields__): pass  # 不会触发，保留逻辑`——`lineart_path` 恒为 None，`KeyframeSpec.lineart_path` 永不填充。CLI `--keyframe` 参数传入的手绘线稿在模块 4 完全未消费（stage1 解析后 controls.keyframe_paths 无人读取）。这是功能与文档（schemas.py:9 "根据手绘关键帧线稿生成多张关键帧"）的实质脱节，不只是风格问题。

**R5. `oilpainting_studio/revive/pipeline/director.py:117-122` — low — 返回值硬编码 mock 文件名**
`final_video = project_dir/"stage5"/"final_mock.mp4"`，ComfyUI 真跑时产物名不同，靠 glob 兜底抓第一个 mp4——若 stage5 下同时存在 `keyframes_rgb.mp4`（stage5/__init__.py:55 LTX 路径产物）可能返回错误的中间产物。建议直接返回 `stage4.final_video_path`。

**R6. `oilpainting_studio/revive/stage3/__init__.py:140-146` — low — inpaint 循环对象掩码列表可能错位**
`object_masks_original.append` 在 `record is None: continue` 时被跳过，而 `object_masks_new.append` 在同一迭代后追加——两者按 zip 配对依赖同一次迭代的成对 append，当前逻辑成立；真正问题是 `original_mask` 未做 None 检查（见 R1）。

**R7. `oilpainting_studio/revive/stage3/reposition.py`（优化循环）+ `config.edge_align_iterations=50` — low — 逐点渲染优化性能风险**
`optimize_repositioning` 每次迭代 `render_object_to_2d` 全点投影 + Canny + dilate（50 次迭代 × 每物体），1080p 图 + 5k 高斯点时 CPU 耗时可观；无进度回调、无早停。GUI 端因不调用该路径（快照走 routers._snapshot_task 的 2D 平移简化）不受影响，仅 CLI 全流程受累。建议 IoU 收敛阈值早停。

---

## 5. video 管线

**V1. `oilpainting_studio/video/pipeline/director.py:100-139` — medium — run_full 失败时 meta 完全不落盘**
docstring 承诺"进度与错误记录"，但异常传播后 `write_meta` 不会执行（finally 只关客户端）——失败的 run 在项目目录里没有剧本 stage 记录，排障只能看日志。建议 except 分支写 `meta["stages"][stage] = {"ok": False, "error": ...}` 后 re-raise。

**V2. `oilpainting_studio/video/pipeline/director.py:64-85` — low — concurrency 配置形同虚设**
`stage_render` 串行 await 每个镜头；`ComfyClient._sem` 只在并发调用 `run()` 时才限流，而这里从未并发。`Settings.concurrency=2`（config.py:47）对 video 管线无实际效果。要么 gather + 信号量并发渲染，要么删配置避免误导。

**V3. `oilpainting_studio/video/pipeline/ffmpeg_tool.py:26-27` — low — 机器特定硬编码路径**
`D:/Code/anaconda3/Library/bin/ffmpeg.exe` 写死在库代码里，换机即失效（有 which 兜底，非致命）。建议移到 .env 示例文档。

**V4. `oilpainting_studio/video/pipeline/edit.py:51-54` — low — concat 列表未转义路径中的单引号**
`file '{c.as_posix()}'`：路径含 `'` 时 concat demuxer 解析错乱；Windows 下 as_posix 产生 `/D:/...` 形式 ffmpeg 可接受，但引号场景未处理。低概率，加 `.replace("'", "'\\''")` 即可。

**V5. `oilpainting_studio/video/pipeline/edit.py:73-99` — low — 字幕时间轴与实际片段时长漂移**
旁白按 `script.shots` 的 `duration_sec` 累计 `enable=between(t,...)`，但 I2V 实际帧数经 `_num_frames` 取整（animate.py:30-35 `n|1`），每镜头偏差可累计数秒，后面的镜头字幕会提前/滞后消失。docstring 已自知（"作为近似可接受"），属已知妥协，建议至少在 meta 里记录实际时长。

**V6. `oilpainting_studio/common/llm_client.py:101-106` — low — 4xx（如 401/400）也走指数退避重试**
`raise_for_status` 抛出的 HTTPStatusError 被 `except (httpx.HTTPError, ...)` 捕获后重试 6 次，认证错误白白等待 ~93s。建议 4xx（除 429）直接返回哨兵错误。

**V7. `oilpainting_studio/video/pipeline/keyframe.py:35-63` — 验证通过 — 工作流模板注入设计合理**
`apply_params` 深拷贝模板、路径注入（`inputs.text`）、`set_seed` 均正确；模板缺失时 FileNotFoundError 信息含查找路径，好。未发现问题。

**V8. `oilpainting_studio/common/comfy/client.py:139-153` — low — 轮询超时后不清理 ComfyUI 队列**
`run()` 超时抛 TimeoutError 后，ComfyUI 侧任务仍在排队/执行，占用 GPU；下次提交继续排在后面。建议超时时调用 `/interrupt` 或记录 prompt_id 供 CLI 清理。

---

## 6. common 工具

**C1. `oilpainting_studio/common/utils/image.py:21-26` — high（与 R1 合并计数）— frames_to_video 双缺陷**
裸 cv2.imread（中文路径炸）+ 无 None 检查（`first.shape` AttributeError）。revive stage5 mock 与 GUI compose 占位路径都依赖它，是全链路最容易踩的公共函数。建议改用 imdecode 版本并显式报错。

**C2. `oilpainting_studio/common/config.py:15` — low — 注释与实际不符**
`PROJECT_ROOT = Path(__file__).resolve().parents[2]  # OilPaintingVideo/` —— 注释还是旧仓库名，实际是 OilPaintingStudio 根。迁移残留（scripts/migrate_imports.py 迁移时未更新注释）。

**C3. `oilpainting_studio/common/utils/vram.py:9-16` — low — release_gpu_memory 名不副实**
只 `empty_cache()`（释放缓存的块，不卸载模型权重）；director 在每阶段后调用它给人"显存已释放"的错觉（logger 还打印 "GPU 显存已释放"）。YOLO/DA-V2 模型对象在 revive 各 stage 内部局部持有、阶段结束由 GC 回收，勉强成立，但日志措辞误导排障。建议改名 `empty_cuda_cache` 或真正 del 模型引用。

---

## 7. desktop 回退逻辑（专项结论）

三档回退 `gpu→cpu→mock` 的核心链路（device.py `probe_device`/`resolve_choice` + engine.py `_segment_backend`）验证**正确**：
- auto 映射修复确认到位（device.py:192 `"auto": report.tier`）；
- 强制 GPU 无 CUDA → CPU 回退 + reason；强制 CPU 无 torch → MOCK 回退；强制 mock 短路（device.py:131-133）；
- YOLO 加载失败时 engine 落 mock 并如实改写 backends（engine.py:121-125）；
- 零检出时保底 `segment_mock` fallback（engine.py:152-155）。
遗留问题即 D1/D2（并发与队列外 GPU 竞争）、D3（prefer 无校验）。

---

## 8. 已知坑逐项核验汇总

| 已知坑 | 结论 |
|---|---|
| Windows cv2 不读中文路径（全仓 _imio 替换） | **未彻底**：stage1/2 + GUI 层已替换，stage3/4/5、eval、director、lineart_parse、common/image 共 ~25 处残留（R1/C1） |
| revive 中文路径修复在 _imio.py | 已确认存在且被 stage1/stage2 正确使用 |
| TestClient 跟随重定向 | 已处理：test_gui_server.py:92 `follow_redirects=False` 断言 307 |
| resolve_choice auto 映射 | 已处理：device.py:192 |
| IAB evaluate 超时拆步 | **本仓库不存在 IAB 模块**（全仓 grep 无 IAB/evaluate 交互组件）；对应概念是前端 `waitTask` 超时（F5），后端 demo 无超时问题 |
| api.py app 定义顺序 | 已处理：desktop/api.py:189 app 在 router 之后定义，import 即可用 |
| 三处未提交改动（DemoView/i18n/__main__） | 见 D1、F1-F4：方向正确、修复有效，余 4 个 low 级瑕疵；`__main__.py` 挂 gui routers 是必要修复但引入 D1 队列外 GPU 竞争 |

## 9. 测试盲区

- **T1** `tests/test_desktop_demo.py` 只测 `desktop/api.py` 的 app；**本次改动的 `desktop/__main__.py`（gui routers 挂载）零覆盖**——若 router 属性名笔误，桌面入口 import 即崩，测试全绿。建议加一条 `from oilpainting_studio.desktop.__main__ import app; GET /api/projects == 200`。
- **T2** 前端无任何测试（connError/retry 逻辑、waitTask 超时分支、undo 栈 UI 均无覆盖）。
- **T3** 无并发测试：并发 mask 笔刷（G3）、并发 demo run（D2）、多 patch 部分失败（G2）。
- **T4** test_gui_server.py:82 等 5 处 `open(painting_png, "rb")` 未关闭文件（Windows 上 tmp_path 清理可能失败产生偶发红）；建议 `with open(...)`。
- **T5** test_gui_server 的 client fixture 重置 `srv.registry` 但**不重置 `task_queue`**——上一测试残留的 worker 任务可能操作已删除的临时目录（当前因 mock 任务极快而侥幸不炸）。
- **T6** revive 全流程测试全部走 ASCII tmp 路径，中文路径回归无守护（正是 R1 漏网的原因）；建议加一个 `项目目录名=中文` 的端到端用例。

---

## 总体评价

整体架构清晰：存储/任务/适配/路由分层干净，原子写与版本翻版等关键协议实现正确，三档设备回退与各级 mock 降级把"无 GPU/无依赖也能跑通全流程"落到了实处，测试对 API 合约的覆盖（85 个用例）在同规模项目里属上乘。但有两个系统性短板：其一，**"全仓 cv2 中文路径替换"是半成品**——stage3/4/5 及公共工具仍裸用 cv2，GUI 之外的 CLI 链路在中文路径上必炸；其二，**"ComfyUI 可用时走真推理"的宣传与实现脱节**（compose 恒占位、TripoSplat 恒 mock），加上吞异常式的降级（R2），让"mock 冒充真模型"成为贯穿性风险。本次未提交的三处改动方向正确、实现基本干净（4 个 low 瑕疵），但 `__main__.py` 挂载 gui routers 后 demo 推理与任务队列的 GPU 竞争是新增的真实问题。

**优先改进 Top 3**

1. **补完 cv2 中文路径替换（R1/C1，high）**：统一 `_imio` 到 common 并替换 stage3/4/5、eval、director、lineart_parse、common/utils/image 的 ~25 处裸调用，同时补 None 检查；加一条中文项目名的端到端回归测试锁死该类问题。
2. **修复 compose 的真假混淆（G1，high）+ 收敛吞异常降级（R2）**：run_compose_task 要么真接 ComfyUI 要么如实上报 `comfy_used: False` 并同步 UI 文案；`except (ImportError, Exception)` 收窄，让推理期错误可见。
3. **统一 GPU 调度与并发安全（D1/D2/G5，medium-high）**：demo run 纳入与 TaskQueue 共享的 GPU 互斥；engine.run 与 TaskInfo 读写加锁；前端 waitTask 超时时调用已有的 cancelTask（api.js:69 目前是零调用的死接口）。
