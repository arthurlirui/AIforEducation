# GestureCoach 代码审阅报告（2026-11-09）

审阅范围：`GestureCoach/`，重点 v4 手势指令管线（gesture_command + gesture_yolo），覆盖后端诊断算法、LLM 调用层、插件侧、存储与配置。所有问题均经实际读码确认；332 测试在本地实际运行确认全绿（`332 passed in 19.36s`）。

## 0. 模块结构

| 模块 | 职责（一行） |
|---|---|
| `gesturecoach/config.py` | 全部算法阈值/阶段画像/GLM/难度分级配置常量 |
| `gesturecoach/types.py` | 全部 dataclass/enum（HandFrame、Deviation、FusedDiagnosisResult 等） |
| `gesturecoach/tracking.py` | MediaPipe 手部关键点提取 + 遮挡插值 + 平滑 + 归一化 |
| `gesturecoach/features.py` | 关节角、笔尖轨迹（速度/加速度/曲率）、FFT 节奏特征 |
| `gesturecoach/dtw.py` | 改进 DTW（欧氏+余弦融合）+ Procrustes MPJPE |
| `gesturecoach/diagnosis.py` | v1 四轴偏差诊断（空间/姿态/方向/时序） |
| `gesturecoach/canvas_diagnosis.py` | v2 第五轴画布诊断（压力/透明度/笔画密度/图层） |
| `gesturecoach/paint.py` | 从画布事件/视频帧估计颜料参数（厚度/透明度/粘度） |
| `gesturecoach/fused_diagnosis.py` | 五轴加权融合 |
| `gesturecoach/stages.py` | ST-GCN+Bi-GRU 阶段识别 + 两级启发式分段 fallback |
| `gesturecoach/template.py` | 按阶段存艺术家参考模板库 |
| `gesturecoach/pipeline.py` | v1/v2 编排（离线 + 滑窗实时） |
| `gesturecoach/feedback.py` | 规则引擎反馈 + 可选 OpenAI LLM 改写 |
| `gesturecoach/glm_client.py` | 智谱 GLM 封装（embed/chat/理解/CogView/GLM-4V） |
| `gesturecoach/glm_feedback.py` | RAG 三级降级教学提示生成 |
| `gesturecoach/knowledge_base.py` / `knowledge_pipeline.py` | SQLite+numpy 向量知识库 / 视频摄取管线 |
| `gesturecoach/gesture_command.py` | **v4**：手势→画布操作双层转换（GLM/规则） |
| `gesturecoach/concept.py` / `master_styles.py` | v3 构思生成/分析、大师风格库 |
| `gesturecoach/artwork_archive.py` / `annotation.py` / `classroom.py` | v3 SQLite 存储（作品档案/教师批注/课堂小组） |
| `gesturecoach/api.py` | FastAPI 全部端点（v1 模板/诊断 + v2 五轴/RAG + v3 + v4 手势指令） |
| `krita_plugins/gesturecoach/gesture_yolo.py` | **v4**：YOLO 识别器 + 21 点几何规则 fallback |
| `krita_plugins/gesturecoach/video_source.py` | 摄像头/文件/网络流统一采集源（线程化+重连） |
| `krita_plugins/gesturecoach/camera_panel.py` | **v4**：相机面板 + GestureWorker + CanvasCommandExecutor |
| `krita_plugins/gesturecoach/ws_client.py` | HTTP 通信客户端（PyQt5 QNAM / urllib 双通道） |
| `krita_plugins/gesturecoach/webcam_thread.py` / `event_capture.py` | MediaPipe 后台线程 / 数位板事件捕获 |
| `krita_plugins/gesturecoach/ui_panel.py` / `concept_panel.py` / `exercise_manager.py` / `plugin.py` | 主面板（5 Tab）/构思面板/练习管理/插件注册 |
| `tests/`（22 文件，332 用例） | 合成数据驱动的单元+集成测试 |

---

## 1. v4 手势指令管线 — gesture_command.py（后端 LLM 决策层）

**规则层覆盖度：合格。** `DEFAULT_RULES`（gesture_command.py:62-73）与 `FALLBACK_EXPLANATIONS`（:76-87）完整覆盖全部 10 个 `VALID_GESTURES`，且 `tests/test_v4_gesture_pipeline.py:255` 有逐手势回归测试。参数校验 `_validate_operation`（:137-170）对全部参数做 clamp，未知操作回退 `none`。

- **`gesturecoach/gesture_command.py:211-212, 254, 263-274` — high — 重复抑制状态非线程安全，且共享性不一致。** `self._last_gesture/_last_time` 无锁读写；`api.py:1050` 的同步端点在 FastAPI 线程池中并发执行，两个并发手势请求会竞争该状态，可能导致抑制失效（同手势双触发 `save_document`/`undo`）。另外模块级封装 `convert_gesture_to_command`（:319-335）每次调用新建 converter，经此路径重复抑制完全不生效（端点未用它，仅影响直接调用者）。建议：加 `threading.Lock`；删掉或修正模块级封装。
- **`gesturecoach/gesture_command.py:292-302` — high — GLM 调用无超时/无熔断（详见 §4 glm_client）。** 异常处理本身健壮：`except Exception: return None` → 落到规则层，`raw` 为空、JSON 解析失败均回退（测试 :327-348 覆盖三种失败）。缺口在**延迟**而非正确性：一次网络挂起的 GLM 调用可阻塞端点数十秒，期间插件侧 30s 超时放弃，但后端仍挂着请求。建议：给 chat 传入显式 timeout（如 3-5s），并加"GLM 连续失败 N 次后短期直连规则层"的熔断。
- **`gesturecoach/gesture_command.py:137-170` — medium — 参数 clamp 后仍允许语义可疑值。** 如 `set_color` 只校验 rgb 长度为 3（:154-157），`preset` 接受任意字符串（:152），`pick_color` 坐标 clamp 到 [0,1] 合理；`new_layer` 名字截断 50 字符合理。`zoom` factor 允许 0.1-10（:162），单次 10 倍缩放对教学场景偏激进。建议：范围收紧到 config。
- **`gesturecoach/gesture_command.py:173-192` — low — `_parse_llm_json` 与 glm_client 内两套 JSON 提取逻辑重复且行为不一致**（本实现剥 code fence，glm_client.py:184-190、:338-344 不剥）。多处 LLM 输出解析应统一为一个工具函数。
- **`gesturecoach/gesture_command.py:230` — low — `import time` 写在方法体内**，每次调用重复查 sys.modules；移到模块顶部。

## 2. v4 识别器 — krita_plugins/gesturecoach/gesture_yolo.py（几何规则 + YOLO fallback）

几何分类器 `classify_from_landmarks`（:110-215）整体判定链合理（OK→pinch→thumbs→victory/two_finger→point→palm，兜底 0.5 置信度），never-raise 保证（:214）到位。具体问题：

- **`krita_plugins/gesturecoach/gesture_yolo.py:352-359` — high — pose 模型关键点 <21 时硬编码返回 `POINT_INDEX`。** 任何仅有 bbox 的手部检测都被标为"食指指向"→ 经规则层触发 `start_stroke`。这是把"识别不出来"静默升级为"开始绘制"的误操作源。建议：返回 `NO_HAND`（source="yolo_pose"）或单独的"detected_unclassified"状态。
- **`krita_plugins/gesturecoach/gesture_yolo.py:368-375` — medium — 类名模糊匹配过宽。** `if key in name or name in key`：`"ok" in "smoke"`、`"one" in "money"`、`"two" in "twenty"` 都会错误映射。建议：只做精确匹配 + 显式别名表，删除子串兜底。
- **`krita_plugins/gesturecoach/gesture_yolo.py:159-168` — medium — thumbs_up/down 依赖相机竖直方向。** `dy < -0.5*scale` 判定拇指朝上；拇指横置的点赞会落入 :170 的 FIST 分支 → 触发 `end_stroke`。2D 几何的固有局限，至少应在文档/UI 标注"拇指需朝上/下"，或用拇指指尖相对掌心的角度做旋转不变判定。
- **`krita_plugins/gesturecoach/gesture_yolo.py:131, 140-148, 178-179` — medium — 魔数全部硬编码**：拇指外展比 1.2、OK 距离 0.35、pinch 距离 0.3、victory 张开度 0.45、extended 容差 1.05。这些是分类准确率的直接旋钮，且 OK(0.35) 与 pinch(0.3) 阈值区间重叠——拇指食指距离在 0.30-0.35 之间时，结果完全取决于其余三指是否全伸，边界手势易抖动（有 stability_window 缓解）。建议：集中到 config 或构造参数。
- **`krita_plugins/gesturecoach/gesture_yolo.py:385-410` — medium — `_stabilize` 返回旧标签时携带新帧的 landmarks/bbox。** 标签来自上一个手势、坐标来自当前帧，下游若用 bbox 做定位（pick_color）会取错位置；且置信度减半（:405 `max(0.3, conf*0.5)`）恰好落在 `min_confidence=0.5` 边界附近，行为对阈值微调敏感。建议：未稳定时清空 bbox/landmarks 或整体返回 NO_HAND。
- **`krita_plugins/gesturecoach/gesture_yolo.py:349-350` — low — YOLO pose 路径置信度无依据 +0.05。** 应直接使用检测置信度。
- **`krita_plugins/gesturecoach/gesture_yolo.py:100-107` — low（类型注解）— `_dist`/`_to_np`/`classify_from_landmarks` 参数无类型标注**，`landmarks` 既可以是 list 也可以是 ndarray（`_to_np` 的返回类型随 numpy 有无而变），全靠运行时 duck-typing。

**测试盲区**：YOLO 推理路径（`_recognize_yolo`）完全没有测试——没有 mock 模型覆盖 <21 关键点分支、类名映射、置信度阈值分支。这正是上面 <21 kpt → POINT_INDEX bug 溜进来的原因。

## 3. v4 插件面板 — camera_panel.py / video_source.py / ui_panel.py

- **`krita_plugins/gesturecoach/ui_panel.py:173`（及 :460）— critical — 调用了不存在的 `CameraPanel.set_comm()`。** `grep` 确认 `set_comm` 只定义于 `concept_panel.py:47`；`camera_panel.py` 的 `_comm` 只能经构造函数注入（:363）。后果分两处：
  - `show()` 的 Tab 2 构建处（:173）：抛 `AttributeError`，而外层 `try/except ImportError`（:396）不捕获它 → **在真实 Krita 中整个面板无法打开**。
  - `_on_connect`（:460）：连接成功后抛 `AttributeError` → camera panel 的 `_comm` 永远是 None → `_on_gesture`（camera_panel.py:566）直接 return → **v4 手势→画布指令在真实 UI 路径上是死功能**。
  测试全部经构造函数注入 comm（test_v4_gesture_pipeline.py:489 `CameraPanel(comm=FakeComm(), ...)`），所以 332 绿测完全没覆盖到。修复：给 `CameraPanel` 加 `def set_comm(self, comm)` 并补一条测试。
- **`krita_plugins/gesturecoach/camera_panel.py:569` + `ws_client.py:138-149` — critical — 手势指令 HTTP 请求在 GUI 线程同步执行。** `_on_gesture` 是 `gesture_detected` 信号的主线程槽，`interpret_gesture` 是同步调用（后端 GLM 可能数秒，插件超时 30s，ws_client.py:503），期间 Krita UI 完全冻结；Qt 通道还用 `loop.exec_()` 跑嵌套事件循环（重入风险：冻结期间新手势信号会被嵌套循环派发）。修复：把 `interpret_gesture + execute` 挪到 worker/QThread，结果经信号回主线程；或至少把超时降到 2-3s。
- **`krita_plugins/gesturecoach/camera_panel.py:195-201` — high — `execute()` 分支顺序错误，`operation="none"` 被判为未知操作。** `handler = getattr(self, f"_op_{op}", None)` 先判 `handler is None`，而类中不存在 `_op_none` → "none"（抑制/无效手势的常态返回值）落入 "unknown operation: none"，`executed=False`；:199 的 `elif op in ("", "none")` 是死代码。所有被抑制的手势都会在日志里显示 ⚠️。测试只测了 `"explode_canvas"`（test:470-475），没测 "none"。修复：把 no-op 判断移到 handler 查找之前。
- **`krita_plugins/gesturecoach/camera_panel.py:307-320, 330-343` — medium — 两个 Krita 操作实现与声明不符。** `_op_set_brush` 触发 `brush_size` action 作为"no-op fallback"（可能弹出 UI）且从不真正设置笔刷，却返回 `executed=True`；`_op_pick_color` 计算了 (x,y) 但触发的 `pick_color` action 在光标位置取色，忽略请求坐标。建议：未实现的操作返回 `executed=False` + 明确 detail，避免日志误导。
- **`krita_plugins/gesturecoach/camera_panel.py:86-115` — medium — YOLO 推理与 QImage 转换内联在采集回调线程。** `VideoSourceBase._deliver`（video_source.py:146-156）同步调用 `_on_frame`，CPU 上 YOLO 推理 50-200ms 会拖慢整个采集循环（fps pacing 在 video_source.py:222-224 只测读帧时间，实际帧率被推理时间压低，预览也卡顿）。建议：`_on_frame` 只暂存帧，推理放到独立定时批处理（如每 100ms 一帧），预览转换保持轻量。另：`QImage(rgb.data, ...)`（:97）依赖 emit 时序列化拷贝，`rgb` 无本地引用持有，属脆弱写法。
- **`krita_plugins/gesturecoach/camera_panel.py:166-174` — medium — `_try_attach_krita` 只在构造时执行一次。** 面板构造时 Krita 可能尚无活动窗口/文档 → `_view=None`，此后永不重试，所有操作永远 no-op。建议：在 `execute` 时惰性重连。
- **`krita_plugins/gesturecoach/ui_panel.py:399-406` + `event_capture.py:119-120` — medium — 事件过滤器安装后永不移除。** `shutdown()` 停了监控线程和相机，但没调 `removeEventFilter`；面板关闭后过滤器仍挂在 canvas 上引用已关闭的 panel。建议：`shutdown` 中 `canvas.removeEventFilter(self._qt_filter)`。
- **`krita_plugins/gesturecoach/video_source.py:240-265` — low — 打开相机超时后被放弃的 daemon 线程泄漏**（持有半开的 VideoCapture）；已注释说明，属已知取舍。`VideoFileSource` 固定 30fps 播放（:299-331），不读文件真实帧率，演示时速度失真。

## 4. LLM 调用层 — glm_client.py / glm_feedback.py / feedback.py

- **`gesturecoach/glm_client.py:137-146` — critical — `chat.completions.create` 无超时参数、无重试、`except Exception: pass` 零日志。** 这是全部 GLM 功能（v4 手势指令 Tier-1、RAG 反馈、技法理解、概念评语）的唯一通道。网络失败在**正确性**上回退健壮（返回 "" → 各调用方落规则层），但（a）无超时 → 实时路径可被单次调用阻塞到 SDK 默认上限；（b）所有失败静默吞掉 → 生产环境完全无法诊断"为什么走了规则层"。建议：显式 `timeout=`、失败记 logger.warning（含异常类型）、可选一次重试。
- **`gesturecoach/api.py:262` + `gesturecoach/config.py:184-205` — high — GLM 在标准部署下永远不可用。** `create_v2_app_factory` 硬编码 `GLMConfig(enable_glm=False, api_key="")`，而 `GLMConfig` 没有任何环境变量读取逻辑——即使设置了 `ZHIPUAI_API_KEY`，`available` 恒为 False。v4 的 GLM Tier-1、RAG Level-1、CogView 生成全部不可达，只能走规则/缓存层。建议：`GLMConfig.from_env()` 读取 `ZHIPUAI_API_KEY`/`GC_ENABLE_GLM`。
- **`gesturecoach/glm_feedback.py:245-251` — medium — `client.embed(query)` 在 `client.available` 检查之前调用。** 知识库若曾用真实 embedding 建库，离线查询用 hash 伪 embedding → 余弦相似度≈0 → 检索永远为空 → Level-2（缓存提示）实际不可达，直接落 Level-3。降级本身安全，但三层设计中的中间层形同虚设。建议：`available` 为 False 时跳过 embed，直接用条目文本做关键词/阶段匹配。
- **`gesturecoach/glm_feedback.py:164-168` — medium — 解析出的每条 tip 的 `knowledge_ref` 一律指向第一个检索条目**，与 tip 实际来源无关，出处失真。
- **`gesturecoach/glm_client.py:184-190, 338-344` — medium — 与 gesture_command 重复的两套 JSON 提取逻辑**（不剥 code fence），行为不一致，见 §1。
- **`gesturecoach/glm_client.py:312-313` — low — 整图 base64 无大小上限**，大图直接进 prompt。
- **`gesturecoach/feedback.py:91-94` — low — rigid/elastic 两个 GOOD-severity 分支都是 `continue`**，区分是死代码，可合并为一个判断。
- **`gesturecoach/feedback.py:141-175` — low — v1 的 OpenAI LLM 层与 v2 的 GLM 层并存**，`PipelineConfig.llm_model="gpt-4o"`（config.py:89）是遗留默认值，`enable_llm_feedback` 默认 False 尚无实际危害，但两套 LLM 体系易混淆。

## 5. 编排与数据流 — api.py / pipeline.py

- **`gesturecoach/pipeline.py:187-191` — high — 阶段模板缺失时静默取库里第一个模板。** `list(self.library._templates.values())[0]`（还穿透了私有属性）：请求 impasto 阶段却拿 sketch 模板比对，诊断结果系统性失真且用户无感知。对比：v1 路径（:117-118）会抛 KeyError、api 层给出明确错误信息。建议：v2 同样抛错，或在结果中标注"参考模板阶段不匹配"。
- **`gesturecoach/pipeline.py:85-108` + `gesturecoach/tracking.py:145-176` — medium — 滑窗共享 HandFrame 对象导致重复预处理。** `windows()` 用列表切片，重叠窗口共享同一批 HandFrame；`run_window` 每窗都调 `preprocess`，而 `interpolate_occlusions` 是**原地写**（tracking.py:166 `frames[i].landmarks[j, d] = v`）、`smooth_sequence` 重新绑定——重叠帧被多次平滑/归一化（归一化近似幂等，平滑不是）。`run_realtime` 路径的时序诊断因此与单窗结果不一致。建议：preprocess 前深拷贝帧，或对整个序列预处理一次再切窗。
- **`gesturecoach/api.py:346-353`（及 :497-509）— low — `StrokePoint` 各字段静默默认**：`timestamp` 缺省 0.0 → `summarize_canvas` 中 dt=1e-6 → mean_speed 天文数字（幸而 canvas 诊断未用 mean_speed，见 §6）；`color` 缺省黑、`brush_opacity` 缺省 1.0。建议：请求校验提示缺字段。
- **`gesturecoach/api.py:1035-1036, 1043-1047` — 已验证正确**：v4 端点注册在 SPA catch-all 之前，注释所述路由遮蔽问题已规避，且有 endpoint 测试覆盖。
- **`gesturecoach/api.py:258` vs `config.py:217-222` — medium — `GC_DATA_DIR` 两处读取时机不同**（config 在 import 时、factory 在调用时）。在 import 之后设置环境变量会出现知识库与作品库写往不同目录的"脑裂"。建议：统一到 config 单点读取。
- **类型注解**：api.py 全部端点返回裸 `dict` 无返回模型；`pipeline.run_window_v2` 返回裸 `tuple`；对前后端契约全靠约定。

## 6. 诊断算法核心 — dtw / diagnosis / tracking / features / canvas_diagnosis / paint

- **`gesturecoach/canvas_diagnosis.py:113-119` — medium — 笔画密度诊断存在量纲混乱与死变量。** `duration = max(summary.mean_speed, 0.001)` 计算后从未使用（mean_speed 也不是 duration！）；`user_rate = float(summary.stroke_count)` 是**计数**而非速率，却与 `expert_stroke_rate * 3`（硬编码假设 3 秒窗）比较——实际窗口可能是 15 个点或 90 帧，比例全错。注释自己承认是 proxy。建议：用 `pts[-1].timestamp - pts[0].timestamp` 计算真实时长。
- **`gesturecoach/canvas_diagnosis.py:63` — low — 硬编码 0.85 早退阈值**，与 config 的 `SEVERITY_GOOD=0.85` 重复定义未引用；paint_usage（:84）同样硬编码。`_severity_from_deviation` 的 0.3 margin 系数（:43）也是魔数。
- **`gesturecoach/dtw.py:76-79` — medium（性能）— DTW 动态规划是纯 Python 双层循环**，且 `diagnose()` 每窗跑两遍 DTW（空间轴 diagnosis.py:175 + 方向轴 :111 各一次）外加 Procrustes。90×90 窗约 8100 次循环/遍，两遍 + 特征提取，实时路径每窗估计 20-50ms——对 0.5s stride 可行，但与"≥30 FPS、33ms/帧预算"的声明（dtw.py:150-155）有差距。建议：反对角线批量向量化 DP 或 numpy 广播逐行推进；`IncrementalDTW` 目前是全量重算（docstring 已如实承认）。
- **`gesturecoach/tracking.py:157-176` — medium（性能）— 遮挡插值是 O(T×21×3) 的 Python 三重循环**，`smooth_sequence`（:178-190）也是逐帧 Python 循环；90 帧窗约 5.7k 次微小 numpy 标量操作，是实时路径另一热点。两者都可整体向量化（`np.interp` 支持按列批量）。
- **`gesturecoach/diagnosis.py:51, 88` — low — `_sim_from_error` 的 scale=0.35 与 scale=20.0 为经验魔数**（:51 有注释说明量纲依据，尚可）；`GRIP_TOO_TIGHT_INDEX_PIP_DEG=95°` 至少已进 config。
- **`gesturecoach/diagnosis.py:67` — low — `ref_std or 1e-3`**：模板某关节 std 恰为 0 时 z 会被放大 ~千倍，产生假阳性 posture 偏差；建议用 `max(ref_std, 5.0)`（角度量纲下的合理下限）。
- **`gesturecoach/features.py:83-88` — low — `speed[0] = speed[1]` 用 t=1 镜像**，`disp` 用 `prepend=pos[:1]` 使 t=0 位移为 0；两处对首帧的处理不一致，T=2 时 `speed[1]` 本身也接近 0。影响极小。
- **`gesturecoach/paint.py:225-227` — low — 死的三元表达式**：`region.ndim == 2` 恒真（布尔掩码索引必展平为 2D），两个分支代码相同。`summarize_canvas` 的 stroke_count 从 1 起步（:277），首点 pressure=0 时也计 1 笔。
- **`gesturecoach/paint.py:62, 87, 123` — low — 三个像素启发式的映射区间（1.5/200/0.25）为魔数**，无标定来源注释。

## 7. 存储与配置 — knowledge_base / artwork_archive / classroom / annotation / config

- **`gesturecoach/knowledge_base.py:168-171` — medium/high — 向量行与条目的顺序对应是隐式约定。** `search()` 用 `list(self.entries.values())` 的下标去索引 `self.vectors` 行；`load()`（:188-217）用无 ORDER BY 的 `SELECT *` 重建 entries、从 .npy 读 vectors——一旦 SQLite 返回顺序与 .npy 行序不一致（删除重插、VACUUM 后），**检索结果张冠李戴**。建议：建表存 vector row id，或 `SELECT ... ORDER BY rowid`，或改存 (id, vector) 对。
- **`gesturecoach/knowledge_base.py:62`、`artwork_archive.py:50`、`classroom.py:45`、`annotation.py:39` — medium — 四个 SQLite 连接都是 `check_same_thread=False` 且无锁**，FastAPI 线程池并发请求（诊断检索 + ingest 同时到达）会在同一连接上交错执行。SQLite 未加串行化时这是数据竞争。建议：加 `threading.Lock` 包裹写操作，或改 per-request 连接。
- **`gesturecoach/classroom.py:224, 228` — medium — `json.loads(row[3]/row[5])` 无 try 保护**（同函数里 concept_json 有保护），一条损坏行的 `list_groups` 会 500。
- **`gesturecoach/classroom.py:152-168` — low — `add_artwork_to_group` 读-改-写无事务**，并发提交会丢 artwork id。
- **`gesturecoach/config.py:59-60` — low — `SEVERITY_BAD = SEVERITY_MINOR` 别名**与 canvas_diagnosis 的硬编码 0.85 并存，阈值治理不统一。`import os as _os`（:217）在文件中部、模块导入时读取环境变量，时序敏感（见 §5）。
- **`gesturecoach/artwork_archive.py:216-219` — low — 成长对比用文本长度总和的 1.3/0.7 倍阈值**判定"构思演变"，纯启发式且阈值魔数；首尾各取 `len//3` 个样本，n<3 时样本量 1，噪声大。

## 8. 插件通信与采集 — ws_client / webcam_thread / event_capture / exercise_manager

- **`krita_plugins/gesturecoach/event_capture.py:107-114` — critical — 数位板事件从不捕获真实笔刷参数。** Qt 过滤器调 `add_point(x, y, pressure, tilt_x, tilt_y)`，brush_name/brush_size/brush_opacity/color/layer_name 全部落默认值（opacity=1.0、size=10、黑、layer=""）。这些点经 `send_painting_data` 进后端 `summarize_canvas` → `mean_opacity` 恒为 1.0 → **canvas 诊断的 paint_usage 轴对 glazing（期望 0.05-0.3）等阶段永远报偏差**，layer_count 恒为 1（layer 名空被 `summarize_canvas:303` 兜底成 1）→ layer 轴对 impasto/glazing 永远报"图层数不足"。双通道感知的画布通道在生产中输出的是**伪造默认值**，整个第五轴失真。建议：在 `TabletPress` 时从 Krita view/resource server 读取当前笔刷/颜色/图层并附加到每个点。
- **`krita_plugins/gesturecoach/ws_client.py:53-66, 99-115` — medium — Qt 传输失败后不降级。** `_use_qt` 一旦为 True 永不回退，每次请求先走 Qt 失败再落 urllib，延迟翻倍；且 `_mark_failure` 只在 urllib 分支调用（:188），Qt 层失败不标记断连。建议：Qt 连续失败 N 次后切 `_use_qt=False`。
- **`krita_plugins/gesturecoach/ws_client.py:495` — low — `interpret_gesture` docstring 声称 status 为 "executed"**，后端实际返回 "ok"（gesture_command.py:98），文档失真。
- **`krita_plugins/gesturecoach/webcam_thread.py:124` — low — 置信度硬编码 0.9**，MediaPipe visibility 被丢弃；:90-96 手动模式以 30Hz 空转 sleep（video_source 用 0.1s，不一致）。
- **`krita_plugins/gesturecoach/exercise_manager.py:24-44` — 已验证历史坑修复**：`from types import Exercise` stdlib 冲突已用 `importlib.util.spec_from_file_location` + 私有别名正确规避，且注册顺序（:37 在 exec_module 之前）处理了 dataclass 字符串注解解析，并有回归测试（test:409-417）。

## 9. 测试套件与历史坑验证

- **332 测试全绿：已实际运行验证**（`py -3 -m pytest tests -q` → `332 passed, 1 warning in 19.36s`，仅一条 httpx 弃用警告）。
- **mock 泄漏（TechLearn 同修项）：已彻底解决。** `grep unittest.mock|monkeypatch|mocker` 在 tests/ 下 **0 处命中**——整个套件用合成数据 + 构造函数注入（FakeGLM/FakeComm/SpyComm）替代 mock，不存在跨测试 mock 残留可能。
- **commit 5d09c49：已确认**（v4 管线提交，含 gesture_command.py:335 行、gesture_yolo.py:415 行、48 项 v4 测试等，与仓库现状一致）。
- 测试盲区（本次发现的所有 critical/high 均落在盲区内）：
  1. 无 `CameraPanel.set_comm` 测试 → §3 critical 漏网；
  2. 无 "none" 操作经 executor 的测试 → 分支顺序 bug 漏网；
  3. 无 mock YOLO 模型的 `_recognize_yolo` 测试 → <21 kpt 硬编码 bug 漏网；
  4. `tests/test_v4_gesture_pipeline.py:440` — medium — **恒真断言**：`assert "&" not in ... or True` 使 URL 编码校验完全失效；
  5. 无 converter 并发测试、无 `windows()` 共享帧突变测试、无 GLMConfig 环境变量启用测试。

---

## 总体评价

工程素质整体良好：配置集中、降级路径系统化（三级反馈降级、双层手势转换）、离线可测试性（合成序列、headless 面板）、异常兜底意识（recognize/convert never-raise）都明显高于同类原型；历史坑（mock 泄漏、stdlib types 冲突、Qt 跨线程）均已确认彻底修复。但 v4 管线存在一个系统性问题：**测试与真实 Krita 运行路径的注入方式不一致**——测试全部从构造函数注入依赖，而真实 UI 走 `set_comm`/事件过滤器路径，导致 332 绿测之下藏着"面板打不开"级别的 critical bug。另外，画布诊断第五轴的数据源（笔刷参数）从未接通真实值，算法本身再正确也是对默认值做诊断。

**优先改进 Top 3：**

1. **修复 `CameraPanel.set_comm` 缺失（§3 critical，ui_panel.py:173/460 + camera_panel.py）**——一个 5 行方法 + 1 条测试就能让 v4 功能在真实 Krita 里活过来，这是投入产出比最高的一项。
2. **接通 GLM 超时与启用路径（§4 critical/high：glm_client.py:137 无 timeout + api.py:262 硬编码禁用 + camera_panel.py:569 GUI 线程同步调用）**——三者叠加的后果是"GLM 层既用不上、一旦用上还会冻结 UI 30 秒"；应一并加 timeout、环境变量读取、异步化指令分发。
3. **修正画布事件的真实笔刷参数捕获（§8 critical，event_capture.py:107-114）**——否则五轴融合诊断中的 canvas 轴（权重 0.25）持续产出系统性假偏差，直接影响教学反馈的可信度，也会污染后续任何用 canvas_summary 做的评测实验。
