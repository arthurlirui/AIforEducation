# IJCAI 2027 三篇论文投稿推进状态

## 总览

| 编号 | 论文 | 路径 | 完成度 | 关键瓶颈 |
|---|---|---|---|---|
| P1 | Depth-as-Radius: Kusama-Style Polka Dot Generation | `AIforPolkaDotsArt/paper/` | 85% | 补 30 张图实验 + baseline 对比 + user study |
| P2 | InkFlow: Dual-Conditioned Video Diffusion for Ink-Wash | `latex/InkFlow/` | 40% | 实现 + 跑实验（最大工作量） |
| P3 | GestureCoach: Real-time Painting Technique Feedback | `GestureCoach/latex_ijcai/` | 80% | IRB + 用户研究数据采集 |

## 本次完成的修改

### P3 GestureCoach（最高优先级）

1. **LaTeX 模板切换**: 从 CVPR (`cvpr.sty`) → IJCAI (`ijcai26.sty`)
   - 新建 `GestureCoach/latex_ijcai/` 完整论文目录
   - 7 个 sec 文件: introduction, related, method, experiments, results, discussion, conclusion
   - `references.bib` 替换所有 "as cited" 占位符为结构化引用
   - 摘要 + 全文内容从 markdown 版迁移到 IJCAI LaTeX

2. **IRB 申请文档完善** (`GestureCoach/data_collection/01_IRB_application.md`):
   - 更新申请日期为 2026-10-15
   - 补充具体酬金金额（艺术家 ¥500/人，初学者 ¥800/人）
   - 新增 §10 时间线表（IRB→录制→实验→分析→投稿，对齐 IJCAI 2027 截稿）

3. **待补数据位置明确标注**:
   - `sec/results.tex` 中所有合成数据结果标记 $^\dagger$
   - §5.2 Learning Effects 和 §5.3 User Perception 标注 "[Results pending user study]"
   - 新增 §5.4 Status of Pending Data 列出三项必须完成的数据采集活动

4. **AI 方法 novelty 强化**:
   - Introduction 贡献列表明确提及 Bi-GRU + ST-GCN 阶段分割模型
   - Discussion 新增 rigid vs. elastic ablation 实验建议

### P1 Spatially-Aware Stippling

1. **可学习 depth-to-dot 映射** (`AIforPolkaDotsArt/learned_radius.py`):
   - `DepthRadiusNet`: 4 层 CNN (~47K 参数)，输入 depth+luminance+梯度，输出 radius+density
   - `StipplePerceptualLoss`: 4 项损失（depth 对齐 + 覆盖率 + 直方图匹配 + 平滑性）
   - `train_depth_radius_net()`: 自监督训练循环
   - `learned_depth_to_radius()` / `learned_depth_to_density()`: 现有 pipeline 的 drop-in 替换
   - `compare_fixed_vs_learned()`: 消融对比工具
   - 自测通过

2. **实验扩充脚本** (`AIforPolkaDotsArt/run_ijcai_experiments.py`):
   - 4 种方法: Secord baseline / AdaIN baseline / 固定公式 / 可学习
   - 6 类 30 张测试图配置
   - 批量实验 runner + 定量指标 (n_cc, b_max, coverage)
   - 感知用户研究协议生成 (2AFC + Likert + 问卷 JSON)
   - 消融表 LaTeX 自动生成

3. **论文修改**:
   - `sec/method.tex`: 新增 §Learnable Depth-to-Radius Mapping 小节
   - `sec/introduction.tex`: 贡献列表新增可学习组件；结尾加入 AI for Art Process framing
   - `sec/related.tex`: 压缩 stippling 子节（删除 halftoning 和冗余引用描述）
   - `sec/discussion.tex`: Future Directions 从 5 条压缩到 2 条
   - `sec/experiments.tex`: 实验设置从 3 张图改为 30 张图 + 3 方法对比；新增 Perceptual User Study 小节

### P2 InkFlow（重构为方法论文）

1. **完整论文骨架** (`latex/InkFlow/`):
   - `main.tex`: IJCAI 模板，标题 "InkFlow: Dual-Conditioned Video Diffusion for Chinese Ink-Wash Painting with Five-Level Ink Theory"
   - `sec/introduction.tex`: 五墨理论 + 留白 + 计白当黑 问题定义，3 个核心 idea，4 项贡献
   - `sec/related.tex`: I2V 扩散 / 水墨风格化 / 可控扩散 / 内容变形场 4 个子节
   - `sec/method.tex`: 完整方法——双阶段条件注入 (line map 早期 + ink-density 后期) + 五墨直方图 EMD 匹配 + 留白 loss + 运笔节奏 prior + 训练目标 + 实现细节
   - `sec/experiments.tex`: 30 张水墨画数据集 + 4 方法对比 + 5 指标 + user study 协议
   - `sec/discussion.tex` + `sec/conclusion.tex`
   - `references.bib`: 13 条结构化引用

### 跨论文统一 framing

三篇论文的 introduction 均包含 "AI for Art Process" 主线段落：
- P1: "AI to understand and intervene in the creative process"
- P2: "AI to understand and extend the creative process"
- P3: "AI to understand and intervene in the creative process of art-making"

## 下一步行动（按紧急度排序）

### 立即（本周）
- [ ] **P3: 提交 IRB 申请** — 这是 critical path，4 周审批周期
- [ ] **P1: 准备 30 张测试图** — 放入 `AIforPolkaDotsArt/test_images/`，6 类各 5 张
- [ ] **P1: 运行 `python learned_radius.py`** 自测 → 训练模型 → 保存 `learned_radius_model.pt`

### 11 月
- [ ] **P3: IRB 审批中；录制 ≥5 位画家参考数据**
- [ ] **P1: 运行 `python run_ijcai_experiments.py --mode batch`** 跑全部实验
- [ ] **P1: 运行 `python run_ijcai_experiments.py --mode study`** 部署用户研究
- [ ] **P2: 收集 30 张水墨画 + 标注 line/ink/blank masks**
- [ ] **P2: 在 OilPaintingVideo ComfyUI pipeline 上实现双条件 adapter**

### 12 月
- [ ] **P3: 执行用户研究** (30-40 人, 4 组, 2 周)
- [ ] **P1: 填入实验数据，完成论文定稿，压缩到 7 页**
- [ ] **P2: 跑实验 + 定量指标 + user study**

### 1 月
- [ ] **P3: 分析用户数据，填入 §5.2/5.3，完成投稿**
- [ ] **P1: 投稿 IJCAI 2027**
- [ ] **P2: 完成论文定稿，投稿 IJCAI 2027**
- [ ] IJCAI 2027 abstract 截稿 (~01-12) → full paper (~01-19)
