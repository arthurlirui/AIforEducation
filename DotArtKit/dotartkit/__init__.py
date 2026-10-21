"""DotArtKit — 统一波点艺术生成器.

把原 AIforPolkaDotsArt (草间弥生专攻 + 深度感知) 与 AIforDotArt
(多流派纯数学) 两个项目整合为单一 Python 包.

8 种生成模式 (按算子分层组织):

无 DL 依赖:
    - ``seurat``       点彩派 (Chevreul 互补色面积混合)
    - ``benday``       Ben-Day 半调 / Lichtenstein 波普
    - ``warp``         Vasarely Vega 欧普凸起
    - ``stipple``      Secord 计算点绘 (纯 numpy GridHash)
    - ``vogel``        黄金角叶序
    - ``kusama_basic`` 草间弥生基础版 (亮度密度 Voronoi)

需 ultralytics + YOLO26:
    - ``kusama_depth`` 草间弥生深度感知版 (YOLO26 深度 + 三层架构)

可选 torch:
    - ``learned`` 可学习深度→半径映射 (IJCAI 论文 AI 贡献,
      见 :mod:`dotartkit.learned`)

快速开始::

    from dotartkit import generate
    from PIL import Image
    img = Image.open("inputs/pumpkin.jpg").convert("RGB")
    generate("kusama_basic", img, palette="yellow_black").save("out.png")

命令行::

    python -m dotartkit.cli list
    python -m dotartkit.cli generate kusama_basic inputs/pumpkin.jpg -o out.png --palette yellow_black
"""

from .api import (
    generate,
    MODES,
    list_modes,
    list_pure_modes,
    list_dl_modes,
    mode_info,
)
from .ops.color import KUSAMA_PALETTES
from .ops.depth import DEPTH_PALETTES, has_ultralytics
from .ops.voronoi import has_scipy
from .learned import has_torch

__version__ = "1.0.0"

__all__ = [
    "generate",
    "MODES",
    "list_modes",
    "list_pure_modes",
    "list_dl_modes",
    "mode_info",
    "KUSAMA_PALETTES",
    "DEPTH_PALETTES",
    "has_scipy",
    "has_ultralytics",
    "has_torch",
    "__version__",
]
