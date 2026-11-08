"""polka_document.py — 波点文档模型 (核心层, 不依赖 tkinter).

维护一张波点画布的全部状态:

- 输入图像 (RGB numpy)
- 中间产物: 深度图 d_norm / 密度场 density / 前景掩码 fg_mask
- 波点列表: 每个点是 (x, y, r, role) — role ∈ {"fg", "bg", "edge"}
- 编辑历史: undo / redo (命令栈)

渲染完全由点列表 + 调色板决定, 编辑操作只改点列表, 然后重绘.
生成管线 (深度估计 → 点采样) 与编辑操作解耦: 改一个参数可只重跑
受影响的阶段 (如只换映射函数则不重跑深度估计).

可独立于 GUI 使用与测试::

    from dotartkit.gui.polka_document import PolkaDocument
    doc = PolkaDocument()
    doc.load_image("pumpkin.jpg")
    doc.generate(n_points=8000)
    doc.delete_dot_at(x, y)
    doc.render()   # -> np.ndarray (H, W, 3) RGB
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import cv2

from ..ops.depth import (
    DepthEstimator,
    SemanticSegmentor,
    DEPTH_PALETTES,
    normalize_depth,
    normalize_depth_foreground,
    depth_to_density,
    get_foreground_mask,
    has_ultralytics,
)
from ..ops.voronoi import (
    compute_density,
    rejection_sample,
    lloyd_relax,
    prune_overlapping,
    prune_min_distance,
    has_scipy,
)

# ---------------------------------------------------------------------------
# 常量: 可选算法注册表 (UI 下拉框直接读这些)
# ---------------------------------------------------------------------------

#: 深度估计算法键 → (描述, 需要 ultralytics)
DEPTH_BACKENDS = {
    "yolo26":     ("YOLO26 单目深度 (metric, GPU)", True),
    "luminance":  ("亮度伪深度 (暗=近, 无需模型)", False),
}

#: 深度→半径映射激活函数键 → (描述, 函数)
#: 每个函数接收 (d_norm, r_min, r_max, alpha, rng, sigma),
#: 返回与 d_norm 同形的半径场.
def _act_power(d, r_min, r_max, alpha, rng, sigma):
    w = np.power(1.0 - d, alpha)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_linear(d, r_min, r_max, alpha, rng, sigma):
    # alpha 退化为对比度拉伸: alpha=1 纯线性
    w = np.clip((1.0 - d) * alpha, 0.0, 1.0)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_sigmoid(d, r_min, r_max, alpha, rng, sigma):
    # 中心化 sigmoid: alpha 控制斜率 (平滑 S 形, 近/远两端饱和)
    t = (0.5 - d) * max(alpha, 0.1) * 4.0
    w = 1.0 / (1.0 + np.exp(-t))
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_sqrt(d, r_min, r_max, alpha, rng, sigma):
    # 凹映射: 大部分区域得到偏大的点, 只有最远处明显缩小
    w = np.power(1.0 - d, 1.0 / max(alpha, 0.1))
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_curvature(d, r_min, r_max, alpha, rng, sigma, kappa=None):
    """纯曲率激活: 凸面 (κ>0) 大点, 凹/鞍面 (κ<0) 小点.

    w = clip(0.5 + 0.5·κ·α, 0, 1) — α 为曲率响应强度.
    深度不参与 (实验对照组), 曲率场由调用方传入 (避免重复计算).
    """
    if kappa is None:
        from ..ops.geometry import mean_curvature
        kappa = mean_curvature(d)
    w = np.clip(0.5 + 0.5 * kappa * max(alpha, 0.1), 0.0, 1.0)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_depth_curv(d, r_min, r_max, alpha, rng, sigma, kappa=None):
    """几何感知能量目标 (论文主方法):

        E_geo = (1-d̂)^α · exp(β·κ_+) · (1 - 0.5·κ_-)

    - 深度项 (1-d̂)^α:        近景大点 (保留原幂律)
    - 凸面增益 exp(β·κ_+):    球顶/鼓起区域再放大 (南瓜主体)
    - 凹面抑制 (1-0.5·κ_-):   鞍/凹陷区域缩小并靠向 r_min
    β 由 alpha 推出 (β=0.8α), κ_+ = max(κ,0), κ_- = max(-κ,0).
    """
    if kappa is None:
        from ..ops.geometry import mean_curvature
        kappa = mean_curvature(d)
    k_pos = np.maximum(kappa, 0.0)
    k_neg = np.maximum(-kappa, 0.0)
    beta = 0.8 * max(alpha, 0.1)
    w = np.power(1.0 - d, alpha) * np.exp(beta * k_pos) * (1.0 - 0.5 * k_neg)
    w = w / (w.max() + 1e-9)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_log(d, r_min, r_max, alpha, rng, sigma):
    """对数压缩: 近场剧烈变化, 远场平缓.

    w = 1 - log(1 + α·d̂) / log(1 + α) — α 控制压缩强度.
    """
    a = max(alpha, 0.1)
    w = 1.0 - np.log1p(a * d) / np.log1p(a)
    w = np.clip(w, 0.0, 1.0)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_cosine(d, r_min, r_max, alpha, rng, sigma):
    """余弦渐变: 平滑的半周期波, 中间带过渡最陡.

    w = 0.5·(1 + cos(π·d̂^α)) — α 扭曲相位分布.
    """
    w = 0.5 * (1.0 + np.cos(np.pi * np.power(d, max(alpha, 0.1))))
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_step(d, r_min, r_max, alpha, rng, sigma):
    """阶梯量化: 半径离散为 n 个台阶 (波普/硬边风格).

    台阶数 n = round(α·4) ∈ [2, 12] — α 控制量化级数.
    """
    n = int(np.clip(round(max(alpha, 0.1) * 4), 2, 12))
    w = np.ceil((1.0 - d) * n) / n
    w = np.clip(w, 0.0, 1.0)
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


def _act_inverse(d, r_min, r_max, alpha, rng, sigma):
    """反幂律: 远景大点、近景点 (负深度关系, 倒置风格实验).

    w = d̂^(1/α) — 与 power 的方向相反.
    """
    w = np.power(d, 1.0 / max(alpha, 0.1))
    r = r_min + (r_max - r_min) * w
    if sigma > 0:
        r = r * (1.0 + rng.normal(0, sigma, r.shape))
    return np.clip(r, 0.3, r_max * 1.1)


ACTIVATIONS = {
    "power":   ("幂律 (1-d̂)^α — 论文默认", _act_power),
    "linear":  ("线性 — 均匀梯度", _act_linear),
    "sigmoid": ("Sigmoid — S 形, 近远饱和", _act_sigmoid),
    "sqrt":    ("凹形 √ — 大点为主", _act_sqrt),
    "curvature": ("纯曲率 — 凸面大点/凹面小点 (对照)", _act_curvature),
    "depth_curv": ("几何感知 E_geo — 深度×凸面增益×凹面抑制", _act_depth_curv),
    "log":     ("对数压缩 — 近场剧烈远场平缓", _act_log),
    "cosine":  ("余弦渐变 — 平滑半周期", _act_cosine),
    "step":    ("阶梯量化 — 波普硬边 (α=级数/4)", _act_step),
    "inverse": ("反幂律 — 远大近小 (倒置)", _act_inverse),
}
"""尺寸映射函数注册表: 特征值 ∈ [0,1] → 半径 ∈ [r_min, r_max].

全部接收 (feature, r_min, r_max, alpha, rng, sigma, kappa=None),
返回半径场. 特征场由 :data:`FEATURES` 决定, 不再绑定深度.
"""

#: 波点滤除算法键 → 描述
FILTERS = {
    "none":        "无滤除 (保留全部采样点)",
    "overlap":     "重叠剪枝 (两圆圆心距 < r1+r2+gap 删其一)",
    "min_dist":    "最小间距 (圆心距 < min_dist 删其一)",
    "density":     "密度感知 (密区随机稀疏化, 保留疏区)",
}


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Dot:
    """一个波点. 坐标为文档像素坐标 (float), r 为半径 (px)."""
    x: float
    y: float
    r: float
    role: str = "fg"        # "fg" | "bg" | "edge"


def _dots_array(dots: list[Dot]):
    pts = np.array([[d.x, d.y] for d in dots], dtype=np.float64) if dots \
        else np.empty((0, 2))
    rads = np.array([d.r for d in dots], dtype=np.float64) if dots \
        else np.empty((0,))
    return pts, rads


# ---------------------------------------------------------------------------
# 特征通道注册表: 尺寸映射函数作用的目标特征场
# ---------------------------------------------------------------------------

FEATURES = {
    "depth":         "归一化深度 d̂ (近=0, 远=1)",
    "luminance":     "亮度 (亮=0, 暗=1 — 暗处大点)",
    "curvature":     "平均曲率 κ (凹/鞍=0, 凸=1)",
    "gradient":      "深度梯度模 |∇d̂| (平坦=0, 转折=1)",
    "gaussian_curv": "高斯曲率 K (鞍=0, 球顶=1)",
    "hybrid":        "混合 0.6·(1-d̂) + 0.4·κ₊ (深度+凸面)",
}
"""特征通道: 映射函数的输入场. 共 6 种, 全部归一到 [0,1]."""


class PolkaDocument:
    """波点文档: 图像 + 中间场 + 点列表 + 编辑历史."""

    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        self.image: Optional[np.ndarray] = None      # RGB uint8
        self.gray: Optional[np.ndarray] = None
        self.depth_raw: Optional[np.ndarray] = None  # metric 或伪深度
        self.d_norm: Optional[np.ndarray] = None
        self.density: Optional[np.ndarray] = None
        self.fg_mask: Optional[np.ndarray] = None
        self.kappa: Optional[np.ndarray] = None   # 符号化平均曲率场 (缓存)
        self._geo_cache: dict = {}                 # geometry_fields 缓存
        self.dots: list[Dot] = []
        self._depth_backend: str = "luminance"
        self._semantic_aware: bool = True
        self._undo_stack: list[list[Dot]] = []
        self._redo_stack: list[list[Dot]] = []
        self._edit_snapshot: list[Dot] | None = None
        self._estimator = None
        self._segmentor = None

    # ------------------------------------------------------------------
    # 图像与生成
    # ------------------------------------------------------------------

    @property
    def size(self) -> tuple[int, int]:
        """(W, H) 或 (0, 0)."""
        if self.image is None:
            return (0, 0)
        return (self.image.shape[1], self.image.shape[0])

    def load_image(self, image_or_path, target_long_edge: int = 1024):
        """加载图像 (PIL Image / ndarray / 路径), 限制长边并转 RGB."""
        if isinstance(image_or_path, str):
            img = cv2.imread(image_or_path)
            if img is None:
                from PIL import Image as PILImage
                pil = PILImage.open(image_or_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        elif hasattr(image_or_path, "convert"):  # PIL
            img = np.array(image_or_path.convert("RGB"))
        else:
            img = np.asarray(image_or_path)
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        h, w = img.shape[:2]
        scale = target_long_edge / max(h, w)
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        self.image = img.astype(np.uint8)
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_RGB2GRAY)
        # 新图像: 清空全部状态
        self.depth_raw = self.d_norm = self.density = self.fg_mask = None
        self.kappa = None
        self._geo_cache = {}
        self.dots = []
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._estimator = None
        self._segmentor = None
        self._depth_backend = "luminance"

    # -- 深度估计 -------------------------------------------------------

    def ensure_depth(self, backend: str, device: str = "0",
                     semantic_aware: bool = True) -> None:
        """确保深度图 / 前景掩码就绪. 后端或图像未变时跳过重算."""
        if self.image is None:
            raise RuntimeError("no image loaded")
        if backend not in DEPTH_BACKENDS:
            raise ValueError(f"unknown depth backend {backend!r}")
        need_recompute = (
            self.depth_raw is None
            or backend != self._depth_backend
            or self.fg_mask is None
        )
        if not need_recompute:
            return
        self._depth_backend = backend
        if backend == "yolo26":
            if not has_ultralytics():
                raise ImportError(
                    "yolo26 backend 需要 ultralytics + YOLO26 权重")
            if self._estimator is None:
                import os
                mp = os.path.join(self.model_dir, "yolo26x-depth.pt")
                self._estimator = DepthEstimator(mp, device=device)
            bgr = cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR)
            self.depth_raw = self._estimator.predict(bgr)
            if semantic_aware and self._segmentor is None:
                import os
                sp = os.path.join(self.model_dir, "yolo26x-sem.pt")
                try:
                    self._segmentor = SemanticSegmentor(sp, device=device)
                except Exception:
                    self._segmentor = None
            if semantic_aware and self._segmentor is not None:
                seg = self._segmentor.predict(bgr)
                self.fg_mask = get_foreground_mask(seg)
            else:
                self.fg_mask = np.ones(self.gray.shape, dtype=np.uint8)
        else:  # luminance 伪深度: 暗=近(0), 亮=远(1)
            self.depth_raw = self.gray.astype(np.float32) / 255.0
            self.fg_mask = np.ones(self.gray.shape, dtype=np.uint8)
        self._semantic_aware = semantic_aware
        self._recompute_norm_density()

    # -- 特征场 ----------------------------------------------------------

    def get_feature(self, name: str) -> np.ndarray:
        """按名称返回归一到 [0,1] 的特征场 (:data:`FEATURES` 键).

        几何场 (曲率/梯度) 计算一次后按图像缓存, 不随参数重算.
        """
        if name not in FEATURES:
            raise ValueError(f"unknown feature {name!r}, choose from "
                             f"{list(FEATURES)}")
        if self.d_norm is None:
            raise RuntimeError("call ensure_depth() first")
        if name == "depth":
            return self.d_norm
        if name == "luminance":
            g = self.gray.astype(np.float32) / 255.0
            return 1.0 - g          # 暗 = 1 → 大点 (映射函数 near=0 约定翻转)
        if self._geo_cache.get("src") is not self.d_norm:
            from ..ops.geometry import geometry_fields
            self._geo_cache = {"src": self.d_norm}
            self._geo_cache.update(geometry_fields(self.d_norm))
        geo = self._geo_cache
        if name == "curvature":
            return (geo["kappa"] + 1.0) * 0.5       # [-1,1] → [0,1]
        if name == "gradient":
            return geo["grad_mag"]
        if name == "gaussian_curv":
            return (geo["gauss_sign"] + 1.0) * 0.5
        if name == "hybrid":
            k_pos = geo["kappa_pos"]
            h = 0.6 * (1.0 - self.d_norm) + 0.4 * k_pos
            return np.clip(h, 0.0, 1.0)
        raise AssertionError(name)

    def _recompute_norm_density(self, percentile_clip: float = 2.0,
                                beta: float = 0.6, gamma: float = 1.2):
        """深度归一化 + 复合密度场 (换 alpha 等参数时无需重跑)."""
        if self.depth_raw is None:
            return
        self.kappa = None   # d_norm 变了, 曲率场随之失效
        if self._semantic_aware and self.fg_mask is not None \
                and self.fg_mask.mean() > 0.005 and self._depth_backend == "yolo26":
            self.d_norm = normalize_depth_foreground(
                self.depth_raw, self.fg_mask,
                percentile_clip=percentile_clip)
        else:
            self.d_norm = normalize_depth(
                self.depth_raw, percentile_clip=percentile_clip)
        self.density = depth_to_density(
            self.d_norm, self.gray, gamma=gamma, beta=beta)

    # -- 生成 ------------------------------------------------------------

    def generate(self,
                 n_points: int = 12000,
                 n_iter: int = 8,
                 r_min: float = 1.0,
                 r_max: float = 14.0,
                 alpha: float = 1.5,
                 sigma: float = 0.15,
                 activation: str = "power",
                 feature: str = "depth",
                 prune: str = "overlap",
                 prune_gap: float = 1.5,
                 pos_jitter: float = 0.3,
                 edge_dots: bool = True,
                 bg_fill: bool = True,
                 bg_spacing: float = 20.0,
                 seed: int = 42) -> dict:
        """按当前参数 (重新) 生成全部波点. 返回统计 dict.

        feature: :data:`FEATURES` 键 — 映射函数的输入特征场.
        """
        if self.density is None:
            raise RuntimeError("call ensure_depth() first")
        if activation not in ACTIVATIONS:
            raise ValueError(f"unknown activation {activation!r}")
        if feature not in FEATURES:
            raise ValueError(f"unknown feature {feature!r}")
        if prune not in FILTERS:
            raise ValueError(f"unknown filter {prune!r}")
        rng = np.random.default_rng(seed)
        H, W = self.gray.shape

        # 曲率场: 几何感知激活需要时才计算 (一次计算, 多次复用)
        need_kappa = activation in ("curvature", "depth_curv")
        kappa = None
        if need_kappa:
            if self.kappa is None:
                from ..ops.geometry import mean_curvature
                self.kappa = mean_curvature(self.d_norm)
            kappa = self.kappa

        # 采样 + Lloyd 松弛 (与激活函数 / 滤除无关)
        pts = rejection_sample(self.density, n_points, rng)
        if has_scipy():
            pts = lloyd_relax(pts, self.density, n_iter=n_iter, rng=rng)
        if pos_jitter > 0:
            pts = pts + rng.normal(0, pos_jitter, pts.shape)

        # 半径场: 映射函数作用于所选特征场
        feat = self.get_feature(feature)
        xi = np.clip(pts[:, 0].astype(int), 0, W - 1)
        yi = np.clip(pts[:, 1].astype(int), 0, H - 1)
        if need_kappa:
            radius_field = ACTIVATIONS[activation][1](
                feat, r_min, r_max, alpha, rng, sigma, kappa=kappa)
        else:
            radius_field = ACTIVATIONS[activation][1](
                feat, r_min, r_max, alpha, rng, sigma)
        radii = radius_field[yi, xi].astype(np.float64)

        # 角色: 前景/背景 (fg_mask 全 1 时全部为 fg)
        if self.fg_mask is not None and self.fg_mask.mean() < 0.999:
            roles = np.where(self.fg_mask[yi, xi] > 0, "fg", "bg")
        else:
            roles = np.full(len(pts), "fg")

        # 滤除
        pts, radii, roles = self._apply_filter(
            pts, radii, roles, prune, prune_gap, rng)

        dots = [Dot(float(x), float(y), float(r), str(role))
                for (x, y), r, role in zip(pts, radii, roles)]

        # 边缘点
        if edge_dots:
            blurred = cv2.GaussianBlur(self.gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 80, 160)
            eys, exs = np.where(edges > 0)
            if len(exs) > 0:
                step = 4
                exs = exs[::step].astype(np.float64) + rng.normal(0, 1.2, (len(exs[::step]),))
                eys = eys[::step].astype(np.float64) + rng.normal(0, 1.2, (len(eys[::step]),))
                dots.extend(Dot(float(x), float(y), 1.3, "edge")
                            for x, y in zip(exs, eys))

        # horror-vacui 背景填充
        if bg_fill:
            bxs = np.arange(bg_spacing / 2, W, bg_spacing)
            bys = np.arange(bg_spacing / 2, H, bg_spacing)
            bgx, bgy = np.meshgrid(bxs, bys)
            bgp = np.column_stack([bgx.ravel(), bgy.ravel()]).astype(np.float64)
            bgp += rng.normal(0, 3.0, bgp.shape)
            bgr = rng.uniform(0.7, 1.3, len(bgp))
            bxi = np.clip(bgp[:, 0].astype(int), 0, W - 1)
            byi = np.clip(bgp[:, 1].astype(int), 0, H - 1)
            keep = self.density[byi, bxi] < 0.25
            dots.extend(Dot(float(x), float(y), float(r), "bg")
                        for (x, y), r in zip(bgp[keep], bgr[keep]))

        self._push_history()
        self.dots = dots
        self._redo_stack.clear()

        n_fg = sum(1 for d in dots if d.role == "fg")
        n_bg = sum(1 for d in dots if d.role == "bg")
        n_edge = sum(1 for d in dots if d.role == "edge")
        return {
            "n_dots": len(dots), "n_fg": n_fg, "n_bg": n_bg,
            "n_edge": n_edge,
            "r_min": float(min((d.r for d in dots), default=0.0)),
            "r_max": float(max((d.r for d in dots), default=0.0)),
        }

    def _apply_filter(self, pts, radii, roles, prune, gap, rng):
        """按滤除算法处理点集. 返回 (pts, radii, roles).

        prune_* 只操作 (pts, radii); 滤除后用最近邻把 roles
        对齐回保留的点 (保留点必来自原集合, 最近邻距离为 0).
        """
        if prune == "none" or len(pts) == 0:
            return pts, radii, roles
        pts_before = pts
        roles_before = roles
        if prune == "overlap":
            pts, radii = prune_overlapping(pts, radii, gap=gap)
        elif prune == "min_dist":
            pts, radii = prune_min_distance(
                pts, radii, min_dist=max(gap, 0.5))
        elif prune == "density":
            # 密度感知: 局部过密处随机丢弃, 稀疏处全保留
            if has_scipy() and len(pts) > 1:
                from scipy.spatial import cKDTree
                tree = cKDTree(pts)
                radius_cap = float(np.percentile(radii, 90)) * 2 + gap * 2
                counts = tree.query_ball_point(pts, radius_cap,
                                               return_length=True)
                thr = float(np.median(counts))
                keep = (counts <= thr) | \
                       (rng.random(len(pts)) < thr / np.maximum(counts, 1))
                pts, radii = pts[keep], radii[keep]
        roles = self._snapshot_roles(pts_before, roles_before, pts)
        return pts, radii, roles

    # ------------------------------------------------------------------
    # 编辑操作 (全部支持 undo/redo)
    # ------------------------------------------------------------------

    def _push_history(self):
        self._undo_stack.append(copy.deepcopy(self.dots))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _snapshot_roles(self, pts_before, roles_before, pts_after):
        """滤除后按最近邻把 roles 对齐回保留点 (供内部使用)."""
        if len(pts_after) == 0 or len(pts_before) == 0:
            return np.empty((0,), dtype=object)
        if has_scipy():
            from scipy.spatial import cKDTree
            tree = cKDTree(pts_before)
            _, idx = tree.query(pts_after, k=1)
        else:
            idx = np.empty(len(pts_after), dtype=int)
            for i, p in enumerate(pts_after):
                idx[i] = int(np.argmin(
                    np.sum((pts_before - p) ** 2, axis=1)))
        return roles_before[idx]

    def find_dot(self, x: float, y: float, tol_extra: float = 3.0) -> Optional[int]:
        """返回包含 (x,y) 的最近点索引 (含 tol 容差), 无则 None.

        命中判定: 距离 ≤ r + tol_extra, 取距离最近者.
        小点优先与大点同级竞争 (直接按归一化距离 d - r 排序).
        """
        best_i, best_key = None, None
        for i, d in enumerate(self.dots):
            dist = np.hypot(d.x - x, d.y - y)
            if dist <= d.r + tol_extra:
                key = dist - d.r
                if best_key is None or key < best_key:
                    best_i, best_key = i, key
        return best_i

    def delete_dot(self, index: int) -> None:
        """删除指定索引的点."""
        self._push_history()
        del self.dots[index]

    def delete_dots_in_circle(self, x: float, y: float, radius: float) -> int:
        """删除圆域内的全部点, 返回删除数."""
        victims = [i for i, d in enumerate(self.dots)
                   if np.hypot(d.x - x, d.y - y) <= radius + d.r]
        if not victims:
            return 0
        self._push_history()
        for i in reversed(victims):
            del self.dots[i]
        return len(victims)

    def move_dot(self, index: int, x: float, y: float) -> None:
        """移动点到 (x, y). 不入历史 — 由调用方 (拖拽结束) 统一提交."""
        self.dots[index].x = float(x)
        self.dots[index].y = float(y)

    def resize_dot(self, index: int, r: float) -> None:
        """修改点半径. 不入历史 — 由调用方统一提交."""
        self.dots[index].r = max(0.3, float(r))

    def set_dot_role(self, index: int, role: str) -> None:
        """修改点角色 (前景/背景/边缘). 不入历史."""
        if role in ("fg", "bg", "edge"):
            self.dots[index].role = role

    def remap_radii(self,
                    activation: str,
                    feature: str = "depth",
                    r_min: float = 1.0,
                    r_max: float = 14.0,
                    alpha: float = 1.5,
                    sigma: float = 0.0,
                    region: Optional[tuple] = None,
                    seed: int = 42) -> int:
        """再编辑核心: 保留点位置, 按新映射函数 + 特征场重算半径.

        与 :meth:`generate` 不同 — 不重新采样: 手动增删移动过的点
        全部保留, 只有半径被替换.

        Parameters
        ----------
        activation : :data:`ACTIVATIONS` 键
        feature : :data:`FEATURES` 键, 映射函数的输入特征场
        region : 可选 (x, y, radius) 圆形选区 — 只重映射选区内
                 的点 (局部再编辑); None = 全部点.
        seed : 映射抖动的随机种子 (sigma>0 时影响)

        Returns
        -------
        n_remapped : 被重映射的点数 (入历史, 可撤销)
        """
        if activation not in ACTIVATIONS:
            raise ValueError(f"unknown activation {activation!r}")
        if feature not in FEATURES:
            raise ValueError(f"unknown feature {feature!r}")
        feat = self.get_feature(feature)
        H, W = feat.shape
        rng = np.random.default_rng(seed)
        fn = ACTIVATIONS[activation][1]
        # 需要曲率的映射函数传入缓存场 (curvature/depth_curv)
        kappa_arg = None
        if activation in ("curvature", "depth_curv"):
            if self.kappa is None:
                from ..ops.geometry import mean_curvature
                self.kappa = mean_curvature(self.d_norm)
            kappa_arg = self.kappa
            radius_field = fn(feat, r_min, r_max, alpha, rng, sigma,
                              kappa=kappa_arg)
        else:
            radius_field = fn(feat, r_min, r_max, alpha, rng, sigma)

        targets = self.dots
        if region is not None:
            rx, ry, rr = region
            targets = [d for d in self.dots
                       if np.hypot(d.x - rx, d.y - ry) <= rr]
        if not targets:
            return 0
        self._push_history()
        for d in targets:
            xi = int(np.clip(round(d.x), 0, W - 1))
            yi = int(np.clip(round(d.y), 0, H - 1))
            d.r = float(radius_field[yi, xi])
        return len(targets)

    def add_dot(self, x: float, y: float, r: float, role: str = "fg") -> None:
        """在 (x, y) 添加一个点 (入历史)."""
        self._push_history()
        self.dots.append(Dot(float(x), float(y), max(0.3, float(r)), role))

    def begin_edit(self) -> None:
        """开始一次交互编辑 (拖拽/改半径前调用): 快照当前状态.

        之后的 move_dot / resize_dot 直接修改, 调用方在结束时调
        end_edit() 决定提交或丢弃. 单独调用 add_dot / delete_dot /
        delete_dots_in_circle 无需配对 — 它们自行入历史.
        """
        self._edit_snapshot = copy.deepcopy(self.dots)
        self._edit_changed = False

    def end_edit(self, changed: bool = True) -> None:
        """结束交互编辑: changed=True 把 begin_edit 的快照压入撤销栈,
        False 则丢弃快照 (无变化时不产生历史记录)."""
        snap = getattr(self, "_edit_snapshot", None)
        if snap is not None and changed:
            self._redo_stack.clear()
            self._undo_stack.append(snap)
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
        self._edit_snapshot = None
        self._edit_changed = False

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(copy.deepcopy(self.dots))
        self.dots = self._undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(copy.deepcopy(self.dots))
        self.dots = self._redo_stack.pop()
        return True

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def render(self, palette: str = "black_red",
               semantic_aware: bool = True,
               dot_roles_visible: Optional[set] = None) -> np.ndarray:
        """渲染点列表 → RGB uint8 图像.

        dot_roles_visible: 可视化用 — 只画指定角色的点 (None = 全部).
        """
        if self.image is None:
            raise RuntimeError("no image loaded")
        pal = DEPTH_PALETTES.get(palette, DEPTH_PALETTES["black_red"])
        # DEPTH_PALETTES 为 BGR, 转 RGB
        bg = pal["bg"][::-1]
        fg_dot = pal["fg_dot"][::-1]
        bg_dot = pal["bg_dot"][::-1]
        H, W = self.image.shape[:2]
        canvas = np.full((H, W, 3), bg, dtype=np.uint8)
        # 绘制顺序: bg 点在下, edge, fg 最上
        for role_order in ("bg", "edge", "fg"):
            color = {"bg": bg_dot, "edge": fg_dot, "fg": fg_dot}[role_order]
            for d in self.dots:
                if dot_roles_visible is not None and d.role not in dot_roles_visible:
                    continue
                if d.role != role_order:
                    continue
                xi, yi, rr = int(round(d.x)), int(round(d.y)), int(round(d.r))
                if rr < 1:
                    if 0 <= xi < W and 0 <= yi < H:
                        canvas[yi, xi] = color
                else:
                    cv2.circle(canvas, (xi, yi), rr, color, -1,
                               lineType=cv2.LINE_4)
        return canvas
