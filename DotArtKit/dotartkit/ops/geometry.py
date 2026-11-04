"""geometry.py — 深度图的几何场计算 (曲率 / 梯度张量, 纯 numpy).

为波点生成的几何感知目标函数提供输入. 从归一化深度图 d̂ 出发计算:

- 一阶: 梯度模 |∇d̂| (坡度)
- 二阶: Hessian 分量 (d_xx, d_xy, d_yy) → 平均曲率 H 与高斯曲率 K

**深度图的曲率语义**: d̂(x,y) 可视为一个高度场 h(x,y) = 1 - d̂(x,y)
(近=高). 其平均曲率近似为::

    H ≈ (d_xx + d_yy) / (2 (1 + |∇d|²)^{3/2})

凸面 (球顶, H < 0 对于 h 场) 在视觉上是"鼓起来"的区域 — Kusama
南瓜的主体正是这种形面, 应给予大而醒目的圆点; 鞍面 / 凹面 (H > 0)
表面转折复杂, 应给予小点并加密以顺应表面. 我们约定输出::

    κ_mean: 平均曲率的符号化版本, 已除以最大 |H| 归一到 [-1, 1],
            κ > 0 = 凸 (球顶), κ < 0 = 凹/鞍
    |∇d̂|:  梯度模, 归一到 [0, 1]
    K_gauss: 高斯曲率符号 (仅作诊断用)

所有函数纯 numpy, 无 DL 依赖.
"""

from __future__ import annotations

import numpy as np


def _central_diff_1d(f: np.ndarray, axis: int) -> np.ndarray:
    """中心差分 (边界用前向/后向差分), 精度 O(h²) 内部."""
    d = np.zeros_like(f, dtype=np.float64)
    if axis == 1:  # x 方向
        d[:, 1:-1] = (f[:, 2:] - f[:, :-2]) * 0.5
        d[:, 0] = f[:, 1] - f[:, 0]
        d[:, -1] = f[:, -1] - f[:, -2]
    else:          # y 方向
        d[1:-1, :] = (f[2:, :] - f[:-2, :]) * 0.5
        d[0, :] = f[1, :] - f[0, :]
        d[-1, :] = f[-1, :] - f[-2, :]
    return d


def _second_diff(f: np.ndarray, axis: int) -> np.ndarray:
    """二阶差分 d²f/dx² 或 d²f/dy² (边界复制)."""
    d = np.zeros_like(f, dtype=np.float64)
    if axis == 1:
        d[:, 1:-1] = f[:, 2:] - 2 * f[:, 1:-1] + f[:, :-2]
        d[:, 0] = d[:, 1]
        d[:, -1] = d[:, -2]
    else:
        d[1:-1, :] = f[2:, :] - 2 * f[1:-1, :] + f[:-2, :]
        d[0, :] = d[1, :]
        d[-1, :] = d[-2, :]
    return d


def depth_gradient(d_norm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """深度梯度 (gx, gy), 各归一到自身最大模."""
    gx = _central_diff_1d(d_norm.astype(np.float64), axis=1)
    gy = _central_diff_1d(d_norm.astype(np.float64), axis=0)
    return gx, gy


def gradient_magnitude(d_norm: np.ndarray) -> np.ndarray:
    """|∇d̂| 归一到 [0, 1]. 坡度转折带 (轮廓) 值高."""
    gx, gy = depth_gradient(d_norm)
    m = np.sqrt(gx ** 2 + gy ** 2)
    m_max = m.max()
    if m_max > 1e-9:
        m = m / m_max
    return m.astype(np.float32)


def mean_curvature(d_norm: np.ndarray,
                   smooth_sigma: float = 1.5) -> np.ndarray:
    """高度场 h = 1 - d̂ 的平均曲率 H 的符号化归一版本 κ_mean ∈ [-1, 1].

    κ > 0 → 凸面 (球顶, 如南瓜主体鼓起处)
    κ < 0 → 凹面/鞍面

    smooth_sigma > 0 时先做高斯平滑 (抑制深度估计噪声的二阶放大).
    """
    h = 1.0 - d_norm.astype(np.float64)
    if smooth_sigma > 0:
        try:
            from scipy.ndimage import gaussian_filter
            h = gaussian_filter(h, sigma=smooth_sigma)
        except ImportError:
            # 无 scipy: 3x3 均值滤波近似
            k = np.ones((3, 3), np.float64) / 9.0
            pad = np.pad(h, 1, mode="edge")
            h = sum(k[i, j] * pad[i:i + h.shape[0], j:j + h.shape[1]]
                    for i in range(3) for j in range(3))

    hx = _central_diff_1d(h, axis=1)
    hy = _central_diff_1d(h, axis=0)
    hxx = _second_diff(h, axis=1)
    hyy = _second_diff(h, axis=0)
    hxy = _central_diff_1d(hx, axis=0)

    denom = (1.0 + hx ** 2 + hy ** 2) ** 1.5
    # 高度场平均曲率 (标准公式). 注意符号: 球顶 (h 极大) 的 H < 0,
    # 我们约定 κ > 0 = 凸, 故取负号翻转.
    H = -((1.0 + hy ** 2) * hxx - 2.0 * hx * hy * hxy
          + (1.0 + hx ** 2) * hyy) / (2.0 * denom + 1e-12)

    # 归一: 除以最大 |H| 后裁剪, 保留缓变场的相对差异 (避免 p98 饱和)
    h_abs = np.abs(H)
    hi = h_abs.max()
    if hi > 1e-12:
        H = np.clip(H / hi, -1.0, 1.0)
    return H.astype(np.float32)


def gaussian_curvature_sign(d_norm: np.ndarray,
                            smooth_sigma: float = 1.5) -> np.ndarray:
    """高斯曲率 K 的符号归一版本 (诊断用). K>0 椭圆点, K<0 鞍点."""
    h = 1.0 - d_norm.astype(np.float64)
    if smooth_sigma > 0:
        try:
            from scipy.ndimage import gaussian_filter
            h = gaussian_filter(h, sigma=smooth_sigma)
        except ImportError:
            pad = np.pad(h, 1, mode="edge")
            h = sum(np.ones((3, 3))[i, j] / 9.0 *
                    pad[i:i + h.shape[0], j:j + h.shape[1]]
                    for i in range(3) for j in range(3))
    hx = _central_diff_1d(h, axis=1)
    hy = _central_diff_1d(h, axis=0)
    hxx = _second_diff(h, axis=1)
    hyy = _second_diff(h, axis=0)
    hxy = _central_diff_1d(hx, axis=0)
    # 高斯曲率自然符号: 球顶 (椭圆点) K > 0, 鞍点 K < 0 — 不翻转
    K = (hxx * hyy - hxy ** 2) / (1.0 + hx ** 2 + hy ** 2 + 1e-12) ** 2
    k_abs = np.abs(K)
    hi = k_abs.max()
    if hi > 1e-12:
        K = np.clip(K / hi, -1.0, 1.0)
    return K.astype(np.float32)


def geometry_fields(d_norm: np.ndarray,
                    smooth_sigma: float = 1.5) -> dict:
    """一次计算全部几何场 (供网络输入 / 激活函数 / 诊断).

    Returns
    -------
    dict 键:
        grad_mag    : |∇d̂| ∈ [0,1]
        kappa       : 符号化平均曲率 ∈ [-1,1] (正=凸)
        kappa_pos   : max(κ, 0) — 凸面响应
        kappa_neg   : max(-κ, 0) — 凹/鞍响应
        gauss_sign  : 高斯曲率符号 (诊断)
    """
    kappa = mean_curvature(d_norm, smooth_sigma=smooth_sigma)
    return {
        "grad_mag": gradient_magnitude(d_norm),
        "kappa": kappa,
        "kappa_pos": np.maximum(kappa, 0.0),
        "kappa_neg": np.maximum(-kappa, 0.0),
        "gauss_sign": gaussian_curvature_sign(d_norm,
                                              smooth_sigma=smooth_sigma),
    }
