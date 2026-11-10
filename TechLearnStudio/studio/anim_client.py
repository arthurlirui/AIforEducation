"""Anim client: Studio 侧的 Backend 动画渲染轻量 HTTP 客户端（S5）。

动画模板的唯一实现在 backend（app/services/anim_gen.py），Studio 不再持有
本地副本：compose 生成 motionCanvas 块的 fallbackSvg 通过
POST /api/anim/render 获取。backend 不可达时返回 None，由调用方降级
（composer/pipeline.py 用通用静态占位 SVG），保证 compose 完全离线可用。
"""
from __future__ import annotations

import os

import httpx

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
_TIMEOUT_S = 3.0


def _post(url: str, payload: dict, timeout: float = _TIMEOUT_S):
    """发 POST 请求。测试时可 monkeypatch 此函数（与 publish.client 同约定）。"""
    return httpx.post(url, json=payload, timeout=timeout)


def backend_base_url() -> str:
    """Backend 基址：env TLS_BACKEND_URL，默认 http://127.0.0.1:8000。"""
    return os.environ.get("TLS_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def fetch_fallback_svg(scene_ref: str, params: dict | None = None,
                       base_url: str | None = None) -> str | None:
    """向 backend 请求动画 SVG；失败/超时/非 200/非 SVG 一律返回 None（不抛异常）。"""
    base = (base_url or backend_base_url()).rstrip("/")
    try:
        r = _post(f"{base}/api/anim/render",
                  {"sceneRef": scene_ref, "params": params or {}})
        if r.status_code != 200:
            return None
        content = r.json().get("content", "")
    except Exception:
        # 网络不可达/超时/坏响应：离线降级交给调用方
        return None
    if not isinstance(content, str) or not content.strip().startswith("<svg"):
        return None
    return content
