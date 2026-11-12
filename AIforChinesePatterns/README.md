# AIforChinesePatterns

中国传统纹样的 AI 生成与再创作 —— 软件算法 + 大语言模型（LLM）+ 扩散模型（Diffusion）。

## 状态

- **2026-11-10** 项目创建，完成文献调研 → [docs/survey.md](docs/survey.md)
- **2026-11-11** 傅里叶纹样算法核心（`src/fcp/`）实现完成：曲线/轮廓/组合/渲染/部件分解五模块，
  49 测全绿，4 张 Demo 通过视觉验收 → [docs/design-fourier-pattern.md](docs/design-fourier-pattern.md)
- **2026-11-11** 桌面 GUI 论文 Demo（`src/fcp/gui/`）：图片加载 / OpenCV 预处理 /
  傅里叶分解 / 封闭线条填色，69 测全绿 → [docs/design-gui.md](docs/design-gui.md)

## 核心思想

用**椭圆傅里叶描述子（EFD）**表达封闭曲线，多条不同位置的傅里叶曲线
装配成一幅纹样。`PatternSpec` JSON 是纹样的完整结构化描述，
也是三层管线中 LLM 的直接生成目标：

```
L1  LLM 生成 PatternSpec（母题引用 + 摆放规则）
L2  规则求解/校验 + 傅里叶骨架渲染      ← 已实现 (src/fcp/)
L3  LoRA + ControlNet 对称感知扩散渲染   ← 规划中
```

## 快速开始

```bash
py -m pytest tests           # 69 tests
py -m fcp.gui                # 启动 GUI 编辑器（可带图片路径参数）
py demos/demo.py             # 谐波收敛 / 团花 / 栅格往返 → demos/output/
py demos/demo_decompose.py   # 掩膜 → 部件分解 → EFD 重建三联对比
```

```python
import sys; sys.path.insert(0, "src")
from fcp import CurveLibrary, Pattern, Placement, render_pattern

pattern = Pattern(
    motifs={"petal": CurveLibrary.petal(n_petals=8, order=14),
            "dot": CurveLibrary.circle(0.3, order=3)},
    placements=[
        Placement(motif="petal", scale=1.6, color="#a63b2a"),
        Placement(motif="dot", mode="rosette", n_fold=16,
                  ring_radius=2.2, color="#c99742"),
    ],
)
render_pattern(pattern, size=640).save("pattern.png")
print(pattern.to_spec().to_json())   # LLM 友好的结构化表示
```

真实纹样掩膜的部件分解（每部件自动选择谐波阶数）：

```python
from fcp import decompose_mask

dec = decompose_mask(binary_mask, max_order=24, tol=0.8)
print(dec.report())                          # 每部件 面积/阶数/RMS + 压缩率
spec = dec.to_pattern().to_spec().to_json()  # → PatternSpec
```

## 目录

```
AIforChinesePatterns/
  docs/        # survey.md 调研 · design-fourier-pattern.md 算法设计 · design-gui.md GUI 设计
  src/fcp/     # 核心五模块 + gui/ (imio/pipeline/fill/app)
  tests/       # 69 项单元测试（含 tests/gui/）
  demos/       # demo.py / demo_decompose.py / demo_gui_screenshot.py + 输出
  data/        # 规划：纹样图像 + 结构标注 + 文化知识库
```
