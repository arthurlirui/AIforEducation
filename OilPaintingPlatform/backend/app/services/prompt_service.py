"""Prompt template library service."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Optional

from ..config import DATA_DIR
from ..schemas import PromptTemplate


@lru_cache
def _load() -> Dict[str, PromptTemplate]:
    path = DATA_DIR / "prompts.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: PromptTemplate(**item) for item in raw}


def list_prompts(category: Optional[str] = None) -> List[PromptTemplate]:
    items = list(_load().values())
    if category:
        items = [p for p in items if p.category == category]
    return items


def get_prompt(prompt_id: str) -> Optional[PromptTemplate]:
    return _load().get(prompt_id)


def categories() -> List[str]:
    seen = []
    for p in _load().values():
        if p.category not in seen:
            seen.append(p.category)
    return seen
