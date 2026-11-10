"""Anim render router: 接收 scene 请求，返回 SVG 动画内容。

Studio 在 compose 时经此端点获取 motionCanvas block 的 fallbackSvg
（内嵌进 blocks_json 推送）；前端播放中同样按需调此端点渲染动画。
模板唯一实现在 backend 本地（app/services/anim_gen.py），studio 无副本。

S5：模板实现在 backend 本地（app/services/anim_gen.py 是唯一实现，
studio 无副本——compose 侧经 HTTP 调用本端点获取 fallbackSvg），
不再运行时注入 studio 源码路径——backend 可独立部署。
S6：sceneRef 白名单 + params 按 Pydantic 模型校验（超界/类型错误 → 422，
非数值不再落到模板内部变 500）。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..services.anim_gen import TEMPLATES, generate

router = APIRouter()

# sceneRef 白名单：只接受已注册模板
SceneRef = Literal["convolution", "ownership_move", "ofdm_subcarriers", "attention_flow"]


class ConvolutionParams(BaseModel):
    signal: list[float] = Field(default=[1.0, 2.0, 3.0, 1.0], max_length=64)
    kernel: list[float] = Field(default=[1.0, 0.0, -1.0], max_length=64)
    mode: Literal["full", "valid"] = "full"


class OwnershipParams(BaseModel):
    vars: list[str] | None = Field(default=None, max_length=16)
    move_from: str = Field(default="s", max_length=64)
    move_to: str = Field(default="t", max_length=64)


class OfdmParams(BaseModel):
    n_subcarriers: int = Field(default=4, ge=1, le=32)
    symbols: list[float] | None = Field(default=None, max_length=64)
    show_fft: bool = True


class AttentionParams(BaseModel):
    seq_len: int = Field(default=4, ge=1, le=16)
    heads: int = Field(default=1, ge=1, le=16)
    weights: list[float] | None = Field(default=None, max_length=256)


_ANIM_PARAMS: dict[str, type[BaseModel]] = {
    "convolution": ConvolutionParams,
    "ownership_move": OwnershipParams,
    "ofdm_subcarriers": OfdmParams,
    "attention_flow": AttentionParams,
}


class AnimRequest(BaseModel):
    sceneRef: SceneRef
    params: dict = {}


class AnimResponse(BaseModel):
    sceneRef: str
    contentType: str
    content: str
    durationS: float


@router.post("/anim/render", response_model=AnimResponse)
def render_anim(req: AnimRequest):
    """渲染动画（当前用内嵌 SVG，M4+ 可扩展为 Motion Canvas 真实渲染）。"""
    try:
        params = _ANIM_PARAMS[req.sceneRef](**req.params)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False)) from e
    result = generate(req.sceneRef, params.model_dump())
    return AnimResponse(
        sceneRef=result.scene_ref,
        contentType=result.content_type,
        content=result.content,
        durationS=result.duration_s,
    )


@router.get("/anim/library")
def anim_library():
    """列出可用动画模板。"""
    return {"templates": list(TEMPLATES.keys())}
