"""Asset pipeline: render masterpiece layers to static files (with cache)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..config import settings
from ..data.masterpieces import get_masterpiece
from . import renderer


def _renderer_code_sig() -> str:
    """哈希渲染器源码：任何渲染代码改动都会轮换缓存签名。

    渲染是确定性的（同处方同代码 → 同 PNG 字节），所以「处方 JSON + 渲染器
    代码内容」共同构成缓存的完整键。历史上签名只含处方，导致改完 renderer.py
    后仍命中旧缓存、修复静默失效（只能靠手动删目录）。
    """
    try:
        src = Path(renderer.__file__).read_bytes()
    except (OSError, TypeError):  # frozen/zipapp 等拿不到源文件的兜底
        src = getattr(renderer, "FALLBACK_VERSION", "0").encode()
    return hashlib.sha256(src).hexdigest()[:12]


# import 时算一次：多 worker 进程各自 import 结果一致，无需每次请求重算
_RENDERER_SIG = _renderer_code_sig()


def _layer_sig(mid: str) -> str:
    m = get_masterpiece(mid)
    blob = json.dumps(m["layers"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{mid}:{_RENDERER_SIG}:{blob}".encode()).hexdigest()[:16]


def _atomic_write(path: Path, data: bytes | str) -> None:
    """先写 .tmp 再 os.replace：并发请求下静态 GET 不会读到半截文件。"""
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


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

    # GC：渲染器/处方一变签名即变，清掉同 mid 下旧签名目录，
    # 避免每次代码改动都遗留一套永不删除的旧 PNG
    parent = layer_dir.parent
    if parent.exists():
        for old in parent.iterdir():
            if old.is_dir() and old.name != sig:
                shutil.rmtree(old, ignore_errors=True)

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
        rendered = renderer.render_layers_sorted(m["layers"])
        manifest = {"layers": []}
        for r in rendered:
            fname = f"{r['role']}.png"
            _atomic_write(layer_dir / fname, r["png"])
            manifest["layers"].append(
                {
                    "role": r["role"],
                    "depth": r["depth"],
                    "semantics": r["semantics"],
                    "url": f"{settings.output_url_prefix}/{mid}/{sig}/{fname}",
                }
            )
        _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    prefix = f"{settings.output_url_prefix}/{mid}/{sig}"
    manifest["layer_dir"] = str(layer_dir)
    manifest["prefix"] = prefix
    return manifest
