"""High-level generation service used by the API router."""
from __future__ import annotations

import time
import threading
import uuid
import json
from typing import List, Optional

from ..config import DATA_DIR, settings
from ..schemas import (
    GenerateRequest,
    GenerateResponse,
    GeneratedImage,
    StylePreset,
)
from .prompt_builder import compose_prompt, compose_negative_prompt, get_style
from .providers import get_provider


GALLERY_INDEX = DATA_DIR / "gallery.json"

# Serializes the read-modify-write cycle on gallery.json: FastAPI runs sync
# endpoints in a thread pool, so concurrent generates could otherwise lose
# each other's entries.
_GALLERY_LOCK = threading.Lock()


def generate(request: GenerateRequest) -> GenerateResponse:
    style = get_style(request.style_id)
    if style is None:
        raise ValueError(f"Unknown style_id: {request.style_id}")

    composed = compose_prompt(request.prompt, style, request.extra_keywords)
    negative = compose_negative_prompt(style)

    # Build credentials dict from the request
    creds = None
    if request.credentials:
        creds = {
            "api_key": request.credentials.api_key,
            "api_id": request.credentials.api_id,
            "base_url": request.credentials.base_url,
        }

    provider = get_provider(request.provider, credentials=creds)
    images: List[GeneratedImage] = provider.generate(
        prompt=composed,
        negative_prompt=negative,
        size=request.size,
        n=request.n,
    )

    # Stamp provider name (mock fallback may differ from requested)
    provider_name = provider.name
    # Provider-level notes (e.g. "negative_prompt ignored by this model")
    notes = list(getattr(provider, "notes", []))
    # Requested provider name when the mock placeholder had to stand in
    # (None on the normal path) — surfaced so the degradation is visible
    fallback_from = getattr(provider, "fallback_from", None)

    # Persist to gallery index
    _append_gallery(images, composed, style, provider_name)

    elapsed = 0  # placeholder; router measures wall time
    return GenerateResponse(
        images=images,
        composed_prompt=composed,
        style=style,
        provider=provider_name,
        elapsed_ms=elapsed,
        notes=notes,
        fallback_from=fallback_from,
    )


def _append_gallery(
    images: List[GeneratedImage],
    prompt: str,
    style: StylePreset,
    provider: str,
) -> None:
    if not images:
        return
    with _GALLERY_LOCK:
        GALLERY_INDEX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if GALLERY_INDEX.exists():
            try:
                existing = json.loads(GALLERY_INDEX.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        for img in images:
            existing.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "url": img.url,
                    "prompt": prompt,
                    "style_id": style.id,
                    "style_name": style.name,
                    "provider": provider,
                    "created_at": ts,
                }
            )
        # Keep the gallery capped
        existing = existing[-200:]
        GALLERY_INDEX.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def list_gallery(limit: int = 50) -> list:
    if not GALLERY_INDEX.exists():
        return []
    try:
        data = json.loads(GALLERY_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(reversed(data[-limit:]))


__all__ = ["generate", "list_gallery"]
