"""Shared text sanitisation for anything the frontend renders.

The frontend renders all text through Vue interpolation (never v-html), but
every LLM output path must still pass through `sanitize` so a stray markup /
script payload can never reach the UI even if a rendering path changes.
"""
from __future__ import annotations

import re

_BAD_CHARS = re.compile(r"[<>{}\\]")


def sanitize(text: str, limit: int = 900) -> str:
    """Strip characters that could smuggle markup/script content, then truncate."""
    return _BAD_CHARS.sub("", text).strip()[:limit]
