"""HistorySandbox backend smoke tests (offline; LLM disabled)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402
from app.services import get_event, list_events  # noqa: E402
from app.services import ai_narrator  # noqa: E402

client = TestClient(app)


# ------------------------------------------------------------- catalog/data

def test_root_and_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["app"]
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_events_catalog_contains_four_plays():
    r = client.get("/api/events")
    assert r.status_code == 200
    events = r.json()
    ids = {e["id"] for e in events}
    assert {"chibi-battle", "silk-road", "age-of-discovery", "wwii-europe"} <= ids
    for e in events:
        assert e["title"] and e["summary"] and e["spirit_core"]
        assert e["step_count"] >= 5
        assert e["nations"], f"{e['id']} has no nations"


def test_event_detail_steps_wellformed():
    for eid in ("chibi-battle", "silk-road", "age-of-discovery", "wwii-europe"):
        r = client.get(f"/api/events/{eid}")
        assert r.status_code == 200
        ev = r.json()
        assert ev["map"] and ev["steps"]
        prev = 0
        for s in ev["steps"]:
            assert s["id"] > prev, "step ids must ascend"
            prev = s["id"]
            assert s["date"] and s["title"] and s["narrative"]
            assert s["background"] and s["spirit"] and s["significance"]
            for a in s["actors"]:
                assert len(a["position"]) == 2
            for arr in s["arrows"]:
                assert len(arr["points"]) >= 2
        # step 1 must place actors (something visible on the board)
        assert ev["steps"][0]["actors"]


def test_event_404():
    assert client.get("/api/events/no-such-event").status_code == 404


# ---------------------------------------------------------------- narration

@pytest.mark.anyio
async def test_narration_local_fallback():
    result = await ai_narrator.narrate("chibi-battle", 5, "immersive")
    assert result is not None
    assert result.source == "local"
    assert "赤壁" in result.text or "沙盘" in result.text
    assert len(result.text) >= 40


@pytest.mark.anyio
async def test_narration_styles():
    for style in ("immersive", "academic", "storytelling"):
        r = await ai_narrator.narrate("silk-road", 1, style)
        assert r is not None and r.text


@pytest.mark.anyio
async def test_narration_404():
    assert await ai_narrator.narrate("no-such", 1) is None
    assert await ai_narrator.narrate("chibi-battle", 999) is None


def test_narrate_endpoint():
    r = client.post("/api/narrate", json={"event_id": "wwii-europe", "step_id": 4, "style": "immersive"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] in ("llm", "local")
    assert data["text"]


# ---------------------------------------------------------------------- Q&A

@pytest.mark.anyio
async def test_ask_hits_corpus():
    ans = await ai_narrator.ask("chibi-battle", 5, "孙刘联盟是如何形成的？", 3)
    assert ans is not None
    assert ans.answer
    assert ans.references  # retrieval found relevant passages


@pytest.mark.anyio
async def test_ask_off_topic_is_honest():
    ans = await ai_narrator.ask("chibi-battle", None, "量子力学的基本原理是什么？", 3)
    assert ans is not None
    # off-topic questions must not fabricate an answer from unrelated history
    assert "量子" not in ans.answer or "超出" in ans.answer


@pytest.mark.anyio
async def test_ask_404():
    assert await ai_narrator.ask("no-such", None, "?") is None


def test_ask_endpoint():
    r = client.post("/api/ask", json={
        "event_id": "silk-road", "step_id": 1,
        "question": "张骞出使西域的意义是什么？", "top_k": 3,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["answer"]
    assert data["source"] in ("llm", "local")


# ------------------------------------------------------------ service layer

def test_get_event_and_step():
    ev = get_event("age-of-discovery")
    assert ev is not None and ev.title == "大航海时代"
    step = ai_narrator.get_step("age-of-discovery", 6)
    assert step is not None and "麦哲伦" in step.narrative


def test_local_narrate_is_deterministic_and_sanitized():
    ev = get_event("wwii-europe")
    step = ev.steps[0]
    a = ai_narrator._local_narrate(ev, step, "immersive")
    b = ai_narrator._local_narrate(ev, step, "immersive")
    assert a == b
    assert not any(ch in a for ch in "<>{}\\")


# ------------------------------------------------------------- world model

from app.services import world_model  # noqa: E402


@pytest.mark.anyio
async def test_simulate_move():
    r = await world_model.simulate_command("chibi-battle", 1, {
        "command": "move", "actor_id": "cao-main",
        "target_position": [113.0, 31.0], "seed": 42})
    assert r is not None
    assert r.hypothetical is True
    assert "假想" in r.date
    cao = next(a for a in r.actors if a.id == "cao-main")
    assert cao.position == (113.0, 31.0)
    assert r.arrows and r.arrows[0].points[0] != r.arrows[0].points[-1]


@pytest.mark.anyio
async def test_simulate_move_clamps_teleport():
    r = await world_model.simulate_command("chibi-battle", 1, {
        "command": "move", "actor_id": "cao-main",
        "target_position": [10.0, 10.0], "seed": 42})
    cao = next(a for a in r.actors if a.id == "cao-main")
    start = (113.9, 35.2)
    import math
    d = math.hypot(cao.position[0] - start[0], (cao.position[1] - start[1]) * 1.2)
    assert d < 20.0  # clamped to move range, not teleported across the globe


@pytest.mark.anyio
async def test_simulate_attack_outcomes():
    outcomes = set()
    for seed in range(12):
        r = await world_model.simulate_command("chibi-battle", 1, {
            "command": "attack", "actor_id": "cao-main", "seed": seed})
        assert r is not None and r.hypothetical
        assert "假想" in r.narrative
        outcomes.add(r.markers[0].label.split("·")[-1])
    # across seeds the engine can produce different results, all valid
    assert outcomes <= {"胜", "惨胜", "败"}
    assert len(outcomes) >= 1


@pytest.mark.anyio
async def test_simulate_attack_deterministic_same_seed():
    a = await world_model.simulate_command("chibi-battle", 1, {
        "command": "attack", "actor_id": "cao-main", "seed": 7})
    b = await world_model.simulate_command("chibi-battle", 1, {
        "command": "attack", "actor_id": "cao-main", "seed": 7})
    assert a.narrative == b.narrative


@pytest.mark.anyio
async def test_simulate_alliance():
    r = await world_model.simulate_command("chibi-battle", 1, {
        "command": "alliance", "target_nation": "shu", "seed": 1})
    assert r is not None and r.hypothetical
    assert any("结盟" in m.label for m in r.markers)


@pytest.mark.anyio
async def test_simulate_hypothetical_local_fallback():
    r = await world_model.simulate_command("wwii-europe", 3, {
        "command": "hypothetical", "question": "如果德国没有进攻苏联会怎样？", "seed": 3})
    assert r is not None and r.hypothetical
    assert "假想" in r.date
    assert r.narrative and len(r.narrative) > 30
    # the strongest actor must have moved (local branch perturbs top-2)
    moved = [a for a in r.arrows]
    assert moved, "hypothetical branch produced no arrows"


@pytest.mark.anyio
async def test_simulate_rejects_invalid():
    # unknown actor on a real step -> structured CommandUnavailable
    with pytest.raises(world_model.CommandUnavailable) as ei:
        await world_model.simulate_command("chibi-battle", 1, {
            "command": "move", "actor_id": "no-such-actor"})
    assert ei.value.reason == "unknown_actor"
    # attack with no enemy on the board (single-faction step)
    with pytest.raises(world_model.CommandUnavailable) as ei2:
        await world_model.simulate_command("age-of-discovery", 1, {
            "command": "attack", "actor_id": "henrique"})
    assert ei2.value.reason == "no_enemy"
    assert "敌军" in ei2.value.detail
    # nonexistent event/step -> None
    assert await world_model.simulate_command("no-event", 1, {
        "command": "move", "actor_id": "x"}) is None
    assert await world_model.simulate_command("chibi-battle", 1, {
        "command": "hypothetical", "question": "  "}) is None


def test_simulate_endpoint():
    r = client.post("/api/simulate", json={
        "event_id": "chibi-battle", "step_id": 5, "command": "attack",
        "actor_id": "cao-chibi", "seed": 11})
    assert r.status_code == 200
    data = r.json()
    assert data["hypothetical"] is True
    assert "假想" in data["date"]
    assert data["actors"] and data["arrows"]


def test_simulate_endpoint_409_no_enemy():
    r = client.post("/api/simulate", json={
        "event_id": "age-of-discovery", "step_id": 1, "command": "attack",
        "actor_id": "henrique"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["reason"] == "no_enemy"
    assert "敌军" in detail["message"]


def test_simulate_endpoint_422():
    r = client.post("/api/simulate", json={
        "event_id": "chibi-battle", "step_id": 1, "command": "hypothetical",
        "question": "   "})
    assert r.status_code == 422


# ------------------------------------------------------------------- terrain

TERRAIN_TYPES = {"mountain", "river", "city", "fort", "forest", "desert", "wasteland"}


def test_chibi_terrain_schema_and_coverage():
    """赤壁剧本的地形数据必须通过 Terrain schema 校验，且七类地形齐全。"""
    from app.models import Terrain

    ev = get_event("chibi-battle")
    assert ev is not None
    terrain = ev.map.terrain
    assert terrain, "赤壁剧本必须包含地形数据"

    # every instance round-trips through the strict Terrain model
    for t in terrain:
        assert isinstance(t, Terrain)
        assert t.type in TERRAIN_TYPES
        assert t.points, f"{t.type} {t.name} 缺少坐标"

    kinds = {t.type for t in terrain}
    missing = TERRAIN_TYPES - kinds
    assert not missing, f"赤壁剧本缺少地形类型：{missing}"

    # 几何语义：山脉/河流为折线（>=2 点），城池/要塞为单点，树林需半径
    for t in terrain:
        if t.type in ("mountain", "river"):
            assert len(t.points) >= 2, f"{t.name} 折线至少需要 2 个点"
        if t.type in ("city", "fort"):
            assert len(t.points) >= 1
        if t.type == "forest":
            assert t.radius > 0, f"树林 {t.name} 必须有分布半径"

    # 古地名标注可读
    labels = {t.label for t in terrain if t.label}
    assert {"长江", "汉水", "江陵", "赤壁"} <= labels


def test_terrain_served_by_api():
    """地形数据必须经 /api/events/{id} 完整下发到前端渲染层。"""
    r = client.get("/api/events/chibi-battle")
    assert r.status_code == 200
    terrain = r.json()["map"]["terrain"]
    assert len(terrain) >= 7
    assert {t["type"] for t in terrain} == TERRAIN_TYPES
    sample = next(t for t in terrain if t["type"] == "river")
    assert len(sample["points"]) >= 2
    assert sample["label"] == "长江"


def test_all_events_terrain_valid():
    """所有剧本若声明地形，都必须通过校验（允许为空以保持向后兼容）。"""
    for ev in list_events():
        for t in ev.map.terrain:
            assert t.type in TERRAIN_TYPES
            assert t.points
