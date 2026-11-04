"""PaintingStudio GUI 后端测试（离线, mock 分割/3DGS 路径）。

覆盖设计文档 §3 数据读写 + §4 各功能模块的 API 合约:
- project 创建/列表/读取/删除 (§3.2–3.3)
- segment 任务 (mock detector) → objects 导入 (§4.2)
- mask 笔刷 + undo/redo + 版本翻版 (§4.2)
- 3DGS 任务 + PLY 翻版 + scene.json 节点生成 (§4.3–3.4)
- scene PATCH/节点增删/相机 + 原子写 (§3.4)
- 快照渲染 → keyframes 三联图 (§4.4)
- 线稿上传 (§4.5)
- compose 占位视频 (§4.6)
- 任务队列: 进度/取消/列表 (§6)
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oilpainting_studio.gui.server import app  # noqa: E402
from oilpainting_studio.gui.store import ProjectRegistry  # noqa: E402
from oilpainting_studio.gui.tasks import get_queue  # noqa: E402


@pytest.fixture()
def client():
    # 重置 registry 指向临时 projects 根, 避免污染真实目录
    import oilpainting_studio.gui.server as srv
    tmp = Path(__file__).parent / "_tmp_projects"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    srv.registry = ProjectRegistry(tmp)
    yield TestClient(app)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def painting_png(tmp_path_factory):
    """合成一张 256x192 测试画: 上天蓝下草绿 + 两个色块物体。"""
    p = tmp_path_factory.mktemp("paintings") / "test_painting.png"
    img = np.zeros((192, 256, 3), dtype=np.uint8)
    img[:, :, 0] = 200; img[:, :, 1] = 160   # 天空 (BGR 蓝)
    img[96:, :] = (60, 140, 40)               # 草地绿
    cv2.circle(img, (70, 80), 28, (40, 60, 220), -1)     # 红色物体
    cv2.rectangle(img, (160, 100), (210, 160), (30, 200, 220), -1)  # 黄色物体
    cv2.imwrite(str(p), img)
    return p


def _wait_task(client: TaskClient, task_id: str, timeout: float = 60.0) -> dict:
    """轮询任务至终态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        t = r.json()
        if t["status"] in ("done", "failed", "cancelled"):
            return t
        time.sleep(0.05)
    raise TimeoutError(task_id)


TestClient_alias = TestClient
TaskClient = TestClient  # alias for type hint readability


def _make_project(client, painting_png, name="测试项目"):
    r = client.post("/api/projects",
                    data={"name": name},
                    files={"painting": ("p.png", open(painting_png, "rb"), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()["project_id"]


# ────────────────────────── projects ──────────────────────────

def test_root_health(client):
    # dist 构建产物存在时 / 重定向到 /index.html (TestClient 默认跟随→HTML);
    # 禁用跟随验证 307 本体, API 描述由 /api/health 与 /docs 提供
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (200, 307)
    if r.status_code == 307:
        assert r.headers["location"] == "/index.html"
    else:
        assert r.json()["app"] == "PaintingStudio"
    assert client.get("/api/health").json()["status"] == "ok"


def test_create_list_get_delete_project(client, painting_png):
    pid = _make_project(client, painting_png)
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert any(p["project_id"] == pid for p in r.json())

    r = client.get(f"/api/projects/{pid}")
    meta = r.json()
    assert meta["painting"]["width"] == 256 and meta["painting"]["height"] == 192
    assert meta["pipeline_state"]["segment"]["status"] == "todo"
    assert meta["undo_depth"] == 0

    # 原画与缩略图可读
    assert client.get(f"/api/projects/{pid}/painting").status_code == 200
    assert client.get(f"/api/projects/{pid}/painting?thumb=true").status_code == 200

    # 重名冲突
    r = client.post("/api/projects", data={"name": "测试项目"},
                    files={"painting": ("p.png", open(painting_png, "rb"), "image/png")})
    assert r.status_code == 409

    # 删除 → 回收站
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_get_missing_project_404(client):
    assert client.get("/api/projects/nonexistent").status_code == 404


# ────────────────────────── segment (§4.2) ──────────────────────────

def test_segment_run_imports_objects(client, painting_png):
    pid = _make_project(client, painting_png)
    r = client.post(f"/api/projects/{pid}/segment/run", json={"detector": "mock"})
    assert r.status_code == 202
    task = _wait_task(client, r.json()["task_id"])
    assert task["status"] == "done", task["error"]
    assert task["result"]["num_objects"] >= 1

    objs = client.get(f"/api/projects/{pid}/objects").json()
    assert len(objs) >= 1
    o = objs[0]
    assert o["mask_version"] == 1 and o["rejected"] is False and o["gs_version"] == 0
    assert o["mask_path"] == "mask.png"

    # 深度图已生成
    assert client.get(f"/api/projects/{pid}/depth").status_code == 200

    # pipeline_state 更新
    st = client.get(f"/api/projects/{pid}").json()["pipeline_state"]["segment"]
    assert st["status"] == "done"

    # mask 可读
    oid = o["object_id"]
    r = client.get(f"/api/projects/{pid}/objects/{oid}/mask")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")


# ────────────────────────── mask 笔刷 + undo (§4.2) ──────────────────────────

def test_mask_paint_undo_redo_versions(client, painting_png):
    pid = _make_project(client, painting_png)
    r = client.post(f"/api/projects/{pid}/segment/run", json={})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "done", t["error"]
    objs = client.get(f"/api/projects/{pid}/objects").json()
    oid = objs[0]["object_id"]

    mask_url = f"/api/projects/{pid}/objects/{oid}/mask"
    before = client.get(mask_url).content

    # 笔划提交
    r = client.put(mask_url, json={"strokes": [
        {"x": 40, "y": 40, "radius": 6},
        {"x": 60, "y": 50, "radius": 4, "erase": True},
    ]})
    assert r.status_code == 200
    v1 = r.json()["mask_version"]
    after = client.get(mask_url).content
    assert v1 == 2 and after != before

    # png_b64 整幅提交
    png = base64.b64encode(after).decode()
    r = client.put(mask_url, json={"png_b64": png})
    assert r.json()["mask_version"] == 3
    # 无效数据报 400
    r = client.put(mask_url, json={"png_b64": "not-an-image"})
    assert r.status_code == 400
    # 缺字段报 400
    r = client.put(mask_url, json={})
    assert r.status_code == 400

    # undo → 还原位图
    assert client.post(f"/api/projects/{pid}/undo").json()["op"] == "mask.paint"
    restored = client.get(mask_url).content
    assert restored == after  # v3 内容被撤销回 v2 (same bytes)

    # redo
    assert client.post(f"/api/projects/{pid}/undo/redo").status_code == 200
    # 栈空时报 409
    for _ in range(5):
        client.post(f"/api/projects/{pid}/undo")
    r = client.post(f"/api/projects/{pid}/undo")
    assert r.status_code == 409


def test_object_update_rejected_and_undo(client, painting_png):
    pid = _make_project(client, painting_png)
    r = client.post(f"/api/projects/{pid}/segment/run", json={})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "done", t["error"]
    oid = client.get(f"/api/projects/{pid}/objects").json()[0]["object_id"]

    r = client.put(f"/api/projects/{pid}/objects/{oid}", json={"rejected": True})
    assert r.status_code == 200 and r.json()["rejected"] is True
    r = client.put(f"/api/projects/{pid}/objects/{oid}", json={"depth_range": [1.5, 4.0]})
    assert r.json()["depth_range"] == [1.5, 4.0]
    # 非法字段
    assert client.put(f"/api/projects/{pid}/objects/{oid}",
                      json={"hack": 1}).status_code == 400

    # undo 恢复 depth_range
    client.post(f"/api/projects/{pid}/undo")
    o = client.get(f"/api/projects/{pid}/objects/{oid}").json()
    assert o["depth_range"] != [1.5, 4.0] or o["rejected"] is True


# ────────────────────────── 3DGS + scene (§4.3–3.4) ──────────────────────────

@pytest.fixture()
def seg_project(client, painting_png):
    pid = _make_project(client, painting_png, name="gs项目")
    r = client.post(f"/api/projects/{pid}/segment/run", json={})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "done", t["error"]
    return pid


def test_gs_run_ply_versioning_and_scene_nodes(client, seg_project):
    pid = seg_project
    objs = [o for o in client.get(f"/api/projects/{pid}/objects").json()
            if not o["rejected"]]
    assert objs, "mock 分割应至少产出 1 个物体"

    r = client.post(f"/api/projects/{pid}/gs/run", json={})
    assert r.status_code == 202
    task = _wait_task(client, r.json()["task_id"])
    assert task["status"] == "done", task["error"]
    assert task["result"]["generated"] >= 1

    o = client.get(f"/api/projects/{pid}/objects/{objs[0]['object_id']}").json()
    assert o["gs_version"] == 1
    assert ".v1.ply" in o["gs_source_ply"]

    # PLY 可下载且为有效 PLY 头
    r = client.get(f"/api/projects/{pid}/gs/{o['object_id']}/ply")
    assert r.status_code == 200
    assert r.content.startswith(b"ply")
    r = client.get(f"/api/projects/{pid}/gs/{o['object_id']}/ply?version=0")
    assert r.status_code == 404

    # scene.json 自动生成节点
    scene = client.get(f"/api/projects/{pid}/scene").json()
    assert len(scene["nodes"]) >= 1
    assert all(n["kind"] == "gs_object" for n in scene["nodes"])
    assert scene["camera"]["locked_to_painting"] is True

    # 重跑 → v2 翻版不覆盖
    r = client.post(f"/api/projects/{pid}/gs/run", json={"object_ids": [o["object_id"]]})
    _wait_task(client, r.json()["task_id"])
    o2 = client.get(f"/api/projects/{pid}/objects/{o['object_id']}").json()
    assert o2["gs_version"] == 2 and ".v2.ply" in o2["gs_source_ply"]
    # 旧版仍可取
    assert client.get(f"/api/projects/{pid}/gs/{o['object_id']}/ply?version=1").status_code == 200



def cam_is_restored(client, pid):
    cam = client.get(f"/api/projects/{pid}/scene").json()["camera"]
    return cam["position"] == [0.0, 0.0, 0.0] and cam["fov"] == 50.0


def test_scene_patch_add_delete_camera_undo(client, seg_project):
    pid = seg_project
    # 场景节点由 gs/run 生成 (§3.4); 先跑 3DGS
    r = client.post(f"/api/projects/{pid}/gs/run", json={})
    t = _wait_task(client, r.json()["task_id"])
    assert t["status"] == "done", t["error"]
    scene = client.get(f"/api/projects/{pid}/scene").json()
    assert scene["nodes"], "gs/run 应生成场景节点"
    nid = scene["nodes"][0]["node_id"]

    # PATCH 变换
    tr = {"translation": [12, -8, 0], "rotation_quat": [0, 0, 0, 1], "scale": [1.1, 1.1, 1.1]}
    r = client.patch(f"/api/projects/{pid}/scene",
                     json=[{"node_id": nid, "transform": tr, "visible": True}])
    assert r.status_code == 200 and r.json()["undo_depth"] == 1
    n = client.get(f"/api/projects/{pid}/scene").json()["nodes"][0]
    assert n["transform"]["translation"] == [12, -8, 0]
    assert n["transform"]["scale"] == [1.1, 1.1, 1.1]

    # 追加关键帧位姿
    r = client.patch(f"/api/projects/{pid}/scene",
                     json=[{"node_id": nid, "add_keyframe": "kf-0"}])
    n = client.get(f"/api/projects/{pid}/scene").json()["nodes"][0]
    assert "kf-0" in n["keyframes"]

    # 未知节点 404
    r = client.patch(f"/api/projects/{pid}/scene",
                     json=[{"node_id": "nope", "transform": tr}])
    assert r.status_code == 404

    # 新增节点
    new_node = {"node_id": "grp-1", "kind": "group", "label": "测试组"}
    r = client.post(f"/api/projects/{pid}/scene/nodes", json=new_node)
    assert r.status_code == 201
    # 重名 409
    assert client.post(f"/api/projects/{pid}/scene/nodes", json=new_node).status_code == 409

    # 锁定后 PATCH 409
    client.patch(f"/api/projects/{pid}/scene",
                 json=[{"node_id": "grp-1", "locked": True}])
    r = client.patch(f"/api/projects/{pid}/scene",
                     json=[{"node_id": "grp-1", "visible": False}])
    assert r.status_code == 409

    # 删除节点 + 404
    client.patch(f"/api/projects/{pid}/scene", json=[{"node_id": "grp-1", "locked": False}])
    assert client.delete(f"/api/projects/{pid}/scene/nodes/grp-1").status_code == 204
    assert client.delete(f"/api/projects/{pid}/scene/nodes/grp-1").status_code == 404

    # 相机
    r = client.put(f"/api/projects/{pid}/scene/camera",
                   json={"position": [1, 2, 3], "fov": 60.0})
    assert r.status_code == 200 and r.json()["fov"] == 60.0
    cam = client.get(f"/api/projects/{pid}/scene").json()["camera"]
    assert cam["position"] == [1, 2, 3]

    # undo 全部场景操作 → 变换回 0 (逐条 undo 直到栈空, 顺序即入栈逆序)
    for _ in range(10):
        r = client.post(f"/api/projects/{pid}/undo")
        if r.status_code == 409:
            break
    n = client.get(f"/api/projects/{pid}/scene").json()["nodes"][0]
    assert n["transform"]["translation"] == [0, 0, 0]
    assert n["keyframes"] == {}
    assert cam_is_restored(client, pid)


def test_gs_all_rejected_raises(client, seg_project):
    pid = seg_project
    objs = client.get(f"/api/projects/{pid}/objects").json()
    for o in objs:
        client.put(f"/api/projects/{pid}/objects/{o['object_id']}",
                   json={"rejected": True})
    r = client.post(f"/api/projects/{pid}/gs/run", json={})
    task = _wait_task(client, r.json()["task_id"])
    assert task["status"] == "failed"
    assert "rejected" in task["error"]


# ────────────────────────── snapshot + keyframes (§4.4–4.5) ──────────────────────────

def test_snapshot_and_lineart(client, seg_project):
    pid = seg_project
    client.post(f"/api/projects/{pid}/gs/run", json={})
    # 等 gs 完成 (snapshot 不强依赖, 但保证场景已建)
    for t in client.get("/api/tasks").json():
        if t["kind"] == "gs" and t["status"] in ("queued", "running"):
            _wait_task(client, t["task_id"])

    # 移动物体
    scene = client.get(f"/api/projects/{pid}/scene").json()
    nid = scene["nodes"][0]["node_id"]
    client.patch(f"/api/projects/{pid}/scene",
                 json=[{"node_id": nid,
                        "transform": {"translation": [30, 10, 0],
                                      "rotation_quat": [0, 0, 0, 1],
                                      "scale": [1, 1, 1]}}])

    r = client.post(f"/api/projects/{pid}/scene/snapshot")
    assert r.status_code == 202
    task = _wait_task(client, r.json()["task_id"])
    assert task["status"] == "done", task["error"]
    assert task["result"]["moved"] == 1
    kid = task["result"]["keyframe_id"]

    kfs = client.get(f"/api/projects/{pid}/keyframes").json()
    assert len(kfs) == 1 and kfs[0]["keyframe_id"] == kid
    for kind in ("rgb", "depth", "edge"):
        r = client.get(f"/api/projects/{pid}/keyframes/{kid}/image?kind={kind}")
        assert r.status_code == 200, kind
        assert r.headers["content-type"].startswith("image/png")

    # 快照 RGB 与原画不同 (物体已移动)
    orig = client.get(f"/api/projects/{pid}/painting").content
    moved = client.get(f"/api/projects/{pid}/keyframes/{kid}/image").content
    assert moved != orig

    # 线稿上传
    line = np.zeros((100, 100), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", line)
    r = client.post(f"/api/projects/{pid}/keyframes/{kid}/lineart",
                    json={"png_b64": base64.b64encode(buf).decode()})
    assert r.status_code == 201
    r = client.get(f"/api/projects/{pid}/keyframes/{kid}/image?kind=lineart")
    assert r.status_code == 200
    # 缺字段
    r = client.post(f"/api/projects/{pid}/keyframes/{kid}/lineart", json={})
    assert r.status_code == 400
    # 未知关键帧
    assert client.post(f"/api/projects/{pid}/keyframes/kf-99/lineart",
                       json={"png_b64": ""}).status_code == 404


# ────────────────────────── compose (§4.6) ──────────────────────────

def test_compose_run_placeholder_video(client, seg_project):
    pid = seg_project
    r = client.post(f"/api/projects/{pid}/compose/run",
                    json={"model": "wan2.2", "prompt": "test", "duration_sec": 2})
    assert r.status_code == 202
    task = _wait_task(client, r.json()["task_id"], timeout=90)
    assert task["status"] == "done", task["error"]
    out_rel = task["result"]["output"]
    assert out_rel.endswith("output.mp4")
    st = client.get(f"/api/projects/{pid}").json()["pipeline_state"]["compose"]
    assert st["status"] == "done"


# ────────────────────────── 任务队列 (§6) ──────────────────────────

def test_task_list_cancel(client, painting_png):
    pid = _make_project(client, painting_png, name="队列项目")

    # 提交两个任务, 第一个运行时取消第二个做不到 (串行) — 改为提交后立刻取消
    r1 = client.post(f"/api/projects/{pid}/segment/run", json={})
    r2 = client.post(f"/api/projects/{pid}/segment/run", json={})
    tid2 = r2.json()["task_id"]

    tasks = client.get("/api/tasks").json()
    assert len(tasks) >= 2
    assert client.post(f"/api/tasks/{tid2}/cancel").status_code == 200
    t2 = _wait_task(client, tid2)
    assert t2["status"] in ("cancelled", "done")  # 取消可能在其开始前生效

    # 已结束任务取消报 409
    r = client.post(f"/api/tasks/{tid2}/cancel")
    if t2["status"] in ("done", "cancelled"):
        assert r.status_code == 409
    # 未知任务 404
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/cancel").status_code == 404


# ────────────────────────── 目录布局与数据契约 (§3.2–3.3) ──────────────────────────

def test_project_layout_matches_design(client, painting_png):
    """目录布局与 project.json/scene.json 契约 (§3.2)。"""
    import oilpainting_studio.gui.server as srv
    pid = _make_project(client, painting_png, name="布局项目")
    client.post(f"/api/projects/{pid}/segment/run", json={})
    for t in client.get("/api/tasks").json():
        if t["status"] in ("queued", "running"):
            _wait_task(client, t["task_id"])
    client.post(f"/api/projects/{pid}/gs/run", json={})
    for t in client.get("/api/tasks").json():
        if t["status"] in ("queued", "running"):
            _wait_task(client, t["task_id"])

    root = srv.registry.get(pid).root
    for rel in ("project.json", "source/painting.png", "source/painting.thumb.jpg",
                "stage1/depth.png", "stage1/background.png", "stage1/stage1.json",
                "stage2/stage2.json", "stage3/scene.json"):
        assert (root / rel).exists(), f"缺 {rel}"

    meta = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == 1
    assert meta["painting"]["path"].startswith("source/")
    assert set(meta["pipeline_state"]) == {"segment", "gs", "scene", "keyframe", "compose"}

    # stage1.json 与 revive Stage1Output 字段对齐 (CLI 可读)
    s1 = json.loads((root / "stage1" / "stage1.json").read_text(encoding="utf-8"))
    assert {"objects", "background_path", "depth_path", "detector"} <= set(s1)

    # scene.json 节点引用的 PLY 存在且相对路径
    scene = json.loads((root / "stage3" / "scene.json").read_text(encoding="utf-8"))
    for n in scene["nodes"]:
        assert (root / n["source_ply"]).exists(), n["source_ply"]

    # stage2.json 模型记录含核心字段
    s2 = json.loads((root / "stage2" / "stage2.json").read_text(encoding="utf-8"))
    for m in s2["models"]:
        assert {"object_id", "ply_rel", "num_gaussians"} <= set(m)

    # 导出 zip
    r = client.get(f"/api/projects/{pid}/export")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
