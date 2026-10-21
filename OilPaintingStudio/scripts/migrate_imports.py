"""migrate_imports.py — 重写整合后包的相对导入路径.

原结构:
    oilpaint/  (OilPaintingVideo)  →  oilpainting_studio/video/
    oilrev/    (OilPaintingRevive) →  oilpainting_studio/revive/
    共享: oilpaint/config.py, llm_client.py, comfy/  →  oilpainting_studio/common/

重写规则:
    revive/ 内:
        ..config         → ..common.config
        ..schemas        → .schemas       (schemas.py 留在 revive/)
        ..comfy          → ..common.comfy
        ..llm_client     → ..common.llm_client
        ..pipeline       → ..video.pipeline
        ..stageN         → .stageN        (同级)
        ..utils          → ..common.utils
    video/ 内:
        ..config         → ..common.config
        ..llm_client     → ..common.llm_client
        ..comfy          → ..common.comfy
        ..pipeline       → .pipeline      (同级)
        ..mesh2video     → .mesh2video
        ..screenplay     → .screenplay
        ..audio          → .audio
        ..utils          → ..common.utils
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "oilpainting_studio"


def migrate_revive(text: str) -> str:
    # ..config / ..llm_client / ..comfy / ..utils → ..common.*
    text = re.sub(r"from \.\.config\b", "from ..common.config", text)
    text = re.sub(r"from \.\.llm_client\b", "from ..common.llm_client", text)
    text = re.sub(r"from \.\.comfy\b", "from ..common.comfy", text)
    text = re.sub(r"from \.\.utils\b", "from ..common.utils", text)
    # ..pipeline.* → ..video.pipeline.*  (pipeline 在 video/)
    text = re.sub(r"from \.\.pipeline\b", "from ..video.pipeline", text)
    # ..schemas → .schemas  (同级)
    text = re.sub(r"from \.\.schemas\b", "from .schemas", text)
    # ..stageN → .stageN  (同级)
    text = re.sub(r"from \.\.(stage\d+)\b", r"from .\1", text)
    return text


def migrate_video(text: str) -> str:
    # ..config / ..llm_client / ..comfy / ..utils → ..common.*
    text = re.sub(r"from \.\.config\b", "from ..common.config", text)
    text = re.sub(r"from \.\.llm_client\b", "from ..common.llm_client", text)
    text = re.sub(r"from \.\.comfy\b", "from ..common.comfy", text)
    text = re.sub(r"from \.\.utils\b", "from ..common.utils", text)
    # ..pipeline / ..mesh2video / ..screenplay / ..audio → .*(同级)
    text = re.sub(r"from \.\.pipeline\b", "from .pipeline", text)
    text = re.sub(r"from \.\.mesh2video\b", "from .mesh2video", text)
    text = re.sub(r"from \.\.screenplay\b", "from .screenplay", text)
    text = re.sub(r"from \.\.audio\b", "from .audio", text)
    return text


def main() -> int:
    changed = 0
    for subpkg, migrator in [("revive", migrate_revive), ("video", migrate_video)]:
        pkg_dir = ROOT / subpkg
        for py in pkg_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            orig = py.read_text(encoding="utf-8")
            new = migrator(orig)
            if new != orig:
                py.write_text(new, encoding="utf-8")
                changed += 1
                print(f"  migrated: {py.relative_to(ROOT)}")
    print(f"\n{changed} files migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
