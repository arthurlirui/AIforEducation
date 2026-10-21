"""Anim render router: 接收 scene 请求，返回 SVG 动画内容。

Studio 在推送课件时，motionCanvas block 的 SVG 由 anim_gen 生成并内嵌到
blocks_json 里（作为 fallbackSvg 或直接内联）。这个端点供前端按需获取动画。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AnimRequest(BaseModel):
    sceneRef: str
    params: dict = {}


class AnimResponse(BaseModel):
    sceneRef: str
    contentType: str
    content: str
    durationS: float


@router.post("/anim/render", response_model=AnimResponse)
def render_anim(req: AnimRequest):
    """渲染动画（当前用内嵌 SVG，M4+ 可扩展为 Motion Canvas 真实渲染）。"""
    # 延迟导入避免循环
    import sys
    from pathlib import Path
    studio_path = str(Path(__file__).resolve().parent.parent.parent.parent / "studio")
    if studio_path not in sys.path:
        sys.path.insert(0, studio_path)
    from anim_gen import generate

    result = generate(req.sceneRef, req.params)
    return AnimResponse(
        sceneRef=result.scene_ref,
        contentType=result.content_type,
        content=result.content,
        durationS=result.duration_s,
    )


@router.get("/anim/library")
def anim_library():
    """列出可用动画模板。"""
    import sys
    from pathlib import Path
    studio_path = str(Path(__file__).resolve().parent.parent.parent.parent / "studio")
    if studio_path not in sys.path:
        sys.path.insert(0, studio_path)
    from anim_gen import TEMPLATES

    return {"templates": list(TEMPLATES.keys())}
