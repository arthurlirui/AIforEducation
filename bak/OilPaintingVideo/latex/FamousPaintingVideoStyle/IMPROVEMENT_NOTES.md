# OilPaintingRevive 论文完善意见

> 论文初稿已完成，编译产物为 `paper.pdf`（10页）。以下按优先级列出完善建议，供下一轮修订参考。

## 一、页数与格式（IJCAI'26 投稿要求）

**当前状态：** 10页（正文约8页 + 参考文献2页）。IJCAI'26 要求正文7页 + 参考考文献不限（或2页），camera-ready 9页含参考文献。

### 建议
1. **压缩至7页正文。** 目前 Method 和 Experiment 部分偏长，可考虑：
   - 将 Complementary Screenplay-Driven Pipeline（Section 3.7）压缩为1段或移至 Appendix，因为它是补充系统而非核心贡献。
   - 将 VRAM Budget 表格（Table 5）移至 supplementary material。
   - 合并 Ablation 中的两个表格为一个，减少行数。
2. **添加 Ethics Statement**（IJCAI 要求）。涉及名画生成，需声明：仅使用公开画作、生成内容标注为AI生成、不用于伪造。
3. **添加 Reproducibility Statement**，说明代码和数据将开源。

## 二、实验部分（最需完善）

**当前状态：** 实验数据为基于设计文档阈值的合理估计值（placeholder），尚未在真实系统上运行。

### 建议
1. **替换为真实实验数据。** 这是投稿前最关键的工作：
   - 在真实 GPU 上运行完整 pipeline，收集 CLIP 相似度、骨架误差、深度误差的真实数值。
   - 当前表格中的数字（如 $S_\text{CLIP}=0.83$, $E_\text{skel}=2.1\%$）是基于设计阈值的估计，需替换为实测值。
   - 代码中的评估模块（`utils/eval.py`）当前使用 proxy 指标（颜色直方图而非CLIP），需接入真实 CLIP 计算。

2. **增加对比方法的公平性。**
   - LTX-Video I2V 和 Wan2.2 I2V 基线应使用相同的 prompt 和参数设置。
   - 考虑增加与 CoDeF + 风格迁移、TokenFlow 视频编辑的对比。
   - LivePortrait 仅适用于人像子集，应在表中明确标注适用范围。

3. **增加视觉对比图（Qualitative Results）。** 当前论文无任何图片，这是系统论文的重大缺陷：
   - 添加 Pipeline 架构图（Figure 1 的 fbox 占位符需替换为真实图）。
   - 添加输入画作 → 分层结果 → 3D 重建 → 粗渲染 → 最终视频的视觉对比。
   - 添加与基线方法的帧对比（side-by-side）。
   - 添加 novel-view 探索的连续帧展示。

4. **增加消融实验的深度。**
   - 消融 2DGS vs 3DGS 的差异。
   - 消融 TripoSplat 前景生成的贡献（有无前景 3D 物体）。
   - 消融 layer-wise depth normalization 的效果。
   - 消融不同 $\lambda$ 权重组合的影响。

5. **用户研究的规范化。**
   - 报告参与者背景分布、统计显著性（p-value）。
   - 使用 blind A/B 测试协议。
   - 增加 inter-rater agreement（如 Fleiss' kappa）。

## 三、Method 部分

**当前状态：** 五阶段描述完整，公式准确，算法伪代码已添加。

### 建议
1. **区分设计方法与代码实现的差距。** 论文描述的是设计文档中的方法，但部分代码实现使用 proxy：
   - 绑定网络代码使用 numpy ReLU（设计文档为 SiLU）。
   - 损失函数代码使用 proxy（颜色直方图而非CLIP，方差而非Chamfer距离）。
   - R³ 模型代码为 mock（arc trajectory）。
   
   **建议：** 投稿前将代码升级至与论文一致，或在论文中注明 "simplified proxy"。

2. **增加 2DGS 渲染的数学描述。** 当前对 2DGS 可微光栅化的描述过于简略，建议增加：
   - Surfel 投影到屏幕空间的公式。
   - Alpha-blending 合成公式。
   - 光度损失的具体形式（L1 vs MSE）。

3. **增加 Binding Network 的训练细节。**
   - 明确 warm-start 的交叉熵目标和后续 end-to-end 优化的区别。
   - 说明 K（骨骼数）如何确定（SMPL-X 的标准骨骼数 vs 通用骨架）。

4. **Stage 5 的 denoise=0.4 未在代码中实际注入。** `build_stage5b_workflow` 未将 `ltx_5b_denoise` 注入模板。论文中描述了这一参数，但代码存在 gap。需修复代码或在论文中调整描述。

## 四、Introduction 部分

**当前状态：** 结构完整，贡献清晰。

### 建议
1. **增加具体示例。** 开头可用一个具体场景引入（如"想象在博物馆中走近梵高的《星夜》，云朵开始流动，星星开始闪烁..."），增强可读性和吸引力。
2. **更明确地与 survey 论文区分。** 当前同目录下有一篇 survey 论文（`main-survey.tex`），需确保本文是一篇独立的技术贡献论文，而非 survey 的延伸。
3. **贡献点4（OilPaintingVideo）的定位。** 这是一个补充系统，作为主贡献之一可能让审稿人觉得核心不够聚焦。建议将其降级为"Extension"或在贡献列表中弱化。

## 五、Related Work 部分

**当前状态：** 四个子领域覆盖全面，约35篇引用。

### 建议
1. **增加最新的 3D-aware video generation 工作。** 如 4D Gaussian Splatting、单图到3D视频生成的最新进展。
2. **增加 cultural heritage digitization 的相关工作。** 这是应用领域的直接相关工作。
3. **增加 controllable video generation 的讨论。** 特别是 ControlNet for Video、MotionCtrl 等与本文 Stage 5 条件控制直接相关的工作。

## 六、参考文献

### 建议
1. **修正 bib 条目。**
   - `ltxvideo2024` 的作者和 arXiv 编号需核实。
   - `wan2025` 同上。
   - `xu2025r3` 的 arXiv 编号为占位符（`2503.xxxxx`），需填入真实编号。
   - `wang2024triposplat` 需确认是否已正式发表。
   - `kling2024` 引用可能不需要（商业闭源系统，与本文开源立场不符）。

2. **增加关键引用。**
   - NeRF 原始论文（Mildenhall et al., ECCV 2020）。
   - AnimateDiff（已在 bib 中但未引用）。
   - ControlNet for Video / MotionCtrl。

## 七、语言与表述

**当前状态：** 全文使用专业学术英语，表述清晰。

### 建议
1. **统一术语。** "surfel" 和 "2D Gaussian" 在文中交替使用，建议首次定义后统一。
2. **时态一致性。** Method 部分建议统一使用现在时描述方法。
3. **避免过度声称。** "the first to apply 2DGS to paintings" 需谨慎，建议改为 "to our knowledge, the first"。
4. **增加 notations 表格。** 五阶段涉及大量符号（$P$, $D$, $\mathcal{S}$, $\mathcal{K}$, $\mathbf{W}$, $\mathcal{B}_\theta$ 等），建议在 Method 开头添加符号表。

## 八、编译与文件组织

**当前状态：** 论文以 `paper.pdf`（jobname=paper）编译，原 survey 论文以 `main-survey.tex` 备份。

### 建议
1. **解决 PDF 锁定问题。** `main.pdf` 被外部程序锁定无法覆盖，当前使用 `-jobname=paper` 绕过。建议关闭 PDF 阅读器后，统一编译为 `main.pdf`。
2. **清理临时文件。** 编译产生了大量 `.aux`, `.log`, `.bbl` 等临时文件，建议加入 `.gitignore`。
3. **更新 README.md。** 当前 README 描述的是 survey 论文，需更新为研究论文的说明。

## 九、核心改进路线图（按优先级）

| 优先级 | 改进项 | 预计工作量 |
|--------|--------|------------|
| P0 | 替换实验数据为真实运行结果 | 3-5天 |
| P0 | 添加架构图和定性对比图 | 1-2天 |
| P0 | 压缩正文至7页 | 0.5天 |
| P1 | 修复代码与论文的 gap（denoise注入、CLIP评估） | 2-3天 |
| P1 | 增加消融实验深度 | 1-2天 |
| P1 | 补充 bib 条目的真实元数据 | 0.5天 |
| P2 | 增加符号表和 notations | 0.5天 |
| P2 | 规范化用户研究 | 1天 |
| P2 | 添加 Ethics/Reproducibility Statement | 0.5天 |
