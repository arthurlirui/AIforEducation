"""fix_nested_imports.py — 修复嵌套子模块的导入深度.

迁移脚本把 ..config → ..common.config, 但对位于 video/pipeline/, video/mesh2video/,
video/screenplay/, revive/stage1..5/ 的文件, ..common 解析到错误的包
(video.common / revive.common). 需要改为 ...common (3 个点) 才能解析到
oilpainting_studio.common.

规则:
    video/pipeline/*.py:     ..common.* → ...common.*
    video/mesh2video/*.py:   ..common.* → ...common.*
    video/screenplay/*.py:   ..common.* → ...common.*
    revive/stage1..5/*.py:   ..common.* → ...common.*
    video/pipeline/*.py:     ..video.pipeline.* (自身, 不变)
    revive/stage3/reposition.py: ..video.pipeline.* → ...video.pipeline.* (3 点)
    revive/stage3/reposition.py: ..stage2.* → ...stage2.* (3 点, 跨 revive 子目录)

顶层文件 (video/cli.py, revive/cli.py, video/__init__.py, revive/__init__.py)
保持 ..common.* (2 点正确).
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "oilpainting_studio"

# 需要修复的嵌套目录 (这些目录下的文件 .. 解析到 video/ 或 revive/, 不是 oilpainting_studio/)
NESTED_DIRS = [
    ROOT / "video" / "pipeline",
    ROOT / "video" / "mesh2video",
    ROOT / "video" / "screenplay",
    ROOT / "video" / "audio",
    ROOT / "revive" / "stage1",
    ROOT / "revive" / "stage2",
    ROOT / "revive" / "stage3",
    ROOT / "revive" / "stage4",
    ROOT / "revive" / "stage5",
]


def fix_nested(text: str) -> str:
    # ..common.* → ...common.*
    text = re.sub(r"from \.\.common\.", "from ...common.", text)
    # ..video.pipeline.* → ...video.pipeline.*  (revive 引用 video pipeline)
    text = re.sub(r"from \.\.video\.", "from ...video.", text)
    # ..stageN.* → ...stageN.*  (revive 跨 stage 引用, 如 stage3 → stage2)
    text = re.sub(r"from \.\.(stage\d+)\.", r"from ...\1.", text)
    return text


def main() -> int:
    changed = 0
    for d in NESTED_DIRS:
        if not d.exists():
            continue
        for py in d.glob("*.py"):
            if "__pycache__" in py.parts:
                continue
            orig = py.read_text(encoding="utf-8")
            new = fix_nested(orig)
            if new != orig:
                py.write_text(new, encoding="utf-8")
                changed += 1
                print(f"  fixed: {py.relative_to(ROOT)}")
    print(f"\n{changed} files fixed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
