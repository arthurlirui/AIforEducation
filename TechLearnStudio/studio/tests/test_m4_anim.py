"""M4 测试：motionCanvas fallbackSvg 的 HTTP 获取与离线降级（S5 消除 anim 复制后）。

动画模板的内容生成测试已随唯一实现迁往 backend/tests/test_backend.py
（backend 独占 anim 生成）；本模块只测 studio 侧行为：
- anim_client：HTTP 获取 / 失败降级 None / env 基址 / 非 SVG 内容拒绝；
- composer：离线时 fallbackSvg 为通用静态占位 SVG（过前端 isSafeSvg 白名单），
  backend 可达时为 HTTP 返回内容。
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import anim_client
from composer import compose
from composer.pipeline import _PLACEHOLDER_SVG
from composer.samples import SIGNAL_CONVOLUTION


def _mc_block(frames):
    diag = next(f for f in frames if f["layout"] == "diagram")
    blocks = json.loads(diag["blocks_json"])
    return next(b for b in blocks if b["type"] == "motionCanvas")


def _is_safe_svg(svg: str) -> bool:
    """前端 hyperframes.js isSafeSvg 白名单的 Python 复刻（保持同语义）。"""
    s = svg.strip()
    return (s.startswith("<svg")
            and not re.search(r"<script", s, re.I)
            and not re.search(r"\son\w+\s*=", s, re.I)
            and not re.search(r"javascript:", s, re.I))


# ---------- anim_client ----------
def test_fetch_fallback_svg_offline_returns_none(monkeypatch):
    def _conn_refused(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(anim_client, "_post", _conn_refused)
    assert anim_client.fetch_fallback_svg("convolution", {}) is None


def test_fetch_fallback_svg_ok_returns_content(monkeypatch):
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    monkeypatch.setattr(anim_client, "_post",
                        lambda *a, **k: SimpleNamespace(status_code=200,
                                                        json=lambda: {"content": svg}))
    assert anim_client.fetch_fallback_svg("convolution", {}) == svg


def test_fetch_fallback_svg_non_200_or_non_svg_returns_none(monkeypatch):
    # 非 200 → None
    monkeypatch.setattr(anim_client, "_post",
                        lambda *a, **k: SimpleNamespace(status_code=404,
                                                        json=lambda: {}))
    assert anim_client.fetch_fallback_svg("convolution", {}) is None
    # 200 但内容不是 SVG → None
    monkeypatch.setattr(anim_client, "_post",
                        lambda *a, **k: SimpleNamespace(status_code=200,
                                                        json=lambda: {"content": "<p>hi</p>"}))
    assert anim_client.fetch_fallback_svg("convolution", {}) is None


def test_fetch_fallback_svg_uses_env_base_url(monkeypatch):
    seen = {}

    def _fake_post(url, payload, timeout=3.0):
        seen["url"] = url
        seen["payload"] = payload
        return SimpleNamespace(status_code=200, json=lambda: {"content": "<svg/>"})

    monkeypatch.setattr(anim_client, "_post", _fake_post)
    monkeypatch.setenv("TLS_BACKEND_URL", "http://10.0.0.9:9000/")
    assert anim_client.fetch_fallback_svg("ownership_move", {"move_from": "a"}) == "<svg/>"
    assert seen["url"] == "http://10.0.0.9:9000/api/anim/render"
    assert seen["payload"] == {"sceneRef": "ownership_move", "params": {"move_from": "a"}}


# ---------- compose 集成 ----------
def test_compose_offline_uses_placeholder_svg(monkeypatch):
    """无 backend 时 motionCanvas 的 fallbackSvg 为通用静态占位 SVG，
    且过前端 isSafeSvg 白名单（compose 完全离线可用）。"""
    def _conn_refused(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(anim_client, "_post", _conn_refused)

    frames = compose(SIGNAL_CONVOLUTION)
    mc = _mc_block(frames)
    assert mc["fallbackSvg"] == _PLACEHOLDER_SVG
    assert "animation unavailable offline" in mc["fallbackSvg"]
    assert _is_safe_svg(mc["fallbackSvg"])
    # block 结构与 hyperframes.js 的消费约定不变（data-mc-block ← sceneRef）
    assert mc["sceneRef"] == "convolution"
    assert mc["params"] == {}
    assert mc["renderMode"] == "video"


def test_compose_with_backend_uses_http_svg(monkeypatch):
    """mock httpx 命中 backend 时 fallbackSvg 为 HTTP 返回内容。"""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg">'
           '<rect><animate attributeName="opacity" values="0;1"/></rect></svg>')
    monkeypatch.setattr(anim_client, "_post",
                        lambda *a, **k: SimpleNamespace(status_code=200,
                                                        json=lambda: {"content": svg}))
    frames = compose(SIGNAL_CONVOLUTION)
    mc = _mc_block(frames)
    assert mc["fallbackSvg"] == svg
