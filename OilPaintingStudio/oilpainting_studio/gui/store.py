"""项目存储层：project.json / scene.json / 物体元数据的读写（§3.2–§3.4）。

- 所有 JSON 落盘走 tmp+rename 原子写
- 目录布局固定（source/ stage1/ stage2/ stage3/ stage5/ exports/）
- 每个项目一个 ProjectStore 实例，由全局 ProjectRegistry 管理
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
from pathlib import Path

from pydantic import BaseModel

from . import imgio

from ..revive.schemas import SegmentedObject
from .models import (
    KeyframeMeta,
    ObjectMeta,
    ProjectMeta,
    SceneGraph,
    SceneNode,
    StageState,
    StageStatus,
    Transform,
    UndoEntry,
    _now,
)

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+")


def safe_name(name: str) -> str:
    """项目目录名：只保留安全字符。"""
    cleaned = _UNSAFE.sub("-", name).strip("-") or "project"
    return cleaned[:64]


def atomic_write_json(path: Path, payload: dict | list) -> None:
    """tmp + rename 原子写 JSON（§6 非功能设计）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def md5_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class ProjectStore:
    """单个项目的目录读写。所有路径均为相对项目根的 POSIX 路径。"""

    MAX_UNDO = 50

    def __init__(self, root: Path, meta: ProjectMeta):
        self.root = root
        self.meta = meta
        self._lock = threading.RLock()
        self._obj_locks: dict[int, threading.Lock] = {}  # mask 笔刷 per-object 写锁
        self._obj_locks_guard = threading.Lock()
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []
        self._load_undo_manifest()  # 启动回载持久化栈 (G8, 无 manifest 时为 no-op)

    def object_lock(self, object_id: int) -> threading.Lock:
        """per-object 写锁（mask 笔刷并发提交串行化, 版本号与内容保持一致）。"""
        with self._obj_locks_guard:
            if object_id not in self._obj_locks:
                self._obj_locks[object_id] = threading.Lock()
            return self._obj_locks[object_id]

    # ── 基础目录 ──

    def abspath(self, rel: str) -> Path:
        return self.root / rel

    @property
    def stage1_dir(self) -> Path:
        return self.root / "stage1"

    @property
    def objects_dir(self) -> Path:
        return self.stage1_dir / "objects"

    @property
    def stage2_dir(self) -> Path:
        return self.root / "stage2"

    @property
    def stage3_dir(self) -> Path:
        return self.root / "stage3"

    # ── project.json ──

    @classmethod
    def create(cls, projects_root: Path, name: str, painting_src: Path,
               thumb_max: int = 512) -> "ProjectStore":
        """从原画新建项目（§3.2）：拷贝原画、生成缩略图、写 project.json。"""
        import cv2

        slug = safe_name(name)
        root = projects_root / slug
        if root.exists():
            raise FileExistsError(f"项目已存在: {slug}")
        (root / "source").mkdir(parents=True)
        (root / "stage1" / "objects").mkdir(parents=True)
        (root / "stage2" / "gs").mkdir(parents=True)
        (root / "stage3" / "lineart").mkdir(parents=True)
        (root / "stage3" / "keyframes").mkdir(parents=True)
        (root / "stage5" / "runs").mkdir(parents=True)
        (root / "exports").mkdir(parents=True)

        # 源文件统一重命名为 painting + 原后缀 (避免非 ASCII 文件名传播到 cv2)
        src_suffix = painting_src.suffix or ".png"
        painting = root / "source" / ("painting" + src_suffix)
        shutil.copy2(painting_src, painting)

        img = imgio.imread(str(painting))
        if img is None:
            raise ValueError(f"无法读取图像: {painting_src}")
        h, w = img.shape[:2]

        thumb_rel = "source/painting.thumb.jpg"
        scale = thumb_max / max(h, w)
        if scale < 1.0:
            thumb = cv2.resize(img, (int(w * scale), int(h * scale)))
        else:
            thumb = img
        imgio.imwrite(str(root / thumb_rel), thumb)

        from .models import PaintingSource
        meta = ProjectMeta(
            name=name,
            painting=PaintingSource(
                path=f"source/{painting.name}", width=w, height=h,
                md5=md5_of(painting), thumb_path=thumb_rel),
        )
        store = cls(root, meta)
        store.save_meta()
        return store

    @classmethod
    def open(cls, root: Path) -> "ProjectStore":
        meta = ProjectMeta.model_validate(read_json(root / "project.json"))
        return cls(root, meta)

    def save_meta(self) -> None:
        with self._lock:
            atomic_write_json(self.root / "project.json",
                              json.loads(self.meta.model_dump_json()))

    def set_stage(self, key: str, status: StageStatus,
                  artifact: str | None = None, detail: str = "") -> None:
        with self._lock:
            st = self.meta.stage(key)
            st.status = status
            st.updated = _now()
            st.artifact = artifact or st.artifact
            st.detail = detail
            self.save_meta()

    # ── 物体元数据（stage1/objects/<oid>/meta.json）──

    def object_dir(self, object_id: int) -> Path:
        return self.objects_dir / f"{object_id:02d}"

    def object_meta_path(self, object_id: int) -> Path:
        return self.object_dir(object_id) / "meta.json"

    def list_objects(self) -> list[ObjectMeta]:
        out: list[ObjectMeta] = []
        if not self.objects_dir.exists():
            return out
        for d in sorted(self.objects_dir.iterdir()):
            mp = d / "meta.json"
            if mp.exists():
                out.append(ObjectMeta.model_validate(read_json(mp)))
        return out

    def get_object(self, object_id: int) -> ObjectMeta:
        p = self.object_meta_path(object_id)
        if not p.exists():
            raise KeyError(f"object {object_id} 不存在")
        return ObjectMeta.model_validate(read_json(p))

    def save_object(self, obj: ObjectMeta) -> None:
        with self._lock:
            atomic_write_json(self.object_meta_path(obj.object_id),
                              json.loads(obj.model_dump_json()))

    def import_stage1(self, objects: list[SegmentedObject], detector: str) -> None:
        """把 revive stage1 输出导入项目目录布局（§3.2 版本化 objects/）。

        已存在的物体（按 label 判定）保留其 mask 编辑历史；全新布局时
        每个物体一个目录，mask/crop 复制入内。
        """
        import cv2
        with self._lock:
            for obj in objects:
                d = self.object_dir(obj.object_id)
                d.mkdir(parents=True, exist_ok=True)
                mask_rel = "mask.png"
                if not (d / mask_rel).exists():
                    imgio.imwrite(str(d / mask_rel),
                                imgio.imread(str(obj.mask_path), cv2.IMREAD_GRAYSCALE))
                    crop_rel = "crop.png"
                    imgio.imwrite(str(d / crop_rel), imgio.imread(str(obj.crop_path)))
                else:
                    crop_rel = "crop.png"
                    if not (d / crop_rel).exists():
                        imgio.imwrite(str(d / crop_rel), imgio.imread(str(obj.crop_path)))

                existing = None
                mp = d / "meta.json"
                if mp.exists():
                    existing = ObjectMeta.model_validate(read_json(mp))

                meta = ObjectMeta(
                    object_id=obj.object_id,
                    category=obj.category.value,
                    label=obj.label,
                    confidence=obj.confidence,
                    bbox=list(obj.bbox),
                    depth_range=list(obj.depth_range),
                    color=existing.color if existing else _PALETTE[obj.object_id % len(_PALETTE)],
                    rejected=existing.rejected if existing else False,
                    mask_version=existing.mask_version if existing else 1,
                    mask_path=mask_rel,
                    crop_path=crop_rel,
                    gs_version=existing.gs_version if existing else 0,
                    gs_source_ply=existing.gs_source_ply if existing else None,
                )
                atomic_write_json(mp, json.loads(meta.model_dump_json()))

            self.set_stage("segment", StageStatus.DONE,
                           artifact="stage1/stage1.json", detail=f"detector={detector}")

            # 清理 revive 落在 stage1 根下的中间产物（已导入 objects/ 布局, 原文件属垃圾）
            for stale in self.stage1_dir.glob("mask_obj*.png"):
                stale.unlink(missing_ok=True)
            for stale in self.stage1_dir.glob("crop_obj*.png"):
                stale.unlink(missing_ok=True)

    # ── scene.json ──

    def scene_path(self) -> Path:
        return self.stage3_dir / "scene.json"

    def load_scene(self) -> SceneGraph:
        p = self.scene_path()
        if not p.exists():
            return SceneGraph()
        return SceneGraph.model_validate(read_json(p))

    def save_scene(self, graph: SceneGraph) -> None:
        with self._lock:
            atomic_write_json(self.scene_path(), json.loads(graph.model_dump_json()))

    def build_scene_from_stage2(self, registry_payload: dict) -> SceneGraph:
        """stage2 完成后：为每个非 rejected 且有 PLY 的物体建节点。"""
        graph = self.load_scene()
        existing = {n.node_id: n for n in graph.nodes}
        objs = {o.object_id: o for o in self.list_objects() if not o.rejected}
        for rec in registry_payload.get("models", []):
            oid = rec["object_id"]
            node_id = f"obj-{oid:02d}-{safe_name(rec['label'])}"
            if node_id in existing:
                existing[node_id].source_ply = rec["ply_rel"]
                continue
            graph.nodes.append(SceneNode(
                node_id=node_id, kind="gs_object",
                label=f"{rec['label']} #{oid}",
                source_ply=rec["ply_rel"]))
        return graph

    # ── undo / redo（§3.3, 持久化到 .undo/undo.json）──

    UNDO_SNAPSHOT_PREFIX = "file:.undo/"

    def _undo_dir(self) -> Path:
        return self.root / ".undo"

    def _undo_manifest_path(self) -> Path:
        return self._undo_dir() / "undo.json"

    def _entry_snapshots(self, entry: UndoEntry) -> list[str]:
        """entry 的 before/after 引用的 .undo/ 快照文件名（非文件标记忽略）。"""
        out = []
        for v in (entry.before, entry.after):
            if isinstance(v, str) and v.startswith(self.UNDO_SNAPSHOT_PREFIX):
                out.append(v[len(self.UNDO_SNAPSHOT_PREFIX):])
        return out

    def _load_undo_manifest(self) -> None:
        """启动回载 .undo/undo.json 重建 undo/redo 栈。

        快照文件缺失或条目损坏的条目跳过（warning）, 不阻断项目打开;
        manifest 整体损坏时从空栈开始。
        """
        p = self._undo_manifest_path()
        if not p.exists():
            return
        try:
            payload = read_json(p)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("undo manifest 损坏, 忽略: %s", e)
            return
        if not isinstance(payload, dict):
            logger.warning("undo manifest 格式异常, 忽略")
            return
        self._undo = self._load_undo_stack(payload.get("undo"), "undo")
        self._redo = self._load_undo_stack(payload.get("redo"), "redo")

    def _load_undo_stack(self, items: object, name: str) -> list[UndoEntry]:
        if not isinstance(items, list):
            return []
        out: list[UndoEntry] = []
        for raw in items:
            try:
                e = UndoEntry.model_validate(raw)
            except Exception as ex:
                logger.warning("跳过损坏的 %s 条目: %s", name, ex)
                continue
            if any(not (self._undo_dir() / rel).is_file()
                   for rel in self._entry_snapshots(e)):
                logger.warning("跳过 %s 条目(快照文件缺失): %s %s", name, e.op, e.target)
                continue
            out.append(e)
        return out

    def _save_undo_manifest(self) -> None:
        """原子写栈 manifest（调用方需持 self._lock）。

        持久化为尽力而为: 写失败仅 warning, 不影响内存栈语义。
        """
        payload = {
            "undo": [json.loads(e.model_dump_json()) for e in self._undo],
            "redo": [json.loads(e.model_dump_json()) for e in self._redo],
        }
        try:
            atomic_write_json(self._undo_manifest_path(), payload)
        except OSError as e:
            logger.warning("undo manifest 写入失败(仅影响持久化): %s", e)

    def _gc_snapshots(self, dropped: list[UndoEntry]) -> None:
        """删除被淘汰/清空条目引用且不再被任何保留条目引用的快照文件。

        调用方需持 self._lock; 只删 dropped 条目引用的文件, 不做全目录
        扫描（并发笔刷可能在 push 前刚落盘快照, 全目录 GC 会误删）。
        """
        candidates = set()
        for e in dropped:
            candidates.update(self._entry_snapshots(e))
        if not candidates:
            return
        referenced = set()
        for e in (*self._undo, *self._redo):
            referenced.update(self._entry_snapshots(e))
        for name in candidates - referenced:
            (self._undo_dir() / name).unlink(missing_ok=True)

    def push_undo(self, entry: UndoEntry) -> None:
        with self._lock:
            self._undo.append(entry)
            dropped = self._redo
            self._redo = []
            if len(self._undo) > self.MAX_UNDO:
                dropped.append(self._undo.pop(0))
            self._save_undo_manifest()
            self._gc_snapshots(dropped)

    def undo(self) -> UndoEntry | None:
        with self._lock:
            if not self._undo:
                return None
            e = self._undo.pop()
            self._redo.append(e)
            self._save_undo_manifest()
            return e

    def redo(self) -> UndoEntry | None:
        with self._lock:
            if not self._redo:
                return None
            e = self._redo.pop()
            self._undo.append(e)
            self._save_undo_manifest()
            return e

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    # ── 关键帧 ──

    def keyframes_index(self) -> Path:
        return self.stage3_dir / "keyframes" / "index.json"

    def list_keyframes(self) -> list[KeyframeMeta]:
        p = self.keyframes_index()
        if not p.exists():
            return []
        return [KeyframeMeta.model_validate(x) for x in read_json(p)]

    def save_keyframes(self, frames: list[KeyframeMeta]) -> None:
        with self._lock:
            atomic_write_json(self.keyframes_index(),
                              [json.loads(k.model_dump_json()) for k in frames])

    # ── 导出 ──

    def export_zip(self, dest: Path) -> Path:
        """打包项目目录为 zip, 供整目录迁移/交付。

        排除 .undo/（undo 内部状态: manifest + 位图快照, 接收端回载时
        会自动重建）与 exports/ 自身（避免 zip 套 zip 递归膨胀）。
        """
        import zipfile
        base = self.root.name
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"{base}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(self.root.rglob("*")):
                rel = p.relative_to(self.root)
                if rel.parts and rel.parts[0] in (".undo", "exports"):
                    continue
                if p.is_file():
                    zf.write(p, rel.as_posix())
        return out


_PALETTE = ["#5b8cff", "#3fbf7f", "#e6b54c", "#9d7bff",
            "#e0655a", "#45c8d8", "#e08ec0", "#8b95a8"]


class ProjectRegistry:
    """projects_root 下全部项目的注册表。线程安全。"""

    def __init__(self, projects_root: Path):
        self.projects_root = projects_root
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self._stores: dict[str, ProjectStore] = {}
        self._lock = threading.Lock()

    def list_projects(self) -> list[ProjectMeta]:
        metas = []
        for d in sorted(self.projects_root.iterdir()):
            if (d / "project.json").is_file():
                try:
                    metas.append(ProjectStore.open(d).meta)
                except Exception as e:  # 损坏的项目仍要列出但标注失败
                    logger.warning("跳过损坏项目 %s: %s", d, e)
        return metas

    def _slug_of(self, project_id: str) -> str | None:
        for d in self.projects_root.iterdir():
            if (d / "project.json").is_file():
                try:
                    meta = ProjectMeta.model_validate(read_json(d / "project.json"))
                    if meta.project_id == project_id:
                        return d.name
                except Exception:
                    continue
        return None

    def get(self, project_id: str) -> ProjectStore:
        with self._lock:
            # setdefault 语义: 并发 miss 时只 open 一次, 后写不再覆盖先写实例
            # (覆盖会丢掉旧实例上的内存态; undo 栈虽已持久化, 但实例复用
            # 仍免去重复回载与 manifest 竞写)
            store = self._stores.get(project_id)
            if store is not None:
                return store
            slug = self._slug_of(project_id)
            if slug is None:
                raise KeyError(f"project {project_id} 不存在")
            store = ProjectStore.open(self.projects_root / slug)
            self._stores.setdefault(project_id, store)
            return self._stores[project_id]

    def create(self, name: str, painting_src: Path) -> ProjectStore:
        store = ProjectStore.create(self.projects_root, name, painting_src)
        with self._lock:
            self._stores[store.meta.project_id] = store
        return store

    def delete(self, project_id: str, trash_dir: Path | None = None) -> None:
        slug = self._slug_of(project_id)
        if slug is None:
            raise KeyError(f"project {project_id} 不存在")
        target = self.projects_root / slug
        if trash_dir is not None:
            trash_dir.mkdir(parents=True, exist_ok=True)
            dest = trash_dir / slug
            if dest.exists():  # 回收站同名: 加时间戳后缀
                from datetime import datetime
                dest = trash_dir / f"{slug}.{datetime.now():%H%M%S%f}"
            shutil.move(str(target), str(dest))
        else:
            shutil.rmtree(target)
        with self._lock:
            self._stores.pop(project_id, None)
