# Famous Painting Dynamic Video-Style Generation — LaTeX Survey (IJCAI'26)

世界名画动态视频风格生成技术调研，采用 **IJCAI--ECAI 26** 官方模板，并新增了 4 个研究方向 idea。

## 目录结构

```
FamousPaintingVideoStyle/
├── main.tex          # 主文件（IJCAI'26 模板 + 标题/摘要 + \input 各章节）
├── main-bak.tex      # 原始调研正文（备份，单文件版本）
├── references.bib    # 参考文献库（约 35 篇顶会论文）
├── ijcai26.sty       # IJCAI'26 样式文件
├── ijcai26.bib       # IJCAI'26 模板自带 bib
├── named.bst         # IJCAI 推荐的 bibstyle
├── main.pdf          # 编译产物（7 页）
└── sec/              # 各章节独立文件
    ├── intro.tex         # 1. Introduction
    ├── style.tex         # 2. Foundations of Artistic Style Transfer
    ├── video.tex         # 3. Video Style Transfer and Temporal Consistency
    ├── diffusion.tex     # 4. Diffusion Models for Image and Video Generation
    ├── painting.tex      # 5. Painting Synthesis and Stroke Rendering
    ├── artstyle.tex      # 6. Art-Style-Specific Methods: Oil and Ink Wash Painting
    ├── portrait.tex      # 7. Portrait and "Talking Painting" Animation
    ├── discussion.tex    # 8. Discussion and Open Challenges
    ├── ideas.tex         # 9. Proposed Research Ideas（4 个创新 idea）
    └── conclusion.tex    # 10. Conclusion
```

## 编译方法

本文档使用了中文艺术术语（焦、浓、重、淡、清 等），需要用 **XeLaTeX** 编译：

```bash
xelatex main.tex
bibtex  main
xelatex main.tex
xelatex main.tex
```

> 若改用 pdflatex，需移除 `sec/ideas.tex` 中的中文字符，或改用其他 CJK 方案。
> `main.tex` 已对 `\pdfinfo` 加了 `\ifdefined` 守卫，XeLaTeX / pdfLaTeX 均可编译。

## 4 个创新研究方向（sec/ideas.tex）

每个 idea 均满足 4 个要求：①使用开源本地视频生成模型（LTX-Video 2.x / Wan2.1/2.2-I2V）；
②接受手绘艺术草稿（线稿、色块等）作为人工艺术指引；③提供精确或模糊的控制
（基于颜色分布、线稿分布、手绘色块）；④引入艺术创作领域的创新点。

| Idea | 名称 | 开源骨干 | 人工草稿 | 控制粒度 | 艺术创新点 |
|------|------|----------|----------|----------|------------|
| I1 | Stroke-Anchored Co-Painting Video | Wan2.1 / LTX | 笔触草稿 + 色块 | 精确 + 模糊 | 油画"肥盖瘦"分层课程 |
| I2 | Palette-and-Line Dual-Conditioned Ink-Wash | Wan2.1 | 线稿 + 墨密度图 | 精确 + 模糊 | 五色墨理论、留白损失 |
| I3 | Sketch-to-Painting-Video (Fuzzy→Precise) | LTX | 草图→色块→细节 | 模糊到精确旋钮 | 学院派工作流、黄金分割损失 |
| I4 | Living-Canvas 多区域协同动画 | Wan2.1 / LTX | 区域脚本 + 箭头 | 分区混合粒度 | 主从虚实焦点编排 |

## 调研覆盖（按四条主线）

1. **艺术风格迁移基础** — Gatys NST (CVPR'16)、Perceptual Losses (ECCV'16)、AdaIN (ICCV'17)、SANet (CVPR'19)、StyTr² (CVPR'22)
2. **视频风格迁移与时序一致性** — Artistic VST (GCPR'16)、Coherent Online VST (ICCV'17)、Real-Time NST (CVPR'17)、Compound Regularization (AAAI'20)、Arbitrary VST (AAAI'21)、ReCoNet (ECCV'18)
3. **扩散模型图像/视频生成与风格化** — LDM、ControlNet、DreamBooth、LoRA、InST (CVPR'23)、ArtAdapter (CVPR'24)、StyleMaster (CVPR'25)、EchoStyle (ECCV'26)、RefVFX (ECCV'26)、Pix2Video/StableVideo/TokenFlow (ICCV'23)、CoDeF/FlowVid (CVPR'24)、Tune-A-Video
4. **绘画合成、笔触渲染与「名画动起来」** — Painting Many Pasts (CVPR'20)、Stylized Neural Painting (CVPR'21)、Neural Strokes (ICCV'21)、Data-Driven Ink Painting、LivePortrait、EDTalk (ECCV'24)、MEAD (ECCV'20)

**艺术风格专项：**
- **油画**（梵高、莫奈、伦勃朗、透纳）
- **水墨画/中国山水画** — Instance-Aware Coherent VST (IJCAI'21)、BiTGAN、CVSTGAN、ChipDiff、InkSpirit、End-to-End Chinese Landscape Painting (WACV'21)
