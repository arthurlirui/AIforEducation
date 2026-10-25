"""模块 6：三维场景图构建（Canvas3D-v2）。

将 stage1 的多物体分割 + stage2 的物体级 3DGS 注册表组织为带节点属性与
关系边的三维场景图，作为视角可控新视角生成（stage7）与空间关系可控视频
生成（stage8）的统一中间表示。

关系类型:
  - 2D 投影关系 (left_of/right_of/above/below)
  - 深度关系 (in_front_of/behind)
  - 拓扑关系 (inside/adjacent/occludes)
  - 物理支撑启发式 (supports/leans_on)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

from ...common.config import Settings
from ..schemas import (
    SceneGraph,
    SceneGraphNode,
    SpatialRelation,
    SpatialRelationType,
    Stage1Output,
    Stage2Output,
    Stage6Output,
    ObjectCategory,
)

logger = logging.getLogger(__name__)


def _bbox_volume(b: tuple[float, float, float, float, float, float]) -> float:
    return max(0.0, b[3] - b[0]) * max(0.0, b[4] - b[1]) * max(0.0, b[5] - b[2])


def _bbox_height(b: tuple[float, float, float, float, float, float]) -> float:
    return max(0.0, b[4] - b[1])


def _bbox_center(b: tuple[float, float, float, float, float, float]) -> tuple[float, float, float]:
    return ((b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0)


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    a_b = (a > 127).astype(np.uint8)
    b_b = (b > 127).astype(np.uint8)
    inter = float(np.logical_and(a_b, b_b).sum())
    union = float(np.logical_or(a_b, b_b).sum())
    return inter / union if union > 0 else 0.0


def _mask_overlap_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """a ∩ b / a（a 被 b 覆盖的比例）。"""
    a_b = (a > 127).astype(np.uint8)
    b_b = (b > 127).astype(np.uint8)
    inter = float(np.logical_and(a_b, b_b).sum())
    area_a = float(a_b.sum())
    return inter / area_a if area_a > 0 else 0.0


def build_scene_graph(
    stage1: Stage1Output,
    stage2: Stage2Output,
    project_dir: Path,
    settings: Settings,
) -> Stage6Output:
    """构建三维场景图。"""
    stage6_dir = project_dir / "stage6"
    stage6_dir.mkdir(parents=True, exist_ok=True)

    h, w = stage1.height, stage1.width
    focal = getattr(settings, "focal_length", 1000.0)

    # ── 1. 节点构建 ──
    nodes: list[SceneGraphNode] = []
    # 前景节点
    total_area = float(w * h)
    cx_img, cy_img = w / 2.0, h / 2.0
    max_dist = float(np.hypot(cx_img, cy_img))

    for obj in stage1.objects:
        record = stage2.registry.get_model(obj.object_id)
        bbox_3d = record.bbox_3d if record is not None else (
            0.0, 0.0, obj.depth_range[0], 0.0, 0.0, obj.depth_range[1])
        center_3d = record.center_3d if record is not None else (0.0, 0.0, 0.0)
        vol = _bbox_volume(bbox_3d)
        height_3d = _bbox_height(bbox_3d)
        # 显著性：面积 + 置信度 + 中心偏置
        bbox_area = float((obj.bbox[2] - obj.bbox[0]) * (obj.bbox[3] - obj.bbox[1]))
        norm_area = min(1.0, bbox_area / max(1.0, total_area * 0.5))
        bbox_cx = (obj.bbox[0] + obj.bbox[2]) / 2.0
        bbox_cy = (obj.bbox[1] + obj.bbox[3]) / 2.0
        center_bias = 1.0 - min(1.0, float(np.hypot(bbox_cx - cx_img, bbox_cy - cy_img)) / max(1e-6, max_dist))
        salience = 0.5 * norm_area + 0.3 * float(obj.confidence) + 0.2 * center_bias

        nodes.append(SceneGraphNode(
            object_id=obj.object_id,
            label=obj.label,
            category=obj.category,
            node_type="foreground",
            center_3d=center_3d,
            bbox_3d=bbox_3d,
            volume=vol,
            height_3d=height_3d,
            depth_range=obj.depth_range,
            ply_path=record.ply_path if record is not None else None,
            mask_path=obj.mask_path,
            salience=salience,
        ))

    # ── 2. 场景尺度 ──
    if nodes:
        all_bboxes = np.array([n.bbox_3d for n in nodes], dtype=np.float64)
        extent = (
            float(all_bboxes[:, 3].max() - all_bboxes[:, 0].min()),
            float(all_bboxes[:, 4].max() - all_bboxes[:, 1].min()),
            float(all_bboxes[:, 5].max() - all_bboxes[:, 2].min()),
        )
    else:
        extent = (float(w), float(h), 1.0)
    eps_xy = max(1e-3, getattr(settings, "scene_graph_threshold_xy", 0.1) * extent[0])
    eps_adj = max(1e-3, 0.02 * extent[0])
    overlap_thr = getattr(settings, "scene_graph_overlap_threshold", 0.05)

    # ── 3. 背景节点 ──
    bg_node = SceneGraphNode(
        object_id=-1,
        label="background",
        category=ObjectCategory.BACKGROUND,
        node_type="background",
        center_3d=(0.0, 0.0, float(np.mean([n.depth_range[1] for n in nodes])) if nodes else 10.0),
        bbox_3d=(-extent[0] / 2, -extent[1] / 2, 8.0, extent[0] / 2, extent[1] / 2, 12.0),
        volume=extent[0] * extent[1] * 4.0,
        height_3d=extent[1],
        depth_range=(8.0, 12.0),
        ply_path=stage2.registry.background_ply_path,
        mask_path=stage1.background_mask_path,
        salience=0.0,
    )
    nodes.append(bg_node)
    background_node_id = -1

    # ── 4. 关系构建 ──
    relations: list[SpatialRelation] = []
    fg_nodes = [n for n in nodes if n.node_type == "foreground"]

    # 预加载 masks 用于拓扑关系
    masks_cache: dict[int, np.ndarray | None] = {}
    for n in fg_nodes:
        if n.mask_path is not None and Path(n.mask_path).exists():
            masks_cache[n.object_id] = cv2.imread(str(n.mask_path), cv2.IMREAD_GRAYSCALE)
        else:
            masks_cache[n.object_id] = None

    for i, a in enumerate(fg_nodes):
        for j, b in enumerate(fg_nodes):
            if i == j:
                continue
            # 2D 投影关系（用 center_3d 的 x/y 分量近似，因为画作基本在 z=const 平面）
            dx = b.center_3d[0] - a.center_3d[0]
            dy = b.center_3d[1] - a.center_3d[1]
            if abs(dx) > eps_xy:
                if dx > 0:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.LEFT_OF,
                        confidence=min(1.0, abs(dx) / (eps_xy + 1e-6)),
                        distance_3d=float(np.linalg.norm(np.array(a.center_3d) - np.array(b.center_3d))),
                    ))
                else:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.RIGHT_OF,
                        confidence=min(1.0, abs(dx) / (eps_xy + 1e-6)),
                        distance_3d=float(np.linalg.norm(np.array(a.center_3d) - np.array(b.center_3d))),
                    ))
            if abs(dy) > eps_xy:
                if dy > 0:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.BELOW,
                        confidence=min(1.0, abs(dy) / (eps_xy + 1e-6)),
                    ))
                else:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.ABOVE,
                        confidence=min(1.0, abs(dy) / (eps_xy + 1e-6)),
                    ))

            # 深度关系
            d_gap = a.depth_range[1] - b.depth_range[0]  # a 在前则 a.far < b.near → 负值
            if a.depth_range[1] < b.depth_range[0]:
                relations.append(SpatialRelation(
                    src_id=a.object_id, dst_id=b.object_id,
                    rel_type=SpatialRelationType.IN_FRONT_OF,
                    confidence=min(1.0, (b.depth_range[0] - a.depth_range[1]) / max(1e-3, extent[2])),
                    depth_gap=float(b.depth_range[0] - a.depth_range[1]),
                ))
            elif a.depth_range[0] > b.depth_range[1]:
                relations.append(SpatialRelation(
                    src_id=a.object_id, dst_id=b.object_id,
                    rel_type=SpatialRelationType.BEHIND,
                    confidence=min(1.0, (a.depth_range[0] - b.depth_range[1]) / max(1e-3, extent[2])),
                    depth_gap=float(a.depth_range[0] - b.depth_range[1]),
                ))
            else:
                # 重叠深度区间：按质心比较
                if a.center_3d[2] < b.center_3d[2]:
                    rel = SpatialRelationType.IN_FRONT_OF
                else:
                    rel = SpatialRelationType.BEHIND
                relations.append(SpatialRelation(
                    src_id=a.object_id, dst_id=b.object_id,
                    rel_type=rel,
                    confidence=0.5,
                    depth_gap=abs(float(a.center_3d[2] - b.center_3d[2])),
                ))

            # 拓扑关系：occludes / inside / adjacent
            ma, mb = masks_cache.get(a.object_id), masks_cache.get(b.object_id)
            if ma is not None and mb is not None and ma.shape == mb.shape:
                overlap = _mask_overlap_ratio(ma, mb)
                if overlap > overlap_thr and a.center_3d[2] < b.center_3d[2]:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.OCCLUDES,
                        confidence=min(1.0, overlap),
                        overlap_ratio=float(overlap),
                    ))
                # inside: a 几乎完全在 b 内
                iou = _mask_iou(ma, mb)
                if iou > 0.9 and overlap > 0.8:
                    relations.append(SpatialRelation(
                        src_id=a.object_id, dst_id=b.object_id,
                        rel_type=SpatialRelationType.INSIDE,
                        confidence=float(iou),
                        overlap_ratio=float(overlap),
                    ))
                # adjacent: mask 距离小且无交叠
                if overlap < 1e-3:
                    # 用膨胀检测邻接
                    kernel = np.ones((5, 5), np.uint8)
                    a_dil = cv2.dilate((ma > 127).astype(np.uint8), kernel)
                    b_b = (mb > 127).astype(np.uint8)
                    if float(np.logical_and(a_dil > 0, b_b > 0).sum()) > 0:
                        relations.append(SpatialRelation(
                            src_id=a.object_id, dst_id=b.object_id,
                            rel_type=SpatialRelationType.ADJACENT,
                            confidence=0.7,
                        ))

        # 物理支撑启发式：a 在 b 之上且底面 ≈ b 顶面
        for b in fg_nodes:
            if a.object_id == b.object_id:
                continue
            a_bottom = a.bbox_3d[4]
            b_top = b.bbox_3d[1]
            if a.center_3d[1] < b.center_3d[1] and abs(a_bottom - b_top) < 0.05 * extent[1]:
                relations.append(SpatialRelation(
                    src_id=b.object_id, dst_id=a.object_id,
                    rel_type=SpatialRelationType.SUPPORTS,
                    confidence=0.6,
                ))
                relations.append(SpatialRelation(
                    src_id=a.object_id, dst_id=b.object_id,
                    rel_type=SpatialRelationType.LEANS_ON,
                    confidence=0.6,
                ))

    # 前景 vs 背景
    for n in fg_nodes:
        relations.append(SpatialRelation(
            src_id=n.object_id, dst_id=background_node_id,
            rel_type=SpatialRelationType.IN_FRONT_OF,
            confidence=0.95,
            depth_gap=float(bg_node.depth_range[0] - n.depth_range[1])
            if bg_node.depth_range[0] > n.depth_range[1] else 0.0,
        ))

    # ── 5. 序列化 ──
    graph = SceneGraph(
        nodes=nodes,
        relations=relations,
        background_node_id=background_node_id,
        scene_extent=extent,
        focal_length=focal,
        principal_point=(w / 2.0, h / 2.0),
    )
    graph_path = stage6_dir / "scene_graph.json"
    graph_dump = graph.model_dump()
    # Path → str 以便 JSON 序列化
    for n in graph_dump["nodes"]:
        if n.get("ply_path") is not None:
            n["ply_path"] = str(n["ply_path"])
        if n.get("mask_path") is not None:
            n["mask_path"] = str(n["mask_path"])
    if graph_dump.get("graph_path") is not None:
        graph_dump["graph_path"] = str(graph_path)
    graph_path.write_text(json.dumps(graph_dump, indent=2, ensure_ascii=False), encoding="utf-8")
    graph.graph_path = graph_path

    output = Stage6Output(
        scene_graph=graph,
        graph_path=graph_path,
        num_nodes=len(nodes),
        num_relations=len(relations),
    )
    logger.info("模块 6 完成: %d 节点, %d 关系 → %s",
                len(nodes), len(relations), graph_path.name)
    return output


def run_stage6(
    stage1: Stage1Output,
    stage2: Stage2Output,
    project_dir: Path,
    settings: Settings,
) -> Stage6Output:
    """执行模块 6 完整流程。"""
    return build_scene_graph(stage1, stage2, project_dir, settings)
