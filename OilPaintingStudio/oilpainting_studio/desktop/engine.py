"""PaintingStudio 论文 demo 计算引擎。

复用 revive 的 mock 分割/深度算法与 GUI 的目录协议, 叠加:
- 设备档位策略 (gpu/cpu/mock 自动回退, device.py)
- 真模型注入点: YOLO-seg (ultralytics) / DA-V2 (torch), 按档位选择
- 计时与运行日志 (demo UI 的 timeline 面板数据源)

论文 demo 场景 = 固定示例画作 ("此画可动否?") 的 3 步演示:
  ① 语义分割 (PaintParse)  → ② 深度估计 → ③ 3D 化身生成 (MonoSplat)
每步产物落 projects/_demo/, 可在桌面窗口里逐帧查看。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..gui.imgio import imread, imwrite
from ..revive.stage1.segment import segment_mock
from ..revive.stage1.depth import estimate_depth_mock
from .device import (BackendKind, DeviceReport, DeviceTier,
                     probe_device, resolve_choice)

logger = logging.getLogger(__name__)

StepFn = Callable[[np.ndarray, dict], dict]


@dataclass
class StepResult:
    name: str
    ok: bool
    ms: int
    summary: str
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class DemoRun:
    """一次 demo 演出的完整记录 (前端 timeline 渲染数据)。"""
    device_requested: str
    device_effective: str
    device_reason: str
    steps: list[StepResult] = field(default_factory=list)
    total_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "device_requested": self.device_requested,
            "device_effective": self.device_effective,
            "device_reason": self.device_reason,
            "total_ms": self.total_ms,
            "steps": [
                {"name": s.name, "ok": s.ok, "ms": s.ms,
                 "summary": s.summary, "artifacts": s.artifacts}
                for s in self.steps
            ],
        }


class PaintingStudioDemoEngine:
    """demo 计算核心: 单图 → 分割 → 深度 → 3D 点云, 全档位可跑。"""

    # demo 步骤名 (与论文 Canvas3D 术语对齐)
    STEP_NAMES = ("PaintParse 分割", "MonoDepth 深度", "MonoSplat 3D 化身")

    def __init__(self, projects_root: Path, prefer: str = "auto"):
        self.projects_root = projects_root
        self.report: DeviceReport = probe_device(prefer)
        self.choice = resolve_choice(prefer, self.report)
        self._yolo = None      # 惰性加载的 ultralytics 模型
        self._yolo_device = None

    # ── 后端选择 ──

    def _segment_backend(self):
        """按档位返回 (fn, kind_str)。真 YOLO 加载失败自动落 mock 并记录。"""
        seg = self.report.backends["segment"]
        if seg.kind == BackendKind.YOLO and self.choice.effective in (DeviceTier.GPU, DeviceTier.CPU):
            dev = "cuda:0" if self.choice.effective == DeviceTier.GPU else "cpu"
            try:
                from ..revive.config import load_settings
                model_name = load_settings().yolo_model
                if self._yolo is None or self._yolo_device != dev:
                    t0 = time.perf_counter()
                    from ultralytics import YOLO
                    self._yolo = YOLO(model_name)
                    self._yolo.to(dev)
                    self._yolo_device = dev
                    seg.load_ms = int((time.perf_counter() - t0) * 1000)
                    logger.info("YOLO 已加载到 %s (%d ms)", dev, seg.load_ms)

                def run_yolo(image_rgb: np.ndarray) -> list[dict]:
                    results = self._yolo(image_rgb, verbose=False, device=dev)
                    dets = []
                    for r in results:
                        if r.masks is None:
                            continue
                        masks = r.masks.data.cpu().numpy()
                        boxes = r.boxes
                        for i in range(len(masks)):
                            mask = (masks[i] * 255).astype(np.uint8)
                            if mask.shape[:2] != image_rgb.shape[:2]:
                                mask = cv2.resize(
                                    mask, (image_rgb.shape[1], image_rgb.shape[0]),
                                    interpolation=cv2.INTER_NEAREST)
                            x0, y0, x1, y1 = boxes.xyxy[i].cpu().numpy().astype(int)
                            cls_id = int(boxes.cls[i].item())
                            dets.append({
                                "label": self._yolo.names[cls_id],
                                "confidence": float(boxes.conf[i].item()),
                                "mask": mask, "bbox": (x0, y0, x1, y1),
                            })
                    return dets
                return run_yolo, f"yolo:{dev}"
            except Exception as e:
                logger.warning("YOLO 加载失败 (%s) → mock 分割", e)
                seg.available = False
                seg.detail = f"加载失败: {e.__class__.__name__}"
                self.report.backends["segment"].kind = BackendKind.MOCK_SEGMENT
        return segment_mock, "mock:kmeans"

    def _depth_backend(self):
        dep = self.report.backends["depth"]
        if dep.kind == BackendKind.DAv2:
            # DA-V2 真推理注入点 (权重就位时启用); 当前环境保持 mock
            pass
        return estimate_depth_mock, "mock:gradient"

    # ── demo 主流程 ──

    def run(self, painting_path: Path, out_dir: Path) -> DemoRun:
        """三步 demo: 分割 → 深度 → 3D 点云, 每步计时并落盘产物。"""
        run = DemoRun(self.choice.requested, self.choice.effective.value,
                      self.choice.reason)
        out_dir.mkdir(parents=True, exist_ok=True)
        image = imread(painting_path)
        if image is None:
            raise FileNotFoundError(painting_path)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        total0 = time.perf_counter()

        # ① PaintParse
        t0 = time.perf_counter()
        seg_fn, seg_kind = self._segment_backend()
        dets = seg_fn(image_rgb)
        # 全部拒绝/空检出时保底一个连通域结果
        if not dets:
            dets = segment_mock(image_rgb)
            seg_kind += "+fallback"
        seg_ms = int((time.perf_counter() - t0) * 1000)

        artifacts: dict[str, str] = {}
        overlay = image_rgb.copy()
        for i, d in enumerate(dets):
            color = tuple(int(c) for c in
                          np.random.default_rng(i).integers(60, 255, 3))
            overlay[d["mask"] > 0] = color
            imwrite(out_dir / f"mask_{i:02d}_{d['label'].replace(' ', '_')}.png",
                    d["mask"])
        overlay_img = cv2.addWeighted(image_rgb, 0.55, overlay, 0.45, 0)
        imwrite(out_dir / "overlay.png", cv2.cvtColor(overlay_img, cv2.COLOR_RGB2BGR))
        artifacts["overlay"] = "overlay.png"
        artifacts["num_masks"] = str(len(dets))
        run.steps.append(StepResult(
            self.STEP_NAMES[0], True, seg_ms,
            f"{len(dets)} 个物体 ({seg_kind})", artifacts))
        self.report.backends["segment"].infer_ms = seg_ms

        # ② MonoDepth
        t0 = time.perf_counter()
        dep_fn, dep_kind = self._depth_backend()
        depth = dep_fn(image_rgb)
        dep_ms = int((time.perf_counter() - t0) * 1000)
        d_min, d_max = depth.min(), depth.max()
        depth_u16 = ((depth - d_min) / (d_max - d_min + 1e-8) * 65535).astype(np.uint16)
        imwrite(out_dir / "depth.png", depth_u16)
        depth_vis = cv2.applyColorMap(
            cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
            cv2.COLORMAP_TURBO)
        imwrite(out_dir / "depth_vis.png", depth_vis)
        run.steps.append(StepResult(
            self.STEP_NAMES[1], True, dep_ms,
            f"深度范围 [{d_min:.1f}, {d_max:.1f}] ({dep_kind})",
            {"depth_vis": "depth_vis.png"}))
        self.report.backends["depth"].infer_ms = dep_ms

        # ③ MonoSplat: 深度反投影 → 顶点色点云 PLY (复用 revive gs2d_init)
        t0 = time.perf_counter()
        ply_rel = "scene.ply"
        self._export_pointcloud(image_rgb, depth, out_dir / ply_rel)
        gs_ms = int((time.perf_counter() - t0) * 1000)
        num_pts = (out_dir / ply_rel).stat().st_size // 60  # 粗略点数估计
        run.steps.append(StepResult(
            self.STEP_NAMES[2], True, gs_ms,
            f"点云 PLY ({num_pts:,} 点, RGB-D 反投影)",
            {"ply": ply_rel}))

        run.total_ms = int((time.perf_counter() - total0) * 1000)
        return run

    def _export_pointcloud(self, image_rgb: np.ndarray, depth: np.ndarray,
                           ply_path: Path, stride: int = 4) -> None:
        """RGB-D 反投影为顶点色点云 (stride 降采样, demo 流畅)。"""
        from ..revive.config import load_settings
        focal = load_settings().focal_length
        h, w = depth.shape[:2]
        ys, xs = np.mgrid[0:h:stride, 0:w:stride]
        z = depth[ys, xs].astype(np.float32)
        x = (xs - w / 2) * z / focal
        y = (ys - h / 2) * z / focal
        rgb = image_rgb[ys, xs]
        pts = np.stack([x, y, z], axis=-1).reshape(-1, 3)
        cols = rgb.reshape(-1, 3)
        # PLY ascii 写出
        lines = ["ply", "format ascii 1.0",
                 f"element vertex {len(pts)}",
                 "property float x", "property float y", "property float z",
                 "property uchar red", "property uchar green", "property uchar blue",
                 "end_header"]
        header = "\n".join(lines) + "\n"
        body = "\n".join(
            f"{p[0]:.3f} {p[1]:.3f} {p[2]:.3f} {c[0]} {c[1]} {c[2]}"
            for p, c in zip(pts[::1], cols[::1]))
        ply_path.write_text(header + body, encoding="ascii")
