# 全仓代码审阅报告（2026-11-09）

> **修复状态（2026-11-09 同日 + 11-10 完善轮）**：7 个项目的全部审阅问题已修复完毕；11-10 又把上轮所有"最小方案取舍/跳过"项按推荐方案实现完整版——OilPaintingStudio G8 undo 完整持久化（.undo/manifest + 重启回载 + 滚动清理）、TechLearn S5 消除 anim 复制（backend 独占，studio 走 HTTP + 离线占位）、GestureCoach DTW/插值向量化（等价性位级验证，2.8×提速）+ YOLO 推理移出采集回调 + 相机超时泄漏修复、DotArtKit kusama 管线 ndarray 化（消除 PNG 往返，适配层 330ms→9ms）+ 边缘/背景半径参数化、HistorySandbox 沙盘 hover tooltip、OilPaintingPlatform mock 降级 fallback_from 可见化。全仓测试验收：GestureCoach **451**(+8 skip) / DotArtKit **217** / OilPaintingStudio **94** / ArtRealm3D **27**(+前端 3) / HistorySandbox **36** / OilPaintingPlatform **68** / TechLearnStudio **64**(+前端 25) —— 共 **957 项 pytest 全绿**，前端构建全部通过。仍未 commit（GestureCoach 为嵌套 git 仓库，改动在其自身仓库内）。

> 审阅方式：按"算法 + 程序模块"逐项目深入审阅，7 个活跃项目全部覆盖。
> 每份子报告均为逐行读码确认，关键算法结论附数值/实测复核。
> 历史修复（2026-10 / 2026-11 两轮，commit 6f3a3ec）逐项验证，**不重复报告已修复项**，只标注残留。

## 报告索引

| 项目 | 报告 | 一句话结论 |
|---|---|---|
| DotArtKit | [dotartkit.md](dotartkit.md) | 分层纪律优秀，但特征通道符号约定错乱（luminance/hybrid 反向）+ 数值算法边界防御不足（零密度死循环、质心 off-by-one） |
| OilPaintingStudio | [oilpaintingstudio.md](oilpaintingstudio.md) | 架构分层干净，但"全仓 cv2 中文路径替换"是半成品（~25 处残留），compose 真假混淆（恒占位却报 `comfy_used: True`） |
| GestureCoach | [gesturecoach.md](gesturecoach.md) | 降级设计系统化，但 v4 管线藏着一个 critical（`CameraPanel.set_comm` 不存在→真实 Krita 面板打不开）+ 画布诊断数据源从未接通真实笔刷参数 |
| ArtRealm3D | [artrealm3d.md](artrealm3d.md) | 缓存签名不含代码版本（已实证曾致"修复不生效"）；stroke 纹理是彻底 no-op（实测 max diff=0） |
| HistorySandbox | [historysandbox.md](historysandbox.md) | 古地名标签确认"数据就绪、无人绘制"；LLM 假想分支存在 500 路径；旁白乱序竞态修复不彻底 |
| OilPaintingPlatform | [oilpaintingplatform.md](oilpaintingplatform.md) | 完成度高，但存在完整凭据泄露链（用户可控 base_url + 服务器 env Key 外泄）+ DashScope 轮询凭据 bug |
| TechLearnStudio | [techlearnstudio.md](techlearnstudio.md) | M1–M7 原型骨架诚实，但存在 LLM 输出→前端 innerHTML 的完整 XSS 链；sandbox 为 stub、增量版本是假的 |

## 跨项目共性问题（按主题归纳）

### 1. 安全（最高优先）
- **凭据/注入链**：OilPaintingPlatform 的 base_url+env Key 外泄（critical）；TechLearnStudio 的 LLM→v-html XSS 链（hyperframes.js 转义四处漏风 + anim 端点参数注入）；HistorySandbox 的 LLM 输出净化标准不统一。
- **SQLite 并发**：GestureCoach（4 处 check_same_thread=False 无锁）、TechLearnStudio（未开 WAL）、OilPaintingPlatform（gallery.json 读改写竞争）——同一模式在 3 个项目重复出现。

### 2. LLM 调用层的系统性缺陷（4 个项目）
- **无超时**：GestureCoach glm_client（可阻塞 30s+ 且在 GUI 线程）、OilPaintingStudio llm_client（4xx 也重试 6 次）。
- **输出不校验**：TechLearnStudio（形状任意直达前端白屏）、HistorySandbox（非 dict JSON→500）、GestureCoach（三套 JSON 提取逻辑不一致）。
- **静默降级**：TechLearnStudio `available` 恒 True、OilPaintingStudio `except (ImportError, Exception)` 吞掉推理错误降级 mock、GestureCoach `except: pass` 零日志——"mock 冒充真模型"是贯穿性风险。

### 3. 前端渲染层的 Three.js 资源治理（3 个项目）
- dispose 不完整/监听器泄漏：ArtRealm3D（backdrop/画框不释放）、HistorySandbox（window 监听器 + CanvasTexture 泄漏）、OilPaintingStudio（PLY 加载失败静默）。
- **前端全部零测试**：7 个项目中 5 个前端（Vue/Three.js）无任何测试，本次发现的多数 high 级 bug（stale 旁白竞态、bootstrap 失败固化、标签不渲染）都落在该盲区。

### 4. 数值算法的边界防御（DotArtKit 集中）
- 全零密度死循环、GridHash 查询半径超 cell 漏检、cumsum 质心 x 方向系统性偏移 ≥1px（已数值复核）——全部位于 ops 层零直接单测的盲区。

### 5. 状态/缓存签名的完整性
- ArtRealm3D 缓存签名不含代码（已实证危害）；TechLearnStudio 版本增量是假的（全帧 version+1 + 死模型）；HistorySandbox 连续推演不累积。

## 各项目优先改进 Top 1 汇总

| 项目 | 最高优先项 | 严重程度 |
|---|---|---|
| DotArtKit | 统一特征通道符号约定，修 luminance/hybrid 反向（现有测试把 bug 固化了） | high |
| OilPaintingStudio | 补完 cv2 中文路径替换（stage3/4/5 + common ~25 处）并加中文路径端到端回归 | high |
| GestureCoach | 补 `CameraPanel.set_comm`（5 行）让 v4 在真实 Krita 活过来 | critical |
| ArtRealm3D | 缓存签名纳入 renderer.py 代码哈希（附旧目录 GC + 回归测试） | high |
| HistorySandbox | 实现 3D 古地名标签渲染（Sprite 方案 ~60-80 行，数据已备好） | high |
| OilPaintingPlatform | 堵凭据泄露链：env Key 与客户端 base_url 互斥 + 限流 | critical |
| TechLearnStudio | 修前端渲染转义链（escapeHtml 补引号 + DOMPurify + 参数校验） | high |

## 建议的修复批次

1. **批次一（安全，先行）**：OilPaintingPlatform 凭据链、TechLearnStudio XSS 链、GestureCoach set_comm。
2. **批次二（正确性）**：DotArtKit 特征通道方向 + 退化输入防护、OilPaintingStudio 中文路径、HistorySandbox LLM 校验 + 标签渲染、ArtRealm3D 缓存签名 + stroke no-op。
3. **批次三（健壮性/体验）**：各项目 LLM 超时与日志、Three.js dispose、并发锁、前端最小测试基建（vitest 覆盖计时器/竞态/状态机）。

每条修复建议的具体设计与代码示例见各项目子报告。
