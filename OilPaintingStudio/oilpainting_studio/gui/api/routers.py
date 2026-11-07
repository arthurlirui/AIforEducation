"""API routers（设计文档 §3.5 读写 API 总表）。

projects / objects / gs / scene / keyframes / compose / tasks / undo
全部挂在 /api 前缀下；共享 registry 与 task queue 由 server 注入。
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from pathlib import Path

import cv2

from .. import imgio
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..adapters import run_compose_task, run_gs_task, run_segmentation_task
from ..models import (
    ComposeRunRequest,
    GSRunRequest,
    KeyframeMeta,
    ObjectMeta,
    SceneGraph,
    SceneNode,
    ScenePatch,
    SegmentRunRequest,
    StageStatus,
    TaskInfo,
    Transform,
    UndoEntry,
)
from ..store import ProjectRegistry, ProjectStore, atomic_write_json
from ..tasks import TaskQueue

logger = logging.getLogger(__name__)


# ───────────────────────── 依赖注入 ─────────────────────────

def get_registry() -> ProjectRegistry:
    from ..server import registry
    return registry


def get_task_queue() -> TaskQueue:
    from ..server import task_queue
    return task_queue


def get_store(project_id: str, registry: ProjectRegistry = Depends(get_registry)) -> ProjectStore:
    try:
        return registry.get(project_id)
    except KeyError:
        raise HTTPException(404, f"project {project_id} 不存在")


# ───────────────────────── projects ─────────────────────────

projects_router = APIRouter(prefix="/api/projects", tags=["projects"])


@projects_router.get("")
def list_projects(registry: ProjectRegistry = Depends(get_registry)):
    out = []
    for meta in registry.list_projects():
        out.append({
            "project_id": meta.project_id, "name": meta.name,
            "created_at": meta.created_at.isoformat(),
            "painting": meta.painting.model_dump(),
            "pipeline_state": {k: v.model_dump(mode="json")
                               for k, v in meta.pipeline_state.items()},
        })
    return out


@projects_router.post("", status_code=201)
async def create_project(name: str = Form(...), painting: UploadFile = File(...),
                         registry: ProjectRegistry = Depends(get_registry)):
    """从上传原画新建项目（§3.2）。"""
    import tempfile
    suffix = Path(painting.filename or "painting.png").suffix or ".png"
    # Windows: cv2 读不了非 ASCII 路径; 上传暂存固定用 ASCII 文件名
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await painting.read())
        tmp_path = Path(tmp.name)
    try:
        store = registry.create(name, tmp_path)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"project_id": store.meta.project_id, "name": store.meta.name,
            "painting": store.meta.painting.model_dump()}


@projects_router.get("/{project_id}")
def get_project(project_id: str, store: ProjectStore = Depends(get_store)):
    meta = store.meta
    return {
        "project_id": meta.project_id, "name": meta.name,
        "created_at": meta.created_at.isoformat(),
        "painting": meta.painting.model_dump(),
        "pipeline_state": {k: v.model_dump(mode="json")
                           for k, v in meta.pipeline_state.items()},
        "undo_depth": store.undo_depth,
    }


@projects_router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, registry: ProjectRegistry = Depends(get_registry),
                   store: ProjectStore = Depends(get_store)):
    registry.delete(project_id, trash_dir=registry.projects_root.parent / ".trash")
    return None


@projects_router.get("/{project_id}/painting")
def get_painting(project_id: str, thumb: bool = False,
                 store: ProjectStore = Depends(get_store)):
    rel = store.meta.painting.thumb_path if thumb else store.meta.painting.path
    p = store.abspath(rel)
    if not p.exists():
        raise HTTPException(404, rel)
    return FileResponse(p)


@projects_router.get("/{project_id}/depth")
def get_depth(project_id: str, store: ProjectStore = Depends(get_store)):
    p = store.stage1_dir / "depth.png"
    if not p.exists():
        raise HTTPException(404, "depth.png 尚未生成, 请先运行分割")
    return FileResponse(p)


@projects_router.get("/{project_id}/export")
def export_project(project_id: str, store: ProjectStore = Depends(get_store)):
    out = store.export_zip(store.root / "exports")
    return FileResponse(out, filename=out.name)


# ───────────────────────── objects / segment ─────────────────────────

objects_router = APIRouter(prefix="/api/projects/{project_id}", tags=["objects"])


@objects_router.get("/objects")
def list_objects(store: ProjectStore = Depends(get_store)):
    return [o.model_dump() for o in store.list_objects()]


@objects_router.get("/objects/{oid}")
def get_object(oid: int, store: ProjectStore = Depends(get_store)):
    try:
        return store.get_object(oid).model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))


@objects_router.put("/objects/{oid}")
def update_object(oid: int, patch: dict,
                  store: ProjectStore = Depends(get_store)):
    """更新物体元数据（rejected / depth_range / color / label）。"""
    try:
        obj = store.get_object(oid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    allowed = {"rejected", "depth_range", "color", "label", "category", "confidence"}
    before = obj.model_dump()
    changed = {k: v for k, v in patch.items() if k in allowed}
    if not changed:
        raise HTTPException(400, f"无可更新字段, 允许: {sorted(allowed)}")
    if isinstance(changed.get("depth_range"), list):
        # model_copy 不做校验：列表不转元组会触发 pydantic 序列化警告
        changed["depth_range"] = tuple(changed["depth_range"])
    obj = obj.model_copy(update=changed)
    store.save_object(obj)
    store.push_undo(UndoEntry(op="object.update", target=f"stage1/objects/{oid:02d}/meta.json",
                              before=before, after=obj.model_dump()))
    return obj.model_dump()


@objects_router.get("/objects/{oid}/mask")
def get_mask(oid: int, store: ProjectStore = Depends(get_store)):
    obj = store.get_object(oid) if _has_object(store, oid) else None
    if obj is None:
        raise HTTPException(404, f"object {oid} 不存在")
    p = store.abspath(f"stage1/objects/{oid:02d}/{obj.mask_path}")
    if not p.exists():
        raise HTTPException(404, "mask.png 不存在")
    return FileResponse(p, media_type="image/png")


@objects_router.put("/objects/{oid}/mask")
async def paint_mask(oid: int, payload: dict,
                     store: ProjectStore = Depends(get_store)):
    """笔刷提交（§4.2）: 整幅 PNG base64 或笔划列表。

    payload = {"png_b64": ...} 或 {"strokes": [{"x","y","radius","erase"}]}
    每次 PUT = 1 undo 单元; mask 版本 +1; 对应 3DGS 标记为源已变更由前端
    通过 gs_source_ply 版本对比判断。
    """
    try:
        obj = store.get_object(oid)
    except KeyError as e:
        raise HTTPException(404, str(e))

    mask_path = store.abspath(f"stage1/objects/{oid:02d}/{obj.mask_path}")
    if not mask_path.exists():
        raise HTTPException(404, "mask.png 不存在, 请先运行分割")

    before = _mask_b64(mask_path)
    if "png_b64" in payload:
        try:
            data = base64.b64decode(payload["png_b64"], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "无效的 base64 数据")
        tmp = mask_path.with_suffix(".tmp.png")
        tmp.write_bytes(data)
        img = imgio.imread(str(tmp), cv2.IMREAD_GRAYSCALE)
        if img is None:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "无效的 PNG 数据")
        imgio.imwrite(str(mask_path), img)
        tmp.unlink(missing_ok=True)
    elif "strokes" in payload:
        img = imgio.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise HTTPException(500, "mask 读取失败")
        h, w = img.shape[:2]
        for s in payload["strokes"]:
            x, y, r = int(s["x"]), int(s["y"]), max(1, int(s.get("radius", 8)))
            val = 0 if s.get("erase") else 255
            cv2.circle(img, (x, y), r, val, -1)
        imgio.imwrite(str(mask_path), img)
    else:
        raise HTTPException(400, "需要 png_b64 或 strokes")

    obj.mask_version += 1
    store.save_object(obj)
    after = _mask_b64(mask_path)
    store.push_undo(UndoEntry(op="mask.paint", target=f"stage1/objects/{oid:02d}/mask.png",
                              before=before, after=after))
    return {"object_id": oid, "mask_version": obj.mask_version}


def _has_object(store: ProjectStore, oid: int) -> bool:
    return store.object_meta_path(oid).exists()


def _mask_b64(path: Path) -> str:
    data = np.fromfile(str(path), dtype=np.uint8)
    return base64.b64encode(data.tobytes()).decode()


# segment run
segment_router = APIRouter(prefix="/api/projects/{project_id}/segment", tags=["segment"])


@segment_router.post("/run", status_code=202)
def run_segment(req: SegmentRunRequest, store: ProjectStore = Depends(get_store),
                queue: TaskQueue = Depends(get_task_queue)):
    def fn(task: TaskInfo, s: ProjectStore):
        return run_segmentation_task(task, s)

    task = queue.submit("segment", store, fn,
                        label=f"分割 {store.meta.name}")
    return {"task_id": task.task_id, "status": task.status}


# ───────────────────────── gs ─────────────────────────

gs_router = APIRouter(prefix="/api/projects/{project_id}/gs", tags=["gs"])


@gs_router.post("/run", status_code=202)
def run_gs(req: GSRunRequest, store: ProjectStore = Depends(get_store),
           queue: TaskQueue = Depends(get_task_queue)):
    oids = req.object_ids or None
    ids_label = ",".join(str(o) for o in req.object_ids) or "全部"

    def fn(task: TaskInfo, s: ProjectStore):
        return run_gs_task(task, s, object_ids=oids)

    task = queue.submit("gs", store, fn, label=f"TripoSplat [{ids_label}]")
    return {"task_id": task.task_id, "status": task.status}


@gs_router.get("/{oid}/ply")
def get_ply(oid: int, version: int | None = None,
            store: ProjectStore = Depends(get_store)):
    obj = store.get_object(oid)
    if version is None:
        version = obj.gs_version
    p = store.stage2_dir / "gs" / f"{oid:02d}_{_safe(obj.label)}.v{version}.ply"
    if not p.exists():
        raise HTTPException(404, f"v{version} PLY 不存在 (gs_version={obj.gs_version})")
    return FileResponse(p, media_type="model/ply")


def _safe(label: str) -> str:
    from ..store import safe_name
    return safe_name(label)


# ───────────────────────── scene ─────────────────────────

scene_router = APIRouter(prefix="/api/projects/{project_id}/scene", tags=["scene"])


@scene_router.get("")
def get_scene(store: ProjectStore = Depends(get_store)):
    graph = store.load_scene()
    return json.loads(graph.model_dump_json())


@scene_router.patch("")
def patch_scene(patches: list[ScenePatch], store: ProjectStore = Depends(get_store)):
    """节点增量更新（§3.4 写入协议）。每个 patch = 1 undo 单元。"""
    graph = store.load_scene()
    nodes = {n.node_id: n for n in graph.nodes}
    results = []
    for patch in patches:
        node = nodes.get(patch.node_id)
        if node is None:
            raise HTTPException(404, f"节点 {patch.node_id} 不存在")
        if node.locked:
            raise HTTPException(409, f"节点 {patch.node_id} 已锁定")
        before = node.model_dump()
        if patch.transform is not None:
            node.transform = patch.transform
        if patch.visible is not None:
            node.visible = patch.visible
        if patch.locked is not None:
            node.locked = patch.locked
        if patch.parent is not None:
            node.parent = patch.parent
        if patch.label is not None:
            node.label = patch.label
        if patch.add_keyframe is not None:
            node.keyframes[patch.add_keyframe] = node.transform.model_copy()
        results.append(node.model_dump())
        store.push_undo(UndoEntry(op="scene.patch", target=f"scene.json#{patch.node_id}",
                                  before=before, after=node.model_dump()))
    store.save_scene(graph)
    store.meta.stage("scene").status = StageStatus.PARTIAL
    store.save_meta()
    return {"nodes": results, "undo_depth": store.undo_depth}


@scene_router.post("/nodes", status_code=201)
def add_node(node: SceneNode, store: ProjectStore = Depends(get_store)):
    graph = store.load_scene()
    if any(n.node_id == node.node_id for n in graph.nodes):
        raise HTTPException(409, f"节点 {node.node_id} 已存在")
    graph.nodes.append(node)
    store.save_scene(graph)
    store.push_undo(UndoEntry(op="scene.add_node", target=f"scene.json#{node.node_id}",
                              before=None, after=node.model_dump()))
    return node.model_dump()


@scene_router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str, store: ProjectStore = Depends(get_store)):
    graph = store.load_scene()
    remaining = [n for n in graph.nodes if n.node_id != node_id]
    if len(remaining) == len(graph.nodes):
        raise HTTPException(404, node_id)
    removed = [n for n in graph.nodes if n.node_id == node_id][0]
    graph.nodes = remaining
    store.save_scene(graph)
    store.push_undo(UndoEntry(op="scene.del_node", target=f"scene.json#{node_id}",
                              before=removed.model_dump(), after=None))
    return None


@scene_router.put("/camera")
def put_camera(camera: dict, store: ProjectStore = Depends(get_store)):
    graph = store.load_scene()
    before = graph.camera.model_dump()
    graph.camera.position = tuple(camera.get("position", graph.camera.position))
    graph.camera.look_at = tuple(camera.get("look_at", graph.camera.look_at))
    graph.camera.fov = float(camera.get("fov", graph.camera.fov))
    graph.camera.locked_to_painting = bool(
        camera.get("locked_to_painting", graph.camera.locked_to_painting))
    store.save_scene(graph)
    store.push_undo(UndoEntry(op="scene.camera", target="scene.json#camera",
                              before=before, after=graph.camera.model_dump()))
    return graph.camera.model_dump()


@scene_router.post("/snapshot", status_code=202)
def snapshot_scene(store: ProjectStore = Depends(get_store),
                   queue: TaskQueue = Depends(get_task_queue)):
    """快照渲染（§4.4）：当前场景图 → keyframes/ 三联图 (RGB/depth/edge)。"""
    def fn(task: TaskInfo, s: ProjectStore):
        return _snapshot_task(task, s)

    task = queue.submit("snapshot", store, fn, label="快照渲染")
    return {"task_id": task.task_id, "status": task.status}


def _snapshot_task(task: TaskInfo, store: ProjectStore) -> dict:
    """把 scene.json 各节点变换应用到原画物体区域, 合成 RGB+depth+edge 三联图。"""
    painting = store.abspath(store.meta.painting.path)
    img = imgio.imread(str(painting))
    if img is None:
        raise FileNotFoundError(painting)
    h, w = img.shape[:2]
    graph = store.load_scene()
    objs = {o.object_id: o for o in store.list_objects()}

    rgb = img.copy()
    depth_src = store.stage1_dir / "depth.png"
    depth = (imgio.imread(str(depth_src), cv2.IMREAD_UNCHANGED)
             if depth_src.exists() else np.full((h, w), 32768, np.uint16))
    if depth is None:
        depth = np.full((h, w), 32768, np.uint16)
    depth_out = depth.copy()

    moved = 0
    for node in graph.nodes:
        if not node.visible or node.kind != "gs_object":
            continue
        try:
            oid = int(node.node_id.split("-")[1])
        except (IndexError, ValueError):
            continue
        obj = objs.get(oid)
        if obj is None:
            continue
        mask_path = store.abspath(f"stage1/objects/{oid:02d}/{obj.mask_path}")
        mask = imgio.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        dx, dy = int(node.transform.translation[0]), int(node.transform.translation[1])
        if dx == 0 and dy == 0:
            continue
        moved += 1
        # 前景抠出 → 平移贴回; 原位涂背景均值色（§4.4 快照语义）
        fg = cv2.bitwise_and(rgb, rgb, mask=mask)
        fg_d = cv2.bitwise_and(depth_out, depth_out, mask=mask)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        fg_t = cv2.warpAffine(fg, M, (w, h))
        fg_d_t = cv2.warpAffine(fg_d, M, (w, h))
        bg_fill = np.uint8(cv2.mean(rgb, mask=255 - mask)[:3])
        rgb[mask > 0] = bg_fill
        depth_out[mask > 0] = 32768
        new_mask = cv2.warpAffine(mask, M, (w, h))
        rgb[new_mask > 0] = fg_t[new_mask > 0]
        depth_out[new_mask > 0] = fg_d_t[new_mask > 0]

    kf_dir = store.stage3_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    idx = len(store.list_keyframes())
    kid = f"kf-{idx}"
    rgb_p = kf_dir / f"{kid}_rgb.png"
    depth_p = kf_dir / f"{kid}_depth.png"
    edge_p = kf_dir / f"{kid}_edge.png"
    imgio.imwrite(str(rgb_p), rgb)
    imgio.imwrite(str(depth_p), depth_out)
    gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
    imgio.imwrite(str(edge_p), cv2.Canny(gray, 80, 160))

    frames = store.list_keyframes()
    frames.append(KeyframeMeta(
        keyframe_id=kid, label=f"关键帧 {idx}",
        rgb_path=f"stage3/keyframes/{rgb_p.name}",
        depth_path=f"stage3/keyframes/{depth_p.name}",
        edge_path=f"stage3/keyframes/{edge_p.name}",
        source="snapshot"))
    store.save_keyframes(frames)
    store.set_stage("keyframe", StageStatus.PARTIAL, artifact="stage3/keyframes")
    task.log.append(f"快照 {kid}: {moved} 个物体已移动")
    task.progress = 1.0
    return {"keyframe_id": kid, "moved": moved,
            "rgb": frames[-1].rgb_path, "depth": frames[-1].depth_path,
            "edge": frames[-1].edge_path}


# ───────────────────────── keyframes ─────────────────────────

keyframes_router = APIRouter(prefix="/api/projects/{project_id}/keyframes", tags=["keyframes"])


@keyframes_router.get("")
def list_keyframes(store: ProjectStore = Depends(get_store)):
    return [k.model_dump() for k in store.list_keyframes()]


@keyframes_router.get("/{keyframe_id}/image")
def keyframe_image(keyframe_id: str, kind: str = "rgb",
                   store: ProjectStore = Depends(get_store)):
    kf = next((k for k in store.list_keyframes() if k.keyframe_id == keyframe_id), None)
    if kf is None:
        raise HTTPException(404, keyframe_id)
    rel = {"rgb": kf.rgb_path, "depth": kf.depth_path, "edge": kf.edge_path,
           "lineart": kf.lineart_path}.get(kind)
    if not rel:
        raise HTTPException(404, f"{kind} 不存在")
    return FileResponse(store.abspath(rel))


@keyframes_router.post("/{keyframe_id}/lineart", status_code=201)
async def upload_lineart(keyframe_id: str, payload: dict,
                         store: ProjectStore = Depends(get_store)):
    """线稿上传（§4.5）: {png_b64} → stage3/lineart/<kid>.png。"""
    frames = store.list_keyframes()
    kf = next((k for k in frames if k.keyframe_id == keyframe_id), None)
    if kf is None:
        raise HTTPException(404, keyframe_id)
    if "png_b64" not in payload:
        raise HTTPException(400, "需要 png_b64")
    la_dir = store.stage3_dir / "lineart"
    la_dir.mkdir(parents=True, exist_ok=True)
    rel = f"stage3/lineart/{keyframe_id}.png"
    p = store.abspath(rel)
    p.write_bytes(base64.b64decode(payload["png_b64"]))
    kf.lineart_path = rel
    store.save_keyframes(frames)
    return {"keyframe_id": keyframe_id, "lineart_path": rel}


# ───────────────────────── compose ─────────────────────────

compose_router = APIRouter(prefix="/api/projects/{project_id}/compose", tags=["compose"])


@compose_router.post("/run", status_code=202)
def run_compose(req: ComposeRunRequest, store: ProjectStore = Depends(get_store),
                queue: TaskQueue = Depends(get_task_queue)):
    model, prompt, dur = req.model, req.prompt, req.duration_sec

    def fn(task: TaskInfo, s: ProjectStore):
        return run_compose_task(task, s, model, prompt, dur)

    task = queue.submit("compose", store, fn,
                        label=f"合成 {req.model} {req.duration_sec}s")
    return {"task_id": task.task_id, "status": task.status}


# ───────────────────────── tasks / undo ─────────────────────────

tasks_router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@tasks_router.get("")
def list_tasks(queue: TaskQueue = Depends(get_task_queue)):
    return [t.model_dump(mode="json") for t in queue.list()]


@tasks_router.get("/{task_id}")
def get_task(task_id: str, queue: TaskQueue = Depends(get_task_queue)):
    t = queue.get(task_id)
    if t is None:
        raise HTTPException(404, task_id)
    return t.model_dump(mode="json")


@tasks_router.post("/{task_id}/cancel")
def cancel_task(task_id: str, queue: TaskQueue = Depends(get_task_queue)):
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} 不存在")
    if not queue.cancel(task_id):
        raise HTTPException(409, "任务已结束, 无法取消")
    return {"task_id": task_id, "cancelled": True}


undo_router = APIRouter(prefix="/api/projects/{project_id}/undo", tags=["undo"])


@undo_router.post("")
def undo(store: ProjectStore = Depends(get_store)):
    """撤销（§3.3）: mask.paint 还原位图快照; 其余还原 JSON before 态。"""
    entry = store.undo()
    if entry is None:
        raise HTTPException(409, "undo 栈为空")
    _apply_undo(store, entry, redo=False)
    return {"op": entry.op, "target": entry.target, "undo_depth": store.undo_depth}


@undo_router.post("/redo")
def redo(store: ProjectStore = Depends(get_store)):
    entry = store.redo()
    if entry is None:
        raise HTTPException(409, "redo 栈为空")
    _apply_undo(store, entry, redo=True)
    return {"op": entry.op, "target": entry.target}


def _apply_undo(store: ProjectStore, entry: UndoEntry, *, redo: bool) -> None:
    """把 entry 的 before(redo 时取 after) 态写回目标文件。"""
    state = entry.after if redo else entry.before
    target = entry.target

    if entry.op == "mask.paint":
        import base64 as b64
        # target = "stage1/objects/<oid>/mask.png"
        mask_path = store.root / target
        if state is None:
            return
        data = b64.b64decode(state)
        arr = np.frombuffer(data, dtype=np.uint8)
        # 快照存的是文件字节; 直接还原
        mask_path.write_bytes(arr.tobytes())
        # mask 版本回退
        oid = int(target.split("/")[2])
        try:
            obj = store.get_object(oid)
            obj.mask_version = max(1, obj.mask_version - (0 if redo else 1))
            store.save_object(obj)
        except KeyError:
            pass
        return

    if target.startswith("scene.json#"):
        graph = store.load_scene()
        node_id = target.split("#", 1)[1]
        if node_id == "camera":
            if state is not None:
                graph.camera = graph.camera.model_validate(state)
            else:
                return
        else:
            nodes = [n for n in graph.nodes if n.node_id != node_id]
            if state is not None:
                nodes.append(SceneNode.model_validate(state))
            graph.nodes = nodes
        store.save_scene(graph)
        return

    if target.startswith("objects/") and target.endswith("meta.json"):
        if state is not None:
            atomic_write_json(store.root / target, state)
        return

    logger.warning("未知 undo 目标: %s", target)
