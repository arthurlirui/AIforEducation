"""dotartkit.styles — 流派渲染器.

每个流派实现为 ``generate_<name>(image: PIL.Image, **kwargs) -> PIL.Image``.
所有流派接收 RGB PIL Image, 输出 RGB PIL Image.

按"算子分层"组织:
- **位置算子**: 网格 / 密度场拒绝采样 / Voronoi Lloyd / 黄金角螺线 / 变形场
- **半径算子**: 常数 / 密度反函数 / 深度映射 / 径向函数
- **颜色算子**: 原图采样 / 互补混合 / 固定图谱 / 调色板

可用的流派 (通过 ``dotartkit.list_modes()`` 查看):

| 流派          | 模式键           | 位置算子       | 半径算子         | 颜色算子        |
|---------------|------------------|----------------|------------------|-----------------|
| 点彩派        | ``seurat``       | 网格 + 抖动    | 常数             | 互补色面积混合  |
| 草间弥生 (基础)| ``kusama_basic`` | Voronoi + 多层 | 密度正向映射     | 调色板          |
| 草间弥生 (深度)| ``kusama_depth`` | 深度密度场     | 深度映射 + 噪声  | 语义双色        |
| Ben-Day 半调  | ``benday``       | 旋转网格       | ∝ sqrt(1-g)      | Lichtenstein 四色 |
| Vasarely 欧普 | ``warp``         | 径向变形网格   | 凸起调制         | 单色 + 亮度     |
| Secord 点绘   | ``stipple_pure`` | 密度拒绝采样   | ∝ ρ^(-1/2)       | 单色            |
| 黄金角叶序    | ``vogel``        | Vogel 螺线     | 中心大 + 亮度    | 原图采样        |
"""

from .seurat import generate_seurat  # noqa: F401
from .benday import generate_benday  # noqa: F401
from .warp import generate_warp  # noqa: F401
from .stipple_pure import generate_stipple  # noqa: F401
from .vogel import generate_vogel  # noqa: F401
from .kusama_basic import generate_kusama_basic, kusama_polka  # noqa: F401
from .kusama_depth import generate_kusama_depth, depth_kusama_polka  # noqa: F401

__all__ = [
    "generate_seurat",
    "generate_benday",
    "generate_warp",
    "generate_stipple",
    "generate_vogel",
    "generate_kusama_basic",
    "kusama_polka",
    "generate_kusama_depth",
    "depth_kusama_polka",
]
