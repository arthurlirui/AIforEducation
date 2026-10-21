# OilPaintingRevive —— 油画动态艺术再创造系统

> 将一幅静态油画的数字扫描件和一组人工手绘控制线稿，转换为一段可探索的油画风格动态视频。
> 五阶段流水线：输入解析 → 2DGS 场景构建 → 骨架绑定优化 → 相机轨迹粗渲染 → LTX-Video IC-LoRA 风格生成。

## ✨ 特性

- **2DGS 3D 结构提取**：单幅油画 + 单目深度 → surfel 点云，可探索视角
- **TripoSplat 前景物体**：单图 → 3D 高斯 → 3DGS→2DGS 转换
- **骨架绑定网络**：可学习 MLP 软绑定，距离权重热启动
- **约束优化**：光度 + 法线 + 骨架遵循 + 风格保持四项损失
- **相机轨迹**：关键帧线稿 → R³ 估计 → 平滑轨迹 → 粗渲染
- **LTX-2.3 IC-LoRA**：Union Control（depth + RGB 双条件）两阶段生成
- **检查点机制**：各阶段中间产物持久化，可断点恢复
- **Fallback mock**：SAM2/DA-V2/R³/ComfyUI 不可用时自动降级，保证流程可测试

## 📦 安装

```bash
cd OilPaintingRevive
pip install -e .
pip install -e ".[dev]"     # pytest
pip install -e ".[torch]"   # PyTorch（真实模型推理）
```

## 🔧 配置

```bash
cp .env.example .env
# 编辑 .env：COMFY_HOST/PORT、FFMPEG_PATH
```

创作参数见 `config/settings.yaml`（画幅/时长/模型名/损失权重/采样参数）。

## 🚀 使用

```bash
# 环境自检
oilrev health

# 一键端到端（需 ComfyUI + 模型权重）
oilrev run painting.png --skeleton skel.png --keyframe kf1.png --keyframe kf2.png

# 仅 mock 模式（无 GPU / 无 ComfyUI 时验证流程）
oilrev run painting.png --no-comfyui

# 断点恢复
oilrev run painting.png --resume
```

## 📐 架构

```
Stage 1  输入解析    油画+线稿 → SAM2分割 + DA-V2深度 → 分层掩码/深度/控制信号
Stage 2  3D构建      分层图 → 2DGS(背景) + TripoSplat(前景) → 3DGS→2DGS → 统一场景
Stage 3  骨架绑定    骨架线稿 → 骨骼拟合 → 高斯软绑定 → 可微渲染优化(4项损失)
Stage 4  轨迹渲染    关键帧 → R³相机估计 → 2DGS渲染 → coarse RGB + depth
Stage 5  风格生成    coarse+depth → LTX-2.3 IC-LoRA → 两阶段生成 → 油画视频
```

详细设计见 [docs/design.md](docs/design.md)。

## 🧪 测试

```bash
pytest -q     # 13 项全流程测试（mock 模式，无需 GPU）
```

测试覆盖：
- Stage 1-5 各阶段单独测试
- 端到端全流程（test_run_pipeline_mock）
- 检查点持久化（test_checkpoint_persistence）
- 数据模型序列化（test_schemas）
- 工作流模板与参数注入（test_workflow_template）

## 📁 产物结构

```
output/<project_id>/
├── meta.json                 # 各阶段耗时与参数
├── stage1/                   # 分层掩码 + 深度图 + 控制线稿
├── stage2/                   # 2DGS 场景 .ply
├── stage3/                   # 绑定权重 + 优化后场景
├── stage4/{rgb,depth}/       # 粗渲染帧序列
└── stage5/                   # 最终视频 + ComfyUI 工作流
```

## 🔗 开源组件

| 模块 | 仓库 | 集成方式 |
|---|---|---|
| SAM 2 | facebookresearch/sam2 | Python API（fallback: mock 分割） |
| Depth Anything V2 | DepthAnything/Depth-Anything-V2 | Python API（fallback: mock 深度） |
| 2DGS | hbb1/2d-gaussian-splatting | PLY 点云 + mock 渲染 |
| TripoSplat | VAST-AI-Research/TripoSplat | ComfyUI/Python（fallback: mock 高斯） |
| LTX-Video | Lightricks/ComfyUI-LTXVideo | ComfyUI HTTP API |
| R³ | KevinXu02/R3 | Python API（fallback: mock 轨迹） |
| SMPL-X | vchoutas/smplx | Python API（fallback: 默认骨架） |

## 📄 设计文档

完整架构设计、各阶段详细方案、系统级设计（检查点/显存/评估）见 [docs/design.md](docs/design.md)。
