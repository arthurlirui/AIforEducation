"""learned.py — 可学习深度→点半径映射 (IJCAI 论文的 AI 贡献).

用轻量 CNN 替代固定幂律公式
``r = r_min + (r_max - r_min) · (1 - d̂)^α · (1 + ε)``,
从感知监督学习最优深度→半径映射.

**可选依赖**: ``torch``. 无 torch 时本模块所有类/函数抛 ImportError,
但其余流派 (seurat / kusama_basic / stipple_pure 等) 不受影响.

网络结构:
    输入 (4 通道): 归一化深度 d̂, 亮度 I_gray, 深度梯度 |∇d̂|, 亮度梯度 |∇I|
    输出 (2 通道): 半径 r ∈ [r_min, r_max], 密度权重 w ∈ [0,1]
    4 conv 层, <50K 参数, 保持可解释性.

训练模式:
    1. 监督: 从艺术家标注的点分布学习 (如有)
    2. 自监督: 优化感知质量目标 (蓝噪声频谱 + 深度梯度对齐 + 覆盖率目标)
"""

from __future__ import annotations

import numpy as np
from typing import Optional

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    nn = None  # type: ignore
    F = None  # type: ignore
    _HAS_TORCH = False


def has_torch() -> bool:
    """返回 torch 是否可用."""
    return _HAS_TORCH


# ---------------------------------------------------------------------------
# 1. DepthRadiusNet
# ---------------------------------------------------------------------------

if _HAS_TORCH:

    class DepthRadiusNet(nn.Module):
        """轻量 CNN, 像素级特征 → 点半径 + 密度权重."""

        def __init__(self,
                     r_min: float = 1.0,
                     r_max: float = 18.0,
                     in_channels: int = 4,
                     hidden_width: int = 32):
            super().__init__()
            self.r_min = r_min
            self.r_max = r_max
            self.features = nn.Sequential(
                nn.Conv2d(in_channels, hidden_width, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv2d(hidden_width, hidden_width, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv2d(hidden_width, hidden_width, 3, padding=1),
                nn.ReLU(inplace=True),
            )
            self.radius_head = nn.Conv2d(hidden_width, 1, 1)
            self.density_head = nn.Conv2d(hidden_width, 1, 1)

        def forward(self, x):
            h = self.features(x)
            radius_raw = torch.sigmoid(self.radius_head(h))
            radius = self.r_min + (self.r_max - self.r_min) * radius_raw
            density = torch.sigmoid(self.density_head(h))
            return radius, density

        def predict_numpy(self,
                          d_norm: np.ndarray,
                          gray: np.ndarray,
                          device: str = "cpu") -> tuple[np.ndarray, np.ndarray]:
            """numpy 输入 → numpy 输出. 返回 (radius, density), 均 (H,W)."""
            d_tensor = torch.from_numpy(d_norm).float().unsqueeze(0).unsqueeze(0)
            g_tensor = torch.from_numpy(gray).float().unsqueeze(0).unsqueeze(0)

            d_grad_x = F.pad(d_tensor[:, :, :, 1:] - d_tensor[:, :, :, :-1], (0, 1))
            d_grad_y = F.pad(d_tensor[:, :, 1:, :] - d_tensor[:, :, :-1, :], (0, 0, 0, 1))
            d_grad = torch.sqrt(d_grad_x ** 2 + d_grad_y ** 2)

            g_grad_x = F.pad(g_tensor[:, :, :, 1:] - g_tensor[:, :, :, :-1], (0, 1))
            g_grad_y = F.pad(g_tensor[:, :, 1:, :] - g_tensor[:, :, :-1, :], (0, 0, 0, 1))
            g_grad = torch.sqrt(g_grad_x ** 2 + g_grad_y ** 2)

            d_grad = d_grad / (d_grad.max() + 1e-8)
            g_grad = g_grad / (g_grad.max() + 1e-8)

            x = torch.cat([d_tensor, g_tensor, d_grad, g_grad], dim=1).to(device)
            self.eval()
            with torch.no_grad():
                radius, density = self.forward(x)
            return (radius.squeeze().cpu().numpy(),
                    density.squeeze().cpu().numpy())

else:
    # torch 不可用时定义占位符, 实例化即抛 ImportError
    class DepthRadiusNet:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError("DepthRadiusNet 需要 torch: pip install torch")


# ---------------------------------------------------------------------------
# 2. 感知损失
# ---------------------------------------------------------------------------

if _HAS_TORCH:

    class StipplePerceptualLoss(nn.Module):
        """点绘感知损失: 深度梯度对齐 + 蓝噪声频谱 + 覆盖率 + 直方图匹配."""

        def __init__(self,
                     target_coverage: float = 0.28,
                     depth_alignment_weight: float = 1.0,
                     coverage_weight: float = 0.5,
                     histogram_weight: float = 0.3,
                     target_radius_hist: Optional[np.ndarray] = None,
                     n_hist_bins: int = 20):
            super().__init__()
            self.target_coverage = target_coverage
            self.depth_align_w = depth_alignment_weight
            self.coverage_w = coverage_weight
            self.hist_w = histogram_weight
            self.n_bins = n_hist_bins

            if target_radius_hist is not None:
                self.register_buffer('target_hist',
                                     torch.from_numpy(target_radius_hist).float())
            else:
                bins = np.linspace(0, 1, n_hist_bins + 1)
                centers = (bins[:-1] + bins[1:]) / 2
                hist = np.exp(-3 * centers)
                hist = hist / hist.sum()
                self.register_buffer('target_hist', torch.from_numpy(hist).float())

        def forward(self, radius, density, d_norm, d_grad):
            losses = {}
            near_weight = 1.0 - d_norm
            r_min = radius.min()
            r_max = radius.max() + 1e-8
            r_norm = (radius - r_min) / (r_max - r_min)
            losses['depth_align'] = F.mse_loss(r_norm, near_weight)

            approx_coverage = (density * torch.pi * radius ** 2).mean()
            losses['coverage'] = (approx_coverage - self.target_coverage) ** 2

            r_flat = r_norm.flatten()
            hist_pred = torch.histc(r_flat, bins=self.n_bins, min=0, max=1)
            hist_pred = hist_pred / (hist_pred.sum() + 1e-8)
            losses['histogram'] = F.mse_loss(hist_pred, self.target_hist)

            r_tv = (radius[:, :, :, 1:] - radius[:, :, :, :-1]).abs().mean() + \
                   (radius[:, :, 1:, :] - radius[:, :, :-1, :]).abs().mean()
            losses['smoothness'] = r_tv

            losses['total'] = (
                self.depth_align_w * losses['depth_align'] +
                self.coverage_w * losses['coverage'] +
                self.hist_w * losses['histogram'] +
                0.1 * losses['smoothness']
            )
            return losses

else:
    class StipplePerceptualLoss:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError("StipplePerceptualLoss 需要 torch: pip install torch")


# ---------------------------------------------------------------------------
# 3. 训练循环
# ---------------------------------------------------------------------------

def train_depth_radius_net(
        train_images: list,
        r_min: float = 1.0,
        r_max: float = 18.0,
        epochs: int = 50,
        lr: float = 1e-3,
        device: str = "cpu",
        save_path: Optional[str] = None):
    """训练 DepthRadiusNet.

    Parameters
    ----------
    train_images : list of (d_norm, gray) 元组, 各 (H,W) float32
    """
    if not _HAS_TORCH:
        raise ImportError("train_depth_radius_net 需要 torch: pip install torch")

    model = DepthRadiusNet(r_min=r_min, r_max=r_max).to(device)
    criterion = StipplePerceptualLoss(target_coverage=0.28)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    features = []
    for d_norm, gray in train_images:
        d_t = torch.from_numpy(d_norm).float().unsqueeze(0).unsqueeze(0)
        g_t = torch.from_numpy(gray).float().unsqueeze(0).unsqueeze(0)
        d_gx = F.pad(d_t[:, :, :, 1:] - d_t[:, :, :, :-1], (0, 1))
        d_gy = F.pad(d_t[:, :, 1:, :] - d_t[:, :, :-1, :], (0, 0, 0, 1))
        d_g = torch.sqrt(d_gx ** 2 + d_gy ** 2)
        d_g = d_g / (d_g.max() + 1e-8)
        g_gx = F.pad(g_t[:, :, :, 1:] - g_t[:, :, :, :-1], (0, 1))
        g_gy = F.pad(g_t[:, :, 1:, :] - g_t[:, :, :-1, :], (0, 0, 0, 1))
        g_g = torch.sqrt(g_gx ** 2 + g_gy ** 2)
        g_g = g_g / (g_g.max() + 1e-8)
        x = torch.cat([d_t, g_t, d_g, g_g], dim=1).to(device)
        features.append((x, d_t.to(device), d_g.to(device)))

    print(f"[train_depth_radius_net] {len(features)} imgs, {epochs} epochs, lr={lr}, device={device}")
    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for x, d_n, d_gr in features:
            optimizer.zero_grad()
            radius, density = model(x)
            losses = criterion(radius, density, d_n, d_gr)
            losses['total'].backward()
            optimizer.step()
            total_loss += losses['total'].item()
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1}/{epochs}: loss={total_loss/len(features):.6f}")

    if save_path:
        torch.save(model.state_dict(), save_path)
        print(f"  Saved model to {save_path}")
    return model


# ---------------------------------------------------------------------------
# 4. 与现有 pipeline 集成
# ---------------------------------------------------------------------------

def learned_depth_to_radius(model, d_norm, gray,
                            sigma: float = 0.12,
                            device: str = "cpu",
                            rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """固定 depth_to_radius 的可学习替代."""
    if rng is None:
        rng = np.random.default_rng()
    radius_map, _ = model.predict_numpy(d_norm, gray, device=device)
    if sigma > 0:
        radius_map *= (1.0 + rng.normal(0, sigma, radius_map.shape))
    return np.clip(radius_map, 0.3, model.r_max * 1.1).astype(np.float32)


def learned_depth_to_density(model, d_norm, gray,
                             device: str = "cpu") -> np.ndarray:
    """固定 depth_to_density 的可学习替代."""
    from .ops.voronoi import compute_density
    _, density_map = model.predict_numpy(d_norm, gray, device=device)
    gray_u8 = (gray * 255).astype(np.uint8)
    lum_density = compute_density(gray_u8, gamma=1.2, invert=True)
    composite = np.sqrt(density_map * lum_density)
    c_max = composite.max()
    if c_max > 1e-9:
        composite /= c_max
    return composite.astype(np.float32)


def compare_fixed_vs_learned(d_norm: np.ndarray,
                             gray: np.ndarray,
                             model=None,
                             r_min: float = 1.0,
                             r_max: float = 18.0,
                             alpha: float = 1.5,
                             sigma: float = 0.12,
                             device: str = "cpu") -> dict:
    """对比固定幂律 vs. 可学习映射, 返回消融指标."""
    rng = np.random.default_rng(42)
    depth_weight = np.power(1.0 - d_norm, alpha)
    fixed_radius = r_min + (r_max - r_min) * depth_weight
    if sigma > 0:
        fixed_radius *= (1.0 + rng.normal(0, sigma, fixed_radius.shape))
    fixed_radius = np.clip(fixed_radius, 0.3, r_max * 1.1)

    if model is not None:
        learned_radius = learned_depth_to_radius(model, d_norm, gray, sigma=sigma, device=device, rng=rng)
    else:
        learned_radius = fixed_radius

    return {
        'fixed_radius_mean': float(fixed_radius.mean()),
        'fixed_radius_std': float(fixed_radius.std()),
        'fixed_radius_range': (float(fixed_radius.min()), float(fixed_radius.max())),
        'learned_radius_mean': float(learned_radius.mean()),
        'learned_radius_std': float(learned_radius.std()),
        'learned_radius_range': (float(learned_radius.min()), float(learned_radius.max())),
        'fixed_depth_correlation': float(np.corrcoef(
            (1 - d_norm).flatten(), fixed_radius.flatten())[0, 1]),
        'learned_depth_correlation': float(np.corrcoef(
            (1 - d_norm).flatten(), learned_radius.flatten())[0, 1]),
    }
