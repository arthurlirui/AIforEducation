"""AI narrator & Q&A service.

Two engines:
- LLM engine (optional): any OpenAI-compatible chat completions endpoint,
  enabled via HISTORY_LLM_* env vars. Falls back to local on any failure.
- Local template engine: zero-dependency, offline; synthesises immersive
  narration and retrieval-augmented answers from the scenario data itself.
"""
from __future__ import annotations

import re

import httpx

from ..config import settings
from ..models import AskAnswer, HistoricalEvent, SandboxStep
from . import get_event, get_step
from .sanitize import sanitize as _sanitize

STYLE_LEADS = {
    "immersive": "以沉浸式沙盘讲解员的口吻，用生动、有画面感的语言",
    "academic": "以严谨的历史教学口吻，条理清晰地",
    "storytelling": "以说书人般的叙事口吻，娓娓道来地",
}


def build_prompt(event: HistoricalEvent, step: SandboxStep, style: str = "immersive") -> str:
    lead = STYLE_LEADS.get(style, STYLE_LEADS["immersive"])
    ctx = f"事件：{event.title}（{event.era}，{event.year_start}—{event.year_end}）。"
    if step.background:
        ctx += f"背景：{step.background} "
    ctx += f"当前推演到：{step.date}「{step.title}」。已知解说要点：{step.narrative}"
    if step.spirit:
        ctx += f" 精神内核：{step.spirit}"
    if step.significance:
        ctx += f" 历史意义：{step.significance}"
    return (
        f"{lead}，为三维历史沙盘推演撰写一段约120字的中文讲解词。"
        f"{ctx} 要求：紧扣地图上正在发生的疆域与行军变化，结尾升华到对今天的启示。"
        "不要使用markdown格式。"
    )


async def _llm_chat(prompt: str) -> str | None:
    if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
        return None
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
        "temperature": 0.7,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _sanitize(content) if content else None
    except Exception:
        return None


# ---------------------------------------------------------------- narration

# Small process-level LRU for LLM narrations: the same (event, step, style) is
# requested repeatedly in a classroom, no need to re-hit the LLM each time.
_LLM_CACHE_MAX = 32
_LLM_NARRATE_CACHE: dict[tuple[str, int, str], str] = {}


def _cache_get(key: tuple[str, int, str]) -> str | None:
    return _LLM_NARRATE_CACHE.get(key)


def _cache_put(key: tuple[str, int, str], value: str) -> None:
    if len(_LLM_NARRATE_CACHE) >= _LLM_CACHE_MAX:
        _LLM_NARRATE_CACHE.pop(next(iter(_LLM_NARRATE_CACHE)))  # FIFO eviction
    _LLM_NARRATE_CACHE[key] = value


def _local_narrate(event: HistoricalEvent, step: SandboxStep, style: str) -> str:
    """Template-based immersive narration, works fully offline."""
    openers = {
        "immersive": f"各位请看沙盘——时间来到{step.date}。",
        "academic": f"推演进度：{step.date}，{step.title}。",
        "storytelling": f"话说到了{step.date}，且看这沙盘之上。",
    }
    parts: list[str] = [openers.get(style, openers["immersive"])]
    parts.append(step.narrative)
    if step.background:
        parts.append(f"要理解这一幕，须知其背景：{step.background}")
    moves = []
    for arrow in step.arrows:
        if arrow.label:
            moves.append(arrow.label)
    if step.markers:
        moves.extend(m.label for m in step.markers if m.label)
    if moves:
        parts.append("沙盘之上：" + "、".join(dict.fromkeys(moves)) + "，尽收眼底。")
    if step.spirit:
        parts.append(step.spirit)
    if step.significance:
        parts.append(f"这一步的意义在于——{step.significance}")
    parts.append("历史不是尘封的年表，而是此刻正在沙盘上流动的选择。")
    return _sanitize("".join(p if p.endswith(("。", "！", "？", "：")) else p + "。" for p in parts if p))


async def narrate(event_id: str, step_id: int, style: str = "immersive"):
    from ..models import Narration

    event = get_event(event_id)
    step = get_step(event_id, step_id)
    if event is None or step is None:
        return None
    cache_key = (event_id, step_id, style)
    llm_text = _cache_get(cache_key)
    if llm_text is None:
        llm_text = await _llm_chat(build_prompt(event, step, style))
        if llm_text:
            _cache_put(cache_key, llm_text)
    if llm_text:
        return Narration(event_id=event_id, step_id=step_id, text=llm_text, source="llm")
    return Narration(
        event_id=event_id,
        step_id=step_id,
        text=_local_narrate(event, step, style),
        source="local",
    )


# -------------------------------------------------------------------- Q&A

def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[。！？；\n]+", text) if s.strip()]


def _keyword_score(sentence: str, terms: list[str]) -> int:
    return sum(1 for t in terms if t and t in sentence)


def _extract_terms(question: str) -> list[str]:
    stop = {"什么", "为什么", "怎么", "如何", "哪些", "哪个", "是谁", "多少",
            "请问", "介绍", "一下", "历史", "事件", "关于", "进行", "怎样",
            "连接", "主要", "tell"}
    # split on punctuation + common function words; keep CJK runs and latin/digit runs
    raw = re.split(r"[\s，。？！、的了呢吗吧与和及在是对从被把有：；]", question)
    terms = [t for t in raw if t and t not in stop]
    # also add 2-4 char sliding windows so 「丝绸之路连接了」 still matches 「丝绸之路」
    windows: list[str] = []
    for t in terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", t) and 3 <= len(t) <= 8:
            for size in (2, 3, 4):
                if len(t) > size:
                    windows.extend(t[i:i + size] for i in range(len(t) - size + 1))
        elif re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 8:
            # 超长专名按整词难以命中，补一个前 4 字滑窗
            windows.append(t[:4])
    terms = terms + windows
    # dedupe, drop very short single CJK chars
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            out.append(t)
    return out or [question.strip()[:8]]


def _local_answer(event: HistoricalEvent, step: SandboxStep | None, question: str, top_k: int) -> AskAnswer:
    terms = _extract_terms(question)
    corpus: list[tuple[str, str]] = []
    corpus.append((f"《{event.title}》总览", event.summary))
    if event.spirit_core:
        corpus.append(("精神内核", f"{event.title}的精神内核：{event.spirit_core}"))
    for n in event.nations:
        if n.description:
            corpus.append((f"势力·{n.name}", n.description))
    for s in event.steps:
        label = f"{s.date}·{s.title}"
        for name, body in (
            ("解说", s.narrative), ("背景", s.background),
            ("精神内核", s.spirit), ("历史意义", s.significance),
        ):
            if body:
                corpus.append((f"{label}（{name}）", body))
    if step is not None:
        for name, body in (
            ("当前步解说", step.narrative), ("当前步背景", step.background),
            ("当前步精神内核", step.spirit), ("当前步历史意义", step.significance),
        ):
            if body:
                corpus.append((f"【当前推演】{step.date}·{step.title}（{name}）", body))

    scored: list[tuple[int, str, str]] = []
    for label, body in corpus:
        best = max((_keyword_score(s, terms) for s in _split_sentences(body)), default=0)
        best += _keyword_score(label, terms)
        scored.append((best, label, body))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [h for h in scored if h[0] > 0][:top_k]

    if not hits:
        # The question mentions this event's topic (we are inside its sandbox),
        # so even with no keyword hits on details, answer from the event itself.
        if _keyword_score(event.title, terms) > 0 or _keyword_score(event.summary, terms) > 0:
            refs = [f"《{event.title}》总览"]
            tail = (
                "关于更具体的细节，可以点击时间轴上的某一步，"
                "或问我这个事件的背景、势力与精神内核。"
            )
            body = " ".join(filter(None, [event.summary, event.spirit_core]))
            return AskAnswer(
                question=question,
                answer=_sanitize(f"关于《{event.title}》：{body} {tail}"),
                source="local",
                references=refs,
            )
        generic = (
            f"这个问题超出了《{event.title}》沙盘剧本的记载范围。"
            "你可以试试问我：这个事件的背景是什么？某一方的势力如何？"
            "或者点击时间轴上的任意一步，让我讲解那里正在发生的故事。"
        )
        return AskAnswer(question=question, answer=generic, source="local", references=[])

    answer_parts: list[str] = []
    refs: list[str] = []
    for score, label, body in hits:
        sents = _split_sentences(body)
        picked = [s for s in sents if _keyword_score(s, terms) > 0] or sents[:2]
        answer_parts.append("".join(picked))
        refs.append(label)
    lead = f"结合《{event.title}》沙盘推演的记载："
    tail = ""
    refs_text = " ".join(refs)
    if "精神" in refs_text or "意义" in refs_text:
        tail = "历史的答案，往往就藏在沙盘上这些看似平静的箭头与疆界之中。"
    return AskAnswer(
        question=question,
        answer=_sanitize(lead + "".join(dict.fromkeys(answer_parts)) + tail),
        source="local",
        references=refs,
    )


async def ask(event_id: str, step_id: int | None, question: str, top_k: int = 3) -> AskAnswer | None:
    event = get_event(event_id)
    if event is None:
        return None
    step = get_step(event_id, step_id) if step_id is not None else None

    context_lines: list[str] = [f"事件：{event.title}（{event.era}）", f"概要：{event.summary}"]
    if event.spirit_core:
        context_lines.append(f"精神内核：{event.spirit_core}")
    for n in event.nations:
        if n.description:
            context_lines.append(f"{n.name}：{n.description}")
    if step is not None:
        context_lines.append(
            f"当前推演步骤 {step.date}「{step.title}」：{step.narrative} {step.spirit} {step.significance}"
        )
    prompt = (
        "你是三维历史沙盘平台的AI讲解员。仅依据以下史料回答学生的问题，"
        "若史料不足就诚实说明。用中文，120字以内，不要markdown。\n\n"
        + "\n".join(context_lines)
        + f"\n\n学生提问：{question}"
    )
    llm_text = await _llm_chat(prompt)
    if llm_text:
        return AskAnswer(question=question, answer=llm_text, source="llm", references=[])
    return _local_answer(event, step, question, top_k)
