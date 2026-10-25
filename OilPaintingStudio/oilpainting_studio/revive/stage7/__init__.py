"""模块 7：视角可控新视角渲染（Canvas3D-v2）。

用户指定视角轨迹（手动 / 轨道 / 推拉 / 俯仰 / 自动），从编辑后场景渲染多视角
关键帧流，附带每帧每节点可见性 mask。可见性 mask 是 stage8 空间关系可控视频
的关键输入：它告诉视频模型「这个视角下哪些物体应该可见、哪些被遮挡」。

模式:
  - manual: 用户直接给 poses 列表
  - orbit: 围绕场景图某个节点做轨道
  - dolly:  沿场景主轴推拉
  - crane:  垂直俯仰
  - auto_orbit: 以显著性最高的前景节点为焦点自动环绕
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

from ...common.config import Settings
from ..schemas import (
    CameraPose,
    SceneGraph,
    Stage3Output,
    Stage7Output,
    ViewframeSpec,
    ViewpointTrajectory,
)
from ..stage3.reposition import load_surfels_from_ply

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 视角轨迹生成
# ──────────────────────────────────────────────────────────────

def generate_trajectory(
    scene_graph: SceneGraph,
    settings: Settings,
    mode: str | None = None,
    focus_node_id: int | None = None,
    num_poses: int | None = None,
    orbit_angle_deg: float | None = None,
    manual_poses: list[CameraPose] | None = None,
) -> ViewpointTrajectory:
    """生成视角轨迹。"""
    mode = mode or getattr(settings, "view_trajectory_mode", "auto_orbit")
    num_poses = num_poses or int(getattr(settings, "view_num_poses", 8))
    orbit_angle = orbit_angle_deg or float(getattr(settings, "view_orbit_angle_deg", 30.0))

    fg_nodes = [n for n in scene_graph.nodes if n.node_type == "foreground"]

    if mode == "manual" and manual_poses:
        return ViewpointTrajectory(poses=manual_poses, mode="manual")

    # 选择焦点节点
    if focus_node_id is not None:
        focus = scene_graph.get_node(focus_node_id)
    else:
        focus = max(fg_nodes, key=lambda n: n.salience) if fg_nodes else None

    if focus is None:
        # 退化：用场景中心
        focus_center = (0.0, 0.0, float(np.mean([n.depth_range[0] for n in scene_graph.nodes]) if scene_graph.nodes else 5.0))
        radius = 3.0
    else:
        focus_center = focus.center_3d
        radius = 1.5 * max(focus.height_3d, 0.5)

    poses: list[CameraPose] = []

    if mode == "orbit" or mode == "auto_orbit":
        # 围绕焦点做水平轨道
        angle_rad = np.deg2rad(orbit_angle)
        # 从 -angle/2 到 +angle/2 扫过
        for i in range(num_poses):
            t = i / max(1, num_poses - 1)
            a = -angle_rad / 2 + angle_rad * t
            x = focus_center[0] + radius * np.sin(a)
            z = focus_center[2] + radius * np.cos(a)
            y = focus_center[1]
            poses.append(CameraPose(
                position=(float(x), float(y), float(z)),
                look_at=focus_center,
            ))
        return ViewpointTrajectory(
            poses=poses, mode=mode, focus_node_id=focus.object_id if focus else None,
            orbit_params={"center": list(focus_center), "radius": radius,
                          "angle_range_deg": orbit_angle},
        )

    if mode == "dolly":
        # 沿主轴推拉：从远到近
        for i in range(num_poses):
            t = i / max(1, num_poses - 1)
            z = focus_center[2] + radius * (1.5 - t)
            poses.append(CameraPose(
                position=(focus_center[0], focus_center[1], float(z)),
                look_at=focus_center,
            ))
        return ViewpointTrajectory(poses=poses, mode="dolly",
                                   focus_node_id=focus.object_id if focus else None)

    if mode == "crane":
        # 垂直俯仰：y 从低到高
        for i in range(num_poses):
            t = i / max(1, num_poses - 1)
            y = focus_center[1] + radius * (t - 0.5)
            z = focus_center[2] + radius * 0.8
            poses.append(CameraPose(
                position=(focus_center[0], float(y), float(z)),
                look_at=focus_center,
            ))
        return ViewpointTrajectory(poses=poses, mode="crane",
                                   focus_node_id=focus.object_id if focus else None)

    # 默认 fallback: auto_orbit
    return generate_trajectory(scene_graph, settings, mode="auto_orbit",
                               focus_node_id=focus_node_id,
                               num_poses=num_poses, orbit_angle_deg=orbit_angle)


# ──────────────────────────────────────────────────────────────
# 视角渲染
# ──────────────────────────────────────────────────────────────

def _look_at_matrix(
    position: tuple[float, float, float],
    look_at: tuple[float, float, float],
    up: tuple[float, float, float],
) -> np.ndarray:
    """构造 view matrix (4x4)，将世界坐标变换到相机坐标。"""
    pos = np.array(position, dtype=np.float64)
    tgt = np.array(look_at, dtype=np.float64)
    up_v = np.array(up, dtype=np.float64)
    forward = tgt - pos
    forward = forward / (np.linalg.norm(forward) + 1e-9)
    right = np.cross(forward, up_v)
    right = right / (np.linalg.norm(right) + 1e-9)
    up_cam = np.cross(right, forward)
    R = np.stack([right, up_cam, -forward], axis=0)  # (3,3)
    T = -R @ pos
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = T
    return M


def render_viewframe(
    surfels: np.ndarray,
    pose: CameraPose,
    img_h: int,
    img_w: int,
    focal: float,
    scene_graph: SceneGraph | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """从指定视角渲染一帧。返回 (rgb, depth, edge, visible_node_ids)。

    surfels: (N, 12) [x,y,z, sx,sy,sz, r,g,b, opacity, qx, qy]
    """
    if len(surfels) == 0:
        rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        depth = np.zeros((img_h, img_w), dtype=np.float32)
        edge = np.zeros((img_h, img_w), dtype=np.uint8)
        return rgb, depth, edge, []

    view_M = _look_at_matrix(pose.position, pose.look_at, pose.up)
    positions = surfels[:, :3].astype(np.float64)
    colors = (surfels[:, 6:9] * 255).clip(0, 255).astype(np.uint8)

    # 世界 → 相机
    ones = np.ones((positions.shape[0], 1))
    pos_h = np.concatenate([positions, ones], axis=1)  # (N,4)
    pos_cam = (view_M @ pos_h.T).T[:, :3]  # (N,3)

    # 相机内参
    fov_rad = np.deg2rad(pose.fov_deg)
    f = focal if focal > 0 else (img_h / (2 * np.tan(fov_rad / 2)))
    cx, cy = img_w / 2.0, img_h / 2.0

    valid = pos_cam[:, 2] < -1e-3  # z 负向为前方
    if not valid.any():
        rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        depth = np.zeros((img_h, img_w), dtype=np.float32)
        edge = np.zeros((img_h, img_w), dtype=np.uint8)
        return rgb, depth, edge, []

    pc = pos_cam[valid]
    cc = colors[valid]
    z = -pc[:, 2]  # 深度 = -z_cam（正值）
    x = pc[:, 0] * f / z + cx
    y = pc[:, 1] * f / z + cy

    rgb = np.zeros((img_h, img_w, 3), dtype=np.uint8)
    depth = np.zeros((img_h, img_w), dtype=np.float32)

    px = x.astype(np.int32)
    py = y.astype(np.int32)
    in_bounds = (px >= 0) & (px < img_w) & (py >= 0) & (py < img_h)
    px, py, z, cc = px[in_bounds], py[in_bounds], z[in_bounds], cc[in_bounds]

    # 按深度排序（远→近）
    order = np.argsort(-z)
    px, py, z, cc = px[order], py[order], z[order], cc[order]
    rgb[py, px] = cc
    depth[py, px] = z

    # 空洞填充
    if depth.max() > 0:
        depth_u16 = (depth * 1000).astype(np.uint16)
        mask = (depth == 0).astype(np.uint8) * 255
        depth_filled = cv2.inpaint(depth_u16, mask, 3, cv2.INPAINT_NS)
        depth = depth_filled.astype(np.float32) / 1000.0

    # 边缘
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edge = cv2.Canny(gray, 50, 150)

    # 可见性：检查场景图每个前景节点是否在视锥内 + 是否被遮挡
    visible_ids: list[int] = []
    if scene_graph is not None:
        for node in scene_graph.nodes:
            if node.node_type != "foreground":
                continue
            # 节点中心投影到相机
            node_pos = np.array(node.center_3d + (1.0,))
            node_cam = (view_M @ node_pos)[:3]
            if node_cam[2] >= -1e-3:
                continue  # 在相机后方
            node_z = -node_cam[2]
            nx = node_cam[0] * f / node_z + cx
            ny = node_cam[1] * f / node_z + cy
            if not (0 <= nx < img_w and 0 <= ny < img_h):
                continue  # 视锥外
            # 简单遮挡检查：该像素处的深度是否 ≤ 节点深度（容差）
            ix, iy = int(nx), int(ny)
            scene_depth = depth[iy, ix]
            if scene_depth <= 0 or scene_depth <= node_z + 0.5:
                visible_ids.append(node.object_id)

    return rgb, depth, edge, visible_ids


def render_viewpoint_keyframes(
    scene_ply_path: Path,
    trajectory: ViewpointTrajectory,
    scene_graph: SceneGraph,
    project_dir: Path,
    settings: Settings,
) -> Stage7Output:
    """渲染多视角关键帧流。"""
    stage7_dir = project_dir / "stage7"
    kf_dir = stage7_dir / "viewframes"
    kf_dir.mkdir(parents=True, exist_ok=True)

    h, w = settings.height, settings.width
    focal = getattr(settings, "focal_length", 1000.0)

    surfels = load_surfels_from_ply(scene_ply_path)

    keyframes: list[ViewframeSpec] = []
    total_visible = 0

    for i, pose in enumerate(trajectory.poses):
        rgb, depth, edge, visible_ids = render_viewframe(
            surfels, pose, h, w, focal, scene_graph)

        render_path = kf_dir / f"view_{i:04d}.png"
        depth_path = kf_dir / f"depth_{i:04d}.png"
        edge_path = kf_dir / f"edge_{i:04d}.png"
        vis_path = kf_dir / f"visibility_{i:04d}.npz"

        cv2.imwrite(str(render_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        d_min, d_max = float(depth.min()), float(depth.max())
        if d_max - d_min > 1e-6:
            depth_u16 = ((depth - d_min) / (d_max - d_min) * 65535).astype(np.uint16)
        else:
            depth_u16 = np.zeros((h, w), dtype=np.uint16)
        cv2.imwrite(str(depth_path), depth_u16)
        cv2.imwrite(str(edge_path), edge)

        # 可见性 mask：存为 npz，含 visible_ids 列表 + 每节点二值 mask
        vis_masks = {}
        for node in scene_graph.nodes:
            if node.node_type != "foreground":
                continue
            record_mask = None
            if node.mask_path is not None and Path(node.mask_path).exists():
                record_mask = cv2.imread(str(node.mask_path), cv2.IMREAD_GRAYSCALE)
            if record_mask is None:
                continue
            # 简单近似：原始 mask 标记该节点投影区域
            vis_masks[str(node.object_id)] = (record_mask > 127).astype(np.uint8)
        np.savez_compressed(str(vis_path), visible_ids=np.array(visible_ids, dtype=np.int32),
                            **vis_masks)

        keyframes.append(ViewframeSpec(
            frame_index=i,
            pose=pose,
            render_path=render_path,
            depth_path=depth_path,
            edge_path=edge_path,
            visibility_mask_path=vis_path,
            visible_node_ids=visible_ids,
        ))
        total_visible += len(visible_ids)

    avg_visible = total_visible / max(1, len(keyframes))

    # 持久化轨迹
    traj_path = stage7_dir / "trajectory.json"
    traj_dump = trajectory.model_dump()
    traj_path.write_text(json.dumps(traj_dump, indent=2, ensure_ascii=False, default=str),
                          encoding="utf-8")

    output = Stage7Output(
        trajectory=trajectory,
        keyframes=keyframes,
        avg_visible_nodes=avg_visible,
    )
    logger.info("模块 7 完成: %d 视角帧, 平均可见节点 %.2f → %s",
                len(keyframes), avg_visible, kf_dir)
    return output


def run_stage7(
    stage3: Stage3Output | None,
    stage6_output,  # Stage6Output
    project_dir: Path,
    settings: Settings,
    mode: str | None = None,
    focus_node_id: int | None = None,
    scene_ply_path: Path | None = None,
    stage2_output=None,  # Stage2Output, used when stage3 is skipped
) -> Stage7Output:
    """执行模块 7 完整流程。"""
    # 选择场景 PLY：优先用 stage3 编辑后的，否则回退到 stage2 原始
    if scene_ply_path is None:
        if stage3 is not None and stage3.edited_scene_ply_path.exists():
            scene_ply_path = stage3.edited_scene_ply_path
        elif stage2_output is not None and stage2_output.scene_ply_path.exists():
            scene_ply_path = stage2_output.scene_ply_path
        else:
            # 最后回退：构造一个最小的空场景 PLY（测试用）
            scene_ply_path = project_dir / "empty.ply"
            if not scene_ply_path.exists():
                scene_ply_path.write_text(
                    "ply\nformat ascii 1.0\n"
                    "element vertex 1\n"
                    "property float x\nproperty float y\nproperty float z\n"
                    "property float sx\nproperty float sy\nproperty float sz\n"
                    "property float r\nproperty float g\nproperty float b\n"
                    "property float opacity\nproperty float qx\nproperty float qy\n"
                    "end_header\n"
                    "0 0 3 0.1 0.1 0.1 0.5 0.5 0.5 1.0 0 0\n",
                    encoding="utf-8",
                )

    trajectory = generate_trajectory(
        stage6_output.scene_graph, settings,
        mode=mode, focus_node_id=focus_node_id,
    )
    return render_viewpoint_keyframes(
        scene_ply_path, trajectory, stage6_output.scene_graph,
        project_dir, settings,
    )
