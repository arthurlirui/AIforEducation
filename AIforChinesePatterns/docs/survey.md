# 中国传统纹样生成与再创作 —— 调研报告

> 项目：AIforChinesePatterns · 版本 v0.1 · 日期 2026-11-10
> 定位：软件算法 + 大语言模型（LLM）+ 扩散模型（Diffusion）用于中国传统纹样的**生成**与**再创作**

---

## 1. 研究版图总览

把"LLM + Diffusion 生成传统纹样"这个方向拆开，现有工作可以归为五大类：

| 板块 | 代表工作 | 与本项目的关系 |
|---|---|---|
| A. 传统纹样直接生成（领域微调） | Miao batik LoRA (Multimedia Systems 2026)、Miao embroidery SD+LoRA (Sustainability 2025)、CTDPD/Wide Diffusion (CSCWD 2025)、非遗情感风格框架 | ⭐ 最接近的"同题"工作，但普遍停留在 LoRA 风格微调 |
| B. 结构 / 几何先验注入 | Structure-aware 少样本纹样生成 (ICCSIE 2025)、DANet 敦煌 cross-attention、ControlNet/T2I-Adapter、Dunhuang 情绪向量风格矩阵 | 提供可控性的技术底座 |
| C. LLM 驱动的设计规划 | LayoutLLM-T2I (MM'23)、LayoutPrompter (NeurIPS'23)、南京云锦智能体框架 (2026)、Co-DSL (TOG'26) | ⭐ "软件算法结合大模型"的核心范式——LLM 做规划、diffusion 做渲染 |
| D. 平铺 / 对称 / 无缝纹样 | MultiDiffusion (ICML'23)、Tiled Diffusion (CVPR'25)、DepthTile (2026)、DiCoT 纹织品无缝图案、Generative Escher Meshes (SIGGRAPH'24)、17 wallpaper groups | 纹样的**独有需求**：对称群、四方连续、可平铺 |
| E. 矢量 / 可编辑输出 | StarVector (AAAI'25)、IconShop、SVGDreamer、VectorFusion、DiffSketcher、LLM-SVG 综述 | 再创作的**工程出口**：可编辑 SVG、面向文创/印刷 |

此外有一条**文化遗产修复**支线（DiffuMural 敦煌壁画修复，npj Heritage Science 2026）值得关注其评测协议，但不是我们的主战场。

---

## 2. 关键工作分述

### 2.1 板块 A：传统纹样的领域化生成（我们的直接竞品/基线）

**Miao batik SD+LoRA 自动生成**（Guo, Tian & Ning, *Multimedia Systems* 32(5), 2026）
- 构建了较早的苗族蜡染文生图数据集（图像+文本描述对），在 SD 上加 LoRA 承载蜡染风格，并改网络结构丰富特征；FID/IS + 专业/非专业双组主观评分（>3.8/5）。
- **启示**：数据集+LoRA+双轨评测是这一领域论文的标准模板；其自述局限是"色彩单一"，多色纹样是明确的后续空间。

**Miao embroidery SD+LoRA 可持续设计**（Yu, Tao & Wang, *Sustainability* 17(17):7657, 2025）
- 完整链路：图像预处理→标注→LoRA 训练→纹样生成→**数字化刺绣落地**（参数化后上刺绣机），含 5 种代表性绣种、绣娘反馈；LoRA scale 0.8–1.2、20–40 步最优。
- **启示**：这是"生成之后做什么"的最佳参照——生成结果要能参数化、能上生产线，评测要包含从业者。我们的"再创作"环节应对标这种端到端闭环。

**Batik-MPDM：Style-Conditioned LCM-LoRA**（Hu et al., *Mathematics* 13(12):1947, 2025）
- 构建 CMBP-9 结构化九类苗族蜡染语义数据集；LoRA（风格）+ LCM（少步快采样）+ SCLF 按提示词语义复杂度动态调整融合权重；LPIPS/SSIM/PSNR/FID + 人工评测。
- **启示**：交互式创作需要 LCM 这类少步蒸馏；"按语义复杂度动态调权"是一个轻量但有效的算法创新点样板。

**Wide Diffusion / CTDPD**（Li et al., CSCWD 2025）
- 自建中国传纹样数据集 CTDPD，Wide AutoEncoder 扩大感受野，FID 5.45。属于"改 backbone 换领域"的老思路，价值主要在数据集。

**结构感知少样本纹样生成**（Lei et al., ICCSIE 2025）
- 面向青花瓷/敦煌/苗族蜡染各仅 20 张 512×512 图的极端少样本：Canny 边缘→多尺度结构引导适配模块（SGAM，新增参数 <5%）+ 高频细节重建 + 类先验保持 + CLIP 语义一致性四重损失，冻结主干；KID 6.5→2.3，LPIPS +31%。
- **启示**：⭐ 极重要。传统纹样的核心瓶颈就是**数据稀缺 + 结构精细**，这篇证明了"结构先验注入 + 多损失对齐"比 DreamBooth/Textual Inversion/LoRA 裸用都强。基线选取（DreamBooth/TI/LoRA/DomainStudio）可直接复用。

**多模态 Transformer + 对比学习非遗纹样生成**（Hua, AIVRID 2026）
- 文化特征编码器（CFE）提取文化符号 + 多模态 Transformer 建模全局结构 + 对比学习优化特征空间，对标 CycleGAN/StyleGAN2 提升 FID/SSIM/**文化一致性得分**。
- **启示**：引入"文化语义"显式表征并单独评测（cultural consistency score），是这个领域区别于普通文生图的关键评价指标。

### 2.2 板块 B：结构/几何先验与可控条件

- **ControlNet**（Zhang et al., ICCV 2023）/ **T2I-Adapter**（Mou et al., AAAI 2024）：边缘/分割/深度等空间条件注入的两大标准件，训练只需 <50k 数据也稳健——是纹样骨架控制的第一选择。
- **DANet**：面向敦煌纹样的 cross-attention 适配机制（板块 A 那篇 ICCSIE 文章引用为 [10]），结构先验有效性的早期验证。
- **Dunhuang 情绪-风格协同生成**（Song, *IJCIS* 2026）：多模态编码器把文本+语音融合成 128 维情绪向量 + LSTM 母题周期性估计 → 4 个可解释风格参数（色彩饱和度/纹样密度/构图对称性/笔触密度）经对角风格矩阵、cross-attention style tokens、FiLM/AdaIN 注入 LDM；6000 张专家标注敦煌数据集，文化符号准确率 82.2%。
  - **启示**：把高层语义（情绪）编译成**少量可解释的风格参数**再注入生成，是"LLM/语义 → 几何/风格控制"的漂亮中间表示，思路可迁移到"朝代/品类/寓意"等纹样属性。
- **DiffuMural**（Han et al., npj Heritage Science 14:44, 2026）：敦煌壁画大缺损修复，损伤轮廓自引导 + 多尺度协同扩散 + 频域细化；25 个唐窟 65 万样本；除 PSNR/SSIM/FID/LPIPS 外提出**人文学价值评估协议**（专家盲评风格真实性/语义连续性/符号合理性，96.7 分）。
  - **启示**：其"专家人文评估协议"值得借鉴到我们的评测体系——纹样生成本质上也是"无 ground truth 的生成任务"。

### 2.3 板块 C：LLM 驱动的规划与编排（本项目"软件算法结合大模型"的核心）

- **LayoutLLM-T2I**（Qu et al., ACM MM 2023）：LLM in-context learning 从 prompt 生成粗粒度布局 → 布局条件扩散生成图像，解决文生图空间关系/计数错误。**coarse-to-fine：LLM 规划 → diffusion 渲染**这一范式在此确立。
- **LayoutPrompter**（Lin et al., NeurIPS 2023）：纯提示工程（输入输出序列化 + 动态示例选择 + 布局排序）让 LLM 零训练达到 SOTA 布局生成；小数据场景显著优于训练基线。
  - **启示**：纹样"构图法则"（如二方连续/四方连续骨架、边框-中心层级、疏密节奏）完全可以序列化成 LLM 可生成的结构化中间表示。
- **智能体驱动的非遗纹样可控迁移——南京云锦**（陈涛等，农业图书情报学报 2026，网络首发）：⭐ 与我们设想最接近的中文工作。以 Hermes Agent 为认知中枢，把纹样迁移拆成"语义解析 → 文化基因层级优先级判定 → 生成参数编译"三层指令，统一调度感知编码与生成解码；**四层文化基因体系**（表象/技艺/语义/精神）作为结构化约束贯穿全流程；以云锦"妆花"为实证，用纹样语义保留率、廓形保留率、实例色彩准确率三个自定指标 + 消融验证，压制文化语义混淆/结构失真/色彩规律丢失三大不稳定性。
  - **启示**：把文化知识形式化为**可执行的生成约束**（提示词、结构条件、LoRA 调度、工作流参数），"知识解耦-认知调度-多条件可控生成"三段式，是本项目的直接对标框架；也提示了"文化知识库/知识图谱"应作为系统的一个一等公民组件。
- **Co-DSL**（Jones, Wu & Agrawala, TOG/SIGGRAPH Asia 2026）：用户与 LLM **协同设计可复用的空间概念库**（DSL 操作），LLM 只负责声明"哪些概念成立"，由求解器搜索满足约束的布局；概念图 + 概念级报错驱动程序自修复。
  - **启示**：把纹样构图法则做成**可复用、可组合的算子库**（LLM 组合、求解器保证合法性），比让 LLM 直接画坐标可靠得多。"LLM 写程序、程序保证结构合法"是软件算法与大模型结合的高级形态。
- **磁州窑/杨柳青年画显性基因提取 + 数字重构**（见云锦文综述）：国内已有"文化基因→提示词/LoRA→文创应用"的实践链。

### 2.4 板块 D：平铺、对称与无缝（传统纹样的独有几何需求）

中国传统纹样大量依赖**对称与连续**（四方连续、二方连续、团花、藻井对称），这是它区别于一般文生图任务的本质结构属性，但现有"纹样+LoRA"工作几乎都不处理：

- **MultiDiffusion**（Bar-Tal et al., ICML 2023）：重叠窗口平均预测 → 大图/无缝平铺生成的通用底座。
- **Tiled Diffusion**（Madar & Fried, CVPR 2025）：周期边界 latent 上下文交换，实现给定图像自平铺。
- **DepthTile**（2026）：深度先验转空间保护图 + 差分扩散掩码，解决"平铺性 vs 内容保持"的权衡，并提出输入侧可平铺性预测分数 STAS。
- **DiCoT**（IEEE 2026）：双尺度动态上下文做**纺织纹样**无缝图案生成——与我们的场景（织物/壁纸/包装）最贴近。
- **Generative Escher Meshes**（Aigerman & Groueix, SIGGRAPH 2024）：基于 17 个 wallpaper 对称群的 Orbifold Tutte Embedding 可微参数化 + diffusion SDS 损失，生成非方形、无缝、周期性的拼贴单元。
  - **启示**：⭐ 这是把**群论**和 diffusion 结合的标杆。中国传统纹样同样有系统的对称骨式（米字格、井字格、对称/旋转/反射），"wallpaper group 条件化"是几乎无人做过的差异化创新点。
- 早期还有 **Periodic Spatial GAN**（ICLR 2017）等用周期 padding 强制无缝的老方法，实现成本最低。

### 2.5 板块 E：矢量与可编辑输出（再创作的工程出口）

"再创作"意味着设计师要能改：改色、换单元、换构图、上印刷。这要求**矢量**：

- **StarVector**（Rodriguez et al., AAAI 2025）：CLIP 图像编码 + Code-LLM 自回归生成 SVG 代码，SVG-Stack 200 万对训练，image-to-SVG / text-to-SVG 双任务，SVG-Bench 评测。
- **IconShop**（Wu et al., TOG 2023）：自回归 Transformer 文本引导矢量图标合成。
- **SVGDreamer / VectorFusion / DiffSketcher**：diffusion SDS 损失驱动 SVG 原语优化（质量高但慢）。
- **LLM-SVG 综述**（Malashenko et al., 2025）：IconShop/StrokeNUWA/StarVector 三系 + SVGEditBench/VGBench/SGP-Bench 基准；结论是推理增强 LLM 在 SVG 生成/理解上更强，且领域数据集仍稀缺。
  - **启示**："纹样 → 结构化 SVG（分层、可替换单元、对称组标注）"若能打通，就是从"生成一张图"升级为"生成一个可编辑的设计资产"，工程价值和论文新颖性都高。VTracer 等传统矢量化工具可作为 pipeline 兜底。

---

## 3. 技术趋势与空白点（研究机会）

1. **"LoRA + 数据集"已饱和，结构/知识驱动是下一程**。板块 A 的论文套路高度同质（自建数据集 → SD+LoRA → FID/IS + 问卷）。单做某个绣种的 LoRA 已没有新颖性；新颖性在"如何把纹样的**结构法则与文化语义**变成可执行的生成控制"。
2. **LLM 规划 + diffusion 渲染的 coarse-to-fine 管线**（LayoutLLM-T2I、云锦 Agent）在纹样领域刚起步，且现有工作的"中间表示"偏粗糙（提示词/布局框）。机会：设计一个**纹样专用的结构化中间表示**（骨架类型 + 母题实例 + 排布规则 + 色彩制度），LLM 生成它、程序校验它、diffusion/ControlNet 渲染它。
3. **对称/平铺约束与 diffusion 的结合**在通用领域（MultiDiffusion、Escher Meshes）已成熟，但**没人针对中国传统纹样的骨式体系**（四方连续、藻井放射对称、团花）做条件化。这是清晰的空白。
4. **评测体系薄弱**：现有工作用 FID/IS/CLIP-score + 小规模问卷，缺少 (a) 文化/结构一致性的自动指标，(b) 对称性/平铺性的几何度量，(c) 专家人文评估协议（DiffuMural 提供了模板）。
5. **矢量再创作链路缺失**：几乎所有纹样工作止步于 raster 输出；"生成→结构化矢量→设计软件可编辑"是工程空白。
6. **少样本**是常态而非例外（很多品类只有几十张可用图），Structure-aware ICCSIE 2025 一路线（结构先验+多损失+冻结主干）应作为方法底座之一。

---

## 4. 对本项目的架构建议（三层管线）

```
┌─────────────────────────────────────────────────────────┐
│ L1 语义层（LLM / Agent）                                  │
│  · 文化知识库：品类/朝代/母题语义/色彩制度/构图骨式          │
│  · 任务解析：需求 → 纹样规格说明（Pattern Spec，结构化 JSON）│
│    { 骨架类型, 对称群, 母题列表, 排布规则, 色彩制度, 寓意 }  │
├─────────────────────────────────────────────────────────┤
│ L2 结构层（软件算法，规则可验证）                           │
│  · 骨架求解器：由 Pattern Spec 生成骨架图/单元排布           │
│    （对称群约束求解、四方连续网格、边框-中心布局）            │
│  · 程序化校验 + 修复：对称性/连通性/密度检查，失败回 L1 重规划 │
├─────────────────────────────────────────────────────────┤
│ L3 渲染层（Diffusion）                                    │
│  · 领域 LoRA（风格） + ControlNet（骨架条件）               │
│  · 平铺/对称感知采样（MultiDiffusion 式窗口或周期 padding）  │
│  · 可选：LCM 少步蒸馏做交互；SVG 矢量化出口做再创作          │
└─────────────────────────────────────────────────────────┘
```

这个架构的每一层都有上面的文献支撑（云锦 Agent 验证 L1、Co-DSL/LayoutPrompter 验证"LLM 出结构化中间表示+求解器"、ICCSIE 结构感知与 ControlNet 验证 L3、MultiDiffusion/Escher 验证平铺对称），组合起来针对中国传统纹样做领域化，是站得住的定位。

## 5. 建议的实施路线

1. **M0 数据与知识整理**：选定 2–3 个品类（建议：敦煌藻井纹 [对称丰富、有公开资源]、苗族蜡染 [有 CMBP-9 等可对标数据]、云锦/苏绣织造纹 [结构严谨]），整理图像 + 结构标注（骨架类型/对称群/母题标签），并构建纹样文化知识条目。
2. **M1 基线复现**：SD + LoRA 直出（对标板块 A 各文），确立 FID/KID/CLIP-score + 专家评估双轨基线。
3. **M2 骨架条件生成**：实现 Pattern Spec → 骨架图 → ControlNet 渲染，对比"无结构先验"消融（对标 ICCSIE 2025 的结论）。
4. **M3 对称/平铺感知采样**：加入周期约束采样，输出可四方连续的纹样并给出几何度量。
5. **M4 LLM 规划闭环**：接入 LLM 生成 Pattern Spec + 校验-重规划循环（对标云锦 Agent、Co-DSL）。
6. **M5 再创作出口**：SVG 结构化矢量化 + 编辑器 Demo（改色/替换单元/重排布），有条件则做文创落地（对标 Miao embroidery 的刺绣机闭环）。

## 6. 评测体系设计（综合各文献）

- **图像质量**：FID / KID / IS（对齐板块 A 通行做法）
- **文图一致性**：CLIP-score（各文通行）
- **结构一致性**：对称性度量（镜像/旋转自相关损失）、平铺接缝度量（Tiling Score，见 DepthTile）、边缘/骨架 IoU
- **文化一致性**：母题分类器准确率（训练一个小分类器判别品类/母题是否正确）、色彩制度符合率（对照知识库色板）
- **人文评估**：专家盲评协议（风格真实性 / 语义合理性 / 创新度），参照 DiffuMural；加非专业用户偏好
- **工程指标**：推理步数/延迟（用 LCM 后）、SVG 可编辑率（路径数、分层完整性）

## 7. 风险与注意

- **版权与伦理**：敦煌研究院等机构图像有使用限制；非遗传承人社区的知情与获益是学术上越来越被审视的点（多篇 Sustainability/npj 文章专门讨论），项目应从数据收集起就记录来源与授权。
- **"文化误用"风险**：生成结果可能混搭不兼容的符号（云锦文所述"文化语义混淆"），这正是 L1 知识约束要解决的问题，也应在评测中显式检查。
- **少样本现实**：多数品类凑不出大数据集，方法设计必须以"冻结主干 + 轻量适配 + 结构先验"为前提。

## 8. 核心文献清单（速查）

| # | 工作 | 出处 | 关键词 |
|---|---|---|---|
| 1 | Miao batik SD+LoRA | Multimedia Systems 2026 | 蜡染、LoRA、文生图数据集 |
| 2 | Miao embroidery LoRA 可持续设计 | Sustainability 2025 | 刺绣落地闭环、从业者评测 |
| 3 | Batik-MPDM (LCM-LoRA+SCLF) | Mathematics 2025 | 少步蒸馏、CMBP-9 数据集 |
| 4 | Wide Diffusion / CTDPD | CSCWD 2025 | 领域数据集 |
| 5 | Structure-aware 少样本纹样生成 | ICCSIE 2025 | 结构先验、四重损失、20 样本 |
| 6 | 多模态 Transformer+对比学习 | AIVRID 2026 | 文化特征编码器 |
| 7 | 智能体驱动云锦纹样迁移 | 农业图书情报学报 2026 | Agent、文化基因四层体系 |
| 8 | Dunhuang 情绪-风格矩阵 | IJCIS 2026 | 可解释风格参数、FiLM/AdaIN |
| 9 | DiffuMural | npj Heritage Science 2026 | 壁画修复、人文评估协议 |
| 10 | LayoutLLM-T2I | ACM MM 2023 | LLM 布局规划→扩散渲染 |
| 11 | LayoutPrompter | NeurIPS 2023 | 纯提示工程布局生成 |
| 12 | Co-DSL | SIGGRAPH Asia/TOG 2026 | LLM+DSL 概念库+求解器 |
| 13 | ControlNet | ICCV 2023 | 结构条件注入 |
| 14 | T2I-Adapter | AAAI 2024 | 轻量条件适配 |
| 15 | MultiDiffusion | ICML 2023 | 窗口融合、大图平铺 |
| 16 | Tiled Diffusion | CVPR 2025 | 周期边界自平铺 |
| 17 | DepthTile | arXiv 2026 | 深度保护、STAS |
| 18 | DiCoT | IEEE 2026 | 纺织无缝图案 |
| 19 | Generative Escher Meshes | SIGGRAPH 2024 | wallpaper 群、SDS |
| 20 | StarVector | AAAI 2025 | image/text-to-SVG、SVG-Bench |
| 21 | IconShop | TOG 2023 | 自回归矢量图标 |
| 22 | LLM for SVG 综述 | arXiv 2025 | SVG 生成/编辑/理解全景 |
| 23 | 情感化灯具纹样图语法+扩散 | AIVRID 2025/2026 | 图语法结构编码 |
| 24 | AIGC 敦煌纹样数字转译 | DSAI 2026 | SD/MJ/DALL·E 3 平行对比 |
| 25 | AIGC 纹样创新双路径 (Baoxiang) | npj Heritage Science 2025 | Shape Grammar vs DDPM 对比 |

---

*下一步：按 §5 路线启动 M0（品类选型与数据资源盘点）。*
