"""Asset pipeline: render masterpiece layers to static files (with cache)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import settings
from ..data.masterpieces import get_masterpiece
from .renderer import render_layers_sorted


def _layer_sig(mid: str) -> str:
    m = get_masterpiece(mid)
    blob = json.dumps(m["layers"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{mid}:{blob}".encode()).hexdigest()[:16]


def ensure_assets(mid: str) -> dict[str, Any]:
    """Render layers for a masterpiece once; reuse cached PNGs afterwards.

    Returns {layer_dir, layers:[{role, depth, url, semantics}]}.
    """
    m = get_masterpiece(mid)
    if m is None:
        return {}

    sig = _layer_sig(mid)
    layer_dir: Path = settings.output_dir / mid / sig
    layer_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = layer_dir / "manifest.json"
    manifest = None
    if manifest_path.exists():
        # 缓存损坏（如写入中途崩溃）时丢弃重渲染，避免接口持续 500
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or "layers" not in manifest:
                manifest = None
        except (json.JSONDecodeError, OSError):
            manifest = None
    if manifest is None:
        rendered = render_layers_sorted(m["layers"])
        manifest = {"layers": []}
        for r in rendered:
            fname = f"{r['role']}.png"
            (layer_dir / fname).write_bytes(r["png"])
            manifest["layers"].append(
                {
                    "role": r["role"],
                    "depth": r["depth"],
                    "semantics": r["semantics"],
                    "url": f"{settings.output_url_prefix}/{mid}/{sig}/{fname}",
                }
            )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    prefix = f"{settings.output_url_prefix}/{mid}/{sig}"
    manifest["layer_dir"] = str(layer_dir)
    manifest["prefix"] = prefix
    return manifest


def chapter_scene(mid: str) -> list[dict[str, Any]]:
    """Narrative chapters enriched with camera focus targets."""
    m = get_masterpiece(mid)
    if m is None:
        return []
    return m["chapters"]
