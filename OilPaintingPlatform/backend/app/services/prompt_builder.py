"""Prompt synthesis service.

Combines the user's prompt with the chosen style preset to produce a final
prompt suitable for vision language models.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..config import DATA_DIR, settings
from ..schemas import StylePreset


@lru_cache
def _load_styles() -> Dict[str, StylePreset]:
    path = DATA_DIR / "styles.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: StylePreset(**item) for item in raw}


def list_styles() -> List[StylePreset]:
    return list(_load_styles().values())


def get_style(style_id: str) -> Optional[StylePreset]:
    return _load_styles().get(style_id)


def compose_prompt(
    user_prompt: str,
    style: StylePreset,
    extra_keywords: Optional[str] = None,
) -> str:
    """Build the final prompt sent to the image model.

    Strategy:
      1. Start with the user prompt (the subject).
      2. Append style prompt_keywords.
      3. Append optional extra keywords.
      4. Append a hint about medium if not already present.
      5. Append reference artists when available.
    """
    parts: List[str] = [user_prompt.strip()]

    style_kw = list(style.prompt_keywords)
    if style_kw:
        parts.append(", ".join(style_kw))

    if extra_keywords:
        parts.append(extra_keywords.strip())

    # Hint at medium if the user did not mention it
    lower = user_prompt.lower()
    if "oil painting" not in lower and "油画" not in user_prompt:
        parts.append("oil painting on canvas")

    if style.reference_artists:
        parts.append(
            "in the manner of " + " / ".join(style.reference_artists[:2])
        )

    # Negative prompt (kept separately for providers that support it)
    return ", ".join(p for p in parts if p)


def compose_negative_prompt(style: StylePreset) -> str:
    """Negative prompt for providers that support it (SD, etc.)."""
    base = "low quality, blurry, deformed, extra fingers, watermark, text, jpeg artifacts"
    extra = ", ".join(style.negative_keywords) if style.negative_keywords else ""
    return f"{base}, {extra}" if extra else base


__all__ = [
    "compose_prompt",
    "compose_negative_prompt",
    "list_styles",
    "get_style",
]
