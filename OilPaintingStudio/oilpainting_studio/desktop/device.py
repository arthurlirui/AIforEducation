"""设备探测与自动回退策略 (设计文档 §3)。

三档推理目标: gpu → cpu → mock, 按依赖可用性逐级回退:

    ┌─────────┐   torch+CUDA 可用   ┌──────────┐
    │  GPU    │ ──────────────────▶ │ YOLO/DA  │  真模型 · cuda:0
    └─────────┘                     └──────────┘
        │ 无 CUDA / CUDA 初始化失败
        ▼
    ┌─────────┐   torch 可用        ┌──────────┐
    │  CPU    │ ──────────────────▶ │ YOLO/DA  │  真模型 · cpu (慢)
    └─────────┘                     └──────────┘
        │ torch / ultralytics 缺失
        ▼
    ┌─────────┐
    │  MOCK   │  K-Means 聚类 / 梯度深度 (瞬时, 流程可验证)
    └─────────┘

用户可强制指定 (demo 模式选择器), 强制不可用项时自动落到下一档并如实上报。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class DeviceTier(str, Enum):
    GPU = "gpu"
    CPU = "cpu"
    MOCK = "mock"


class BackendKind(str, Enum):
    YOLO = "yolo"          # ultralytics YOLO-seg
    DAv2 = "dav2"          # Depth Anything V2
    MOCK_SEGMENT = "mock_segment"
    MOCK_DEPTH = "mock_depth"


@dataclass
class BackendStatus:
    kind: BackendKind
    available: bool
    device: DeviceTier
    detail: str = ""
    load_ms: int = 0                 # 模型加载耗时
    infer_ms: int = 0                # 单帧推理耗时 (实测)


@dataclass
class DeviceReport:
    """设备探测结果, 同时作为 demo 的 system info 数据源。"""
    tier: DeviceTier
    torch_version: str | None = None
    cuda_available: bool = False
    cuda_device_name: str | None = None
    vram_gb: float | None = None
    cpu_name: str | None = None
    ram_gb: float | None = None
    backends: dict[str, BackendStatus] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "torch_version": self.torch_version,
            "cuda_available": self.cuda_available,
            "cuda_device_name": self.cuda_device_name,
            "vram_gb": self.vram_gb,
            "cpu_name": self.cpu_name,
            "ram_gb": self.ram_gb,
            "backends": {
                k: {"kind": v.kind.value, "available": v.available,
                    "device": v.device.value, "detail": v.detail,
                    "load_ms": v.load_ms, "infer_ms": v.infer_ms}
                for k, v in self.backends.items()
            },
        }


def _cpu_name() -> str:
    import platform
    return platform.processor() or platform.machine()


def _ram_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1e9, 1)
    except ImportError:
        return None


def probe_device(prefer: str = "auto") -> DeviceReport:
    """探测当前机器可用的推理档位。

    prefer: "auto" | "gpu" | "cpu" | "mock"。
    返回的 tier 一定是实际可用档 (不可用则自动下落)。
    """
    report = DeviceReport(tier=DeviceTier.MOCK,
                          cpu_name=_cpu_name(), ram_gb=_ram_gb())

    # ── mock 后端始终可用 ──
    report.backends["segment"] = BackendStatus(
        kind=BackendKind.MOCK_SEGMENT, available=True, device=DeviceTier.MOCK,
        detail="K-Means 颜色聚类 + 连通域 (瞬时)")
    report.backends["depth"] = BackendStatus(
        kind=BackendKind.MOCK_DEPTH, available=True, device=DeviceTier.MOCK,
        detail="纵向梯度 + 亮度调制 (瞬时)")

    # ── torch 探测 ──
    torch_ok = False
    try:
        import torch
        report.torch_version = torch.__version__
        report.cuda_available = torch.cuda.is_available()
        if report.cuda_available:
            report.cuda_device_name = torch.cuda.get_device_name(0)
            report.vram_gb = round(
                torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
        torch_ok = True
    except ImportError:
        report.torch_version = None
        logger.info("torch 未安装 → 只能 mock 推理")

    # ── 用户强制 mock ──
    if prefer == "mock":
        report.tier = DeviceTier.MOCK
        return report

    # ── ultralytics (YOLO) 探测 ──
    yolo_available = False
    try:
        import ultralytics  # noqa: F401
        yolo_available = True
    except ImportError:
        logger.info("ultralytics 未安装 → 分割退化为 mock")

    # ── 决定档位 ──
    if torch_ok and report.cuda_available and prefer in ("auto", "gpu"):
        report.tier = DeviceTier.GPU
    elif torch_ok and prefer in ("auto", "gpu", "cpu"):
        if prefer == "gpu":
            logger.warning("强制 GPU 但 CUDA 不可用 → 回退 CPU")
        report.tier = DeviceTier.CPU
    # else: 保持 MOCK (prefer=cpu 但 torch 缺失时也落到 mock)

    if report.tier in (DeviceTier.GPU, DeviceTier.CPU):
        if yolo_available:
            dev = "cuda:0" if report.tier == DeviceTier.GPU else "cpu"
            report.backends["segment"] = BackendStatus(
                kind=BackendKind.YOLO, available=True, device=report.tier,
                detail=f"YOLO-seg on {dev}")
        # DA-V2: 依赖外部权重与仓库, 未配置时深度仍走 mock (可如实展示混合模式)
        try:
            from ..revive.config import load_settings
            s = load_settings()
            da_path = Path(s.da_v2_model)
            if da_path.exists() and torch_ok:
                report.backends["depth"] = BackendStatus(
                    kind=BackendKind.DAv2, available=True, device=report.tier,
                    detail=f"DepthAnythingV2 ({da_path.name})")
            else:
                report.backends["depth"].detail = (
                    f"mock (未找到权重 {s.da_v2_model})")
        except Exception:
            pass  # 深度保持 mock

    return report


@dataclass
class DeviceChoice:
    """一次推理的设备决策记录 (喂给 demo 的 UI 显示)。"""
    requested: str
    effective: DeviceTier
    reason: str


def resolve_choice(prefer: str, report: DeviceReport) -> DeviceChoice:
    """把用户偏好解析成实际档位, 并给出回退原因 (UI 展示用)。

    order 下标越大算力越弱 (gpu=0 < cpu=1 < mock=2);
    期望档下标 >= 机器实际档下标 时说明实际档更弱 → 回退到实际档。
    """
    table = {
        "gpu": DeviceTier.GPU, "cpu": DeviceTier.CPU, "mock": DeviceTier.MOCK,
        "auto": report.tier,          # auto = 直接采用探测结果
    }
    want = table.get(prefer, report.tier)
    if want == DeviceTier.MOCK and prefer == "mock":
        return DeviceChoice("mock", DeviceTier.MOCK, "用户选择 mock 演示模式")
    order = [DeviceTier.GPU, DeviceTier.CPU, DeviceTier.MOCK]
    idx_want = order.index(want)
    idx_have = order.index(report.tier)
    if idx_have > idx_want:
        # 实际档弱于期望档 (如请求 gpu 但机器只有 cpu) → 回退
        return DeviceChoice(want.value, report.tier,
                            f"请求 {want.value.upper()} 不可用 → 自动回退 {report.tier.value.upper()}")
    # 期望档在机器能力范围内 → 尊重请求 (含 auto 直接用探测档)
    return DeviceChoice(want.value, want,
                        "自动档" if prefer == "auto" else f"运行于 {want.value.upper()}")


class Benchmark:
    """推理基准 (论文 demo 的量化表格数据源)。"""

    def __init__(self, engine):
        self.engine = engine

    def run(self) -> dict:
        """对当前后端跑一次分割+深度基准, 返回耗时结构。"""
        t0 = time.perf_counter()
        result = self.engine.run_pipeline()
        total_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "total_ms": total_ms,
            "device": self.engine.report.tier.value,
            "segment_backend": self.engine.report.backends["segment"].kind.value,
            "depth_backend": self.engine.report.backends["depth"].kind.value,
            "num_objects": result.get("num_objects", 0),
        }
