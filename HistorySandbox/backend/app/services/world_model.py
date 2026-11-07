"""World-model engine for interactive sandbox simulation.

Two layers:
- Rule dynamics (always available, offline): deterministic movement ranges,
  terrain defence bonuses, seeded combat resolution. Every simulated step is
  clearly tagged as hypothetical and never mixed up with recorded history.
- LLM layer (optional): for free-text counterfactuals ("what if there had been
  no south-east wind?") an OpenAI-compatible LLM proposes the next sandbox
  state as strict JSON; the rule engine validates/clamps it. Falls back to a
  local heuristic branch when the LLM is unavailable.
"""
from __future__ import annotations

import json
import math
import random
from typing import Any

import httpx

from ..config import settings
from ..models import Actor, Arrow, Highlight, Marker, SandboxStep
from . import get_event, get_step

# movement range per actor kind, in degrees of lon/lat per simulated step
MOVE_RANGE = {
    "army": 6.0,
    "fleet": 9.0,
    "person": 4.0,
    "trade": 5.0,
    "city": 0.0,
    "battle": 0.0,
}

# defence bonus when fighting inside one's own nation area
HOME_DEFENCE_BONUS = 0.25

HYP_MARKER = "· 假想"


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], (a[1] - b[1]) * 1.2)  # lat degrees stretched


def _clamp_position(base: tuple[float, float], dest: tuple[float, float], max_range: float) -> tuple[float, float]:
    """Allow free movement but clamp absurd teleporting to the move range."""
    if _dist(base, dest) <= max_range * 1.6:
        return dest
    k = (max_range * 1.6) / _dist(base, dest)
    return (base[0] + (dest[0] - base[0]) * k, base[1] + (dest[1] - base[1]) * k)


def _in_area(pos: tuple[float, float], event, nation_id: str) -> bool:
    for area in event.map.areas:
        if area.nation != nation_id:
            continue
        if _point_in_poly(pos, area.points):
            return True
    return False


def _point_in_poly(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _resolve_combat(attacker: Actor, defender: Actor, event, rng: random.Random) -> dict[str, Any]:
    """Seeded Lanchester-lite combat: strength ratio modified by defence & luck."""
    atk = float(attacker.strength)
    dfn = float(defender.strength)
    if _in_area(defender.position, event, defender.nation):
        dfn *= 1 + HOME_DEFENCE_BONUS
    luck = rng.uniform(0.85, 1.15)
    power = atk * luck
    if power > dfn * 1.1:
        winner, ratio = "attacker", power / max(dfn, 1.0)
    elif power > dfn * 0.8:
        winner, ratio = "pyrrhic", power / max(dfn, 1.0)
    else:
        winner, ratio = "defender", power / max(dfn, 1.0)
    return {"winner": winner, "ratio": ratio, "luck": luck}


def _nation_name(event, nation_id: str) -> str:
    for n in event.nations:
        if n.id == nation_id:
            return n.name
    return nation_id


def _nation_color(event, nation_id: str) -> str:
    for n in event.nations:
        if n.id == nation_id:
            return n.color
    return "#e67e22"


class CommandUnavailable(Exception):
    """Raised when a command type cannot apply to the current step.

    `reason` is a stable machine code; `detail` is a user-facing hint.
    """
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _check_command_applicable(event, base: SandboxStep, kind: str, cmd: dict[str, Any]) -> None:
    """Validate command semantics against the step before simulating."""
    actors = base.actors
    if kind in ("move", "attack", "retreat"):
        actor = next((a for a in actors if a.id == cmd.get("actor_id")), None)
        if actor is None:
            raise CommandUnavailable("unknown_actor", "沙盘上没有这枚棋子，或它不在当前幕中。")
    if kind == "attack":
        actor = next(a for a in actors if a.id == cmd.get("actor_id"))
        if not any(a.nation != actor.nation for a in actors):
            raise CommandUnavailable(
                "no_enemy",
                f"「{base.title}」这一幕的沙盘上只有{actor.name}所属阵营，没有可进攻的敌军棋子。"
                "航海、商路类剧本多为单阵营推演，试试机动、假想推演，或换一个战役型剧本（如赤壁之战、二战欧洲）。",
            )


async def simulate_command(event_id: str, step_id: int, cmd: dict[str, Any]) -> SandboxStep | None:
    event = get_event(event_id)
    base = get_step(event_id, step_id)
    if event is None or base is None:
        return None

    kind = cmd.get("command", "move")
    _check_command_applicable(event, base, kind, cmd)

    rng = random.Random(cmd.get("seed") or 42)
    actors = [a.model_copy(deep=True) for a in base.actors]
    arrows: list[Arrow] = []
    highlights: list[Highlight] = []
    markers: list[Marker] = []
    title = ""
    narrative = ""
    spirit = ""
    significance = ""
    date = base.date

    if kind in ("move", "retreat") and cmd.get("actor_id"):
        actor = next((a for a in actors if a.id == cmd["actor_id"]), None)
        if actor is None:
            return None
        dest = tuple(cmd["target_position"] or actor.position)
        rng_deg = MOVE_RANGE.get(actor.kind, 5.0) * (1.6 if kind == "retreat" else 1.0)
        dest = _clamp_position(actor.position, dest, rng_deg)
        arrows.append(Arrow(
            label=f"{actor.name}{'后撤' if kind == 'retreat' else '机动'}",
            points=[actor.position, dest],
            color=_nation_color(event, actor.nation),
            dashed=(kind == "retreat"),
        ))
        actor.position = dest
        if kind == "retreat":
            actor.strength = max(10, int(actor.strength * 0.9))
        verb = "向后方转移" if kind == "retreat" else "向新位置机动"
        title = f"{actor.name}自由机动"
        narrative = (
            f"在假想推演中，你指挥{actor.name}{verb}。"
            f"沙盘之上的战线因此改变——但请记住，真实的历史走的是另一条路。"
        )
        spirit = "历史的分岔口，正是每一个选择塑造的；沙盘给了你重走一遍的权力，也给了你对比与反思的机会。"
        significance = "此为教学性假想推演，用于理解地理与机动的军事价值，并非史实。"

    elif kind == "attack" and cmd.get("actor_id"):
        attacker = next((a for a in actors if a.id == cmd["actor_id"]), None)
        if attacker is None:
            return None
        # nearest enemy actor
        enemies = [a for a in actors if a.nation != attacker.nation]
        if not enemies:
            return None
        target = min(enemies, key=lambda e: _dist(attacker.position, e.position))
        dest = target.position
        arrows.append(Arrow(
            label=f"{attacker.name}进攻",
            points=[attacker.position, dest],
            color="#e74c3c", width=1.5,
        ))
        result = _resolve_combat(attacker, target, event, rng)
        highlights.append(Highlight(position=dest, radius=5.0, color="#e74c3c", label="假想战场"))
        if result["winner"] == "attacker":
            target.strength = max(5, int(target.strength * 0.3))
            attacker.strength = int(attacker.strength * 0.85)
            markers.append(Marker(id="hyp-battle", kind="battle", position=dest,
                                  label="假想会战·胜", color="#e67e22"))
            narrative = (f"假想推演：{attacker.name}向{_nation_name(event, target.nation)}发起进攻，"
                         f"经沙盘推演判定为攻势得手，但自身亦有折损。战争的胜负从不只有一面。")
        elif result["winner"] == "pyrrhic":
            target.strength = max(5, int(target.strength * 0.5))
            attacker.strength = max(5, int(attacker.strength * 0.5))
            markers.append(Marker(id="hyp-battle", kind="battle", position=dest,
                                  label="假想会战·惨胜", color="#f1c40f"))
            narrative = (f"假想推演：{attacker.name}苦战得胜，两败俱伤——"
                         f"皮洛士式胜利提醒我们：赢得战役未必赢得战争。")
        else:
            attacker.strength = max(5, int(attacker.strength * 0.4))
            markers.append(Marker(id="hyp-battle", kind="battle", position=dest,
                                  label="假想会战·败", color="#95a5a6"))
            narrative = (f"假想推演：{attacker.name}的攻势被守方依托地利挫败。"
                         f"沙盘用一场假想的失败告诉你：真实的胜利者为何高明。")
        title = "假想会战"
        spirit = "胜负乃兵家常事，而理解失败与理解胜利同样重要。"
        significance = "此为规则引擎的兵棋推演，兵力、地利与运气共同决定结果，并非史实。"

    elif kind == "alliance" and cmd.get("target_nation"):
        partner = cmd["target_nation"]
        positions = [a.position for a in actors if a.nation == partner]
        if positions:
            cx = sum(p[0] for p in positions) / len(positions)
            cy = sum(p[1] for p in positions) / len(positions)
            highlights.append(Highlight(position=(cx, cy), radius=6.0, color="#f1c40f",
                                        label=f"假想同盟·{_nation_name(event, partner)}"))
        markers.append(Marker(id="hyp-treaty", kind="treaty",
                              position=highlights[-1].position if highlights else base.camera or (0, 0),
                              label="假想结盟", color="#f1c40f"))
        title = "假想结盟"
        narrative = (f"假想推演：你在沙盘上促成了一场原本不存在的结盟——"
                     f"与{_nation_name(event, partner)}携手。棋局随之改变，"
                     f"但历史没有如果，它只把岔路留给我们思考。")
        spirit = "合纵连横是弱者的智慧，也是强者的枷锁；改变同盟，就改变了整个棋盘的力学。"
        significance = "此为教学性假想，用于体会外交在历史天平上的重量，并非史实。"

    elif kind == "hypothetical" and cmd.get("question"):
        return await simulate_hypothetical(event_id, step_id, cmd)

    else:
        return None

    return SandboxStep(
        id=900 + step_id,
        date=f"{date}{HYP_MARKER}",
        title=title,
        narrative=narrative,
        spirit=spirit,
        significance=significance,
        camera=base.camera,
        camera_zoom=base.camera_zoom,
        actors=actors,
        arrows=arrows,
        highlights=highlights,
        markers=markers,
        hypothetical=True,
    )


# -------------------------------------------------- LLM counterfactual layer

def _build_hyp_prompt(event, base: SandboxStep, question: str) -> str:
    actors_desc = "; ".join(
        f"{a.id}|{a.name}|{a.nation}|{a.position[0]:.1f},{a.position[1]:.1f}|兵力{a.strength}"
        for a in base.actors
    )
    return (
        "你是历史沙盘平台的世界模型引擎。基于当前沙盘状态，针对学生的反事实假想，"
        "推演下一步沙盘状态。只依据历史常识与给出的沙盘数据，输出严格 JSON（不要 markdown）：\n"
        '{"title": "...", "narrative": "120字内推演叙述", "spirit": "一句精神内核", '
        '"significance": "一句教学意义", "actor_moves": [{"id": "...", "lon": 0.0, "lat": 0.0, "strength_change_ratio": 0.8}], '
        '"new_markers": [{"position": [lon, lat], "label": "..."}]}\n'
        f"事件：{event.title}（{event.era}）。当前推演到：{base.date}「{base.title}」。\n"
        f"沙盘棋子：{actors_desc}\n"
        f"学生假想：{question}\n"
        "要求：actor_moves 只能引用给定 id，坐标偏移不超过5度；明确这是假想推演。"
    )


async def _llm_hypothetical(prompt: str) -> dict[str, Any] | None:
    if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
        return None
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(url, json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.6,
            }, headers={"Authorization": f"Bearer {settings.llm_api_key}"})
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None


def _local_hypothetical(event, base: SandboxStep, question: str) -> dict[str, Any]:
    """Offline fallback: perturb the strongest actors slightly and narrate."""
    actors = sorted(base.actors, key=lambda a: -a.strength)
    moves = []
    for a in actors[:2]:
        dx = 2.0 if a.position[0] < (base.camera or (0, 0))[0] else -2.0
        moves.append({"id": a.id, "lon": a.position[0] + dx, "lat": a.position[1] + 0.5,
                      "strength_change_ratio": 0.95})
    return {
        "title": "假想推演",
        "narrative": (f"针对你的假想「{question[:40]}」，沙盘在本地推演引擎下给出一种可能的走向："
                      "关键力量沿最可能的方向重新部署，局势进入未知的分支。"
                      "配置 LLM 后可获得更细腻的推演。切记：这不是真实的历史。"),
        "spirit": "历史无法重来，但推演让我们学会敬畏每一个选择的分量。",
        "significance": "此为教学性假想推演，用于培养历史思维中的因果想象力。",
        "actor_moves": moves,
        "new_markers": [],
    }


async def simulate_hypothetical(event_id: str, step_id: int, cmd: dict[str, Any]) -> SandboxStep | None:
    event = get_event(event_id)
    base = get_step(event_id, step_id)
    if event is None or base is None:
        return None
    question = cmd.get("question", "").strip()
    if not question:
        return None

    prompt = _build_hyp_prompt(event, base, question)
    data = await _llm_hypothetical(prompt) or _local_hypothetical(event, base, question)

    actors = [a.model_copy(deep=True) for a in base.actors]
    arrows: list[Arrow] = []
    markers: list[Marker] = []
    for mv in data.get("actor_moves", [])[:6]:
        actor = next((a for a in actors if a.id == mv.get("id")), None)
        if actor is None:
            continue
        try:
            dest = (float(mv["lon"]), float(mv["lat"]))
        except (KeyError, TypeError, ValueError):
            continue
        dest = _clamp_position(actor.position, dest, MOVE_RANGE.get(actor.kind, 5.0) * 1.6)
        arrows.append(Arrow(label=f"{actor.name}·假想机动", points=[actor.position, dest],
                            color=_nation_color(event, actor.nation), dashed=True))
        actor.position = dest
        ratio = mv.get("strength_change_ratio")
        if isinstance(ratio, (int, float)) and 0.1 <= ratio <= 2.0:
            actor.strength = max(5, min(300, int(actor.strength * ratio)))
    for m in data.get("new_markers", [])[:4]:
        try:
            pos = (float(m["position"][0]), float(m["position"][1]))
            markers.append(Marker(id=f"hyp-{len(markers)}", kind="battle", position=pos,
                                  label=str(m.get("label", "假想"))[:20], color="#f1c40f"))
        except (KeyError, TypeError, IndexError, ValueError):
            continue

    return SandboxStep(
        id=900 + step_id,
        date=f"{base.date}{HYP_MARKER}",
        title=str(data.get("title", "假想推演"))[:30],
        narrative=str(data.get("narrative", ""))[:400],
        spirit=str(data.get("spirit", ""))[:200],
        significance=str(data.get("significance", ""))[:200],
        camera=base.camera,
        camera_zoom=base.camera_zoom,
        actors=actors,
        arrows=arrows,
        highlights=[],
        markers=markers,
        hypothetical=True,
    )
