"""In-memory scenario registry: loads built-in sandbox plays from app/data."""
from __future__ import annotations

import logging
from pathlib import Path

from ..models import HistoricalEvent

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_EVENTS: dict[str, HistoricalEvent] = {}
_LOADED = False


def _load_all() -> None:
    global _LOADED
    if _LOADED:
        return
    for fp in sorted(DATA_DIR.glob("event_*.json")):
        # One malformed data file (e.g. a hand-edited scenario) must not take
        # the whole backend down: log it and keep the other plays playable.
        try:
            event = HistoricalEvent.model_validate_json(fp.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("跳过无法解析的剧本文件：%s", fp.name)
            continue
        _EVENTS[event.id] = event
    _LOADED = True


def list_events() -> list[HistoricalEvent]:
    _load_all()
    return list(_EVENTS.values())


def get_event(event_id: str) -> HistoricalEvent | None:
    _load_all()
    return _EVENTS.get(event_id)


def get_step(event_id: str, step_id: int):
    ev = get_event(event_id)
    if ev is None:
        return None
    for s in ev.steps:
        if s.id == step_id:
            return s
    return None
