"""Publish client: 把 compose 产出的帧推送到 Backend admin API。"""
from __future__ import annotations

import os

import httpx


def _post(url: str, json: dict, headers: dict, timeout: float = 30):
    """发 POST 请求。测试时可 monkeypatch 此函数。"""
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


def publish_course(backend_url: str, admin_token: str, course_id: str,
                   title: str, category: str, subject: str, frames: list[dict],
                   source_id: str = "") -> dict:
    """推送课件（含帧）到 Backend（默认 draft 状态）。返回 backend 响应 JSON。"""
    payload = {
        "id": course_id,
        "title": title,
        "category": category,
        "subject": subject,
        "source_id": source_id,
        "frames": frames,
    }
    headers = {"X-Admin-Token": admin_token}
    r = _post(f"{backend_url}/api/admin/courses", payload, headers)
    r.raise_for_status()
    return r.json()


def publish_and_publish(backend_url: str, admin_token: str, course_id: str,
                        title: str, category: str, subject: str, frames: list[dict],
                        source_id: str = "", publish: bool | None = None) -> dict:
    """推送 + 发布上线。

    设计稿 §4b.5 的语义是"Studio 推送默认 draft，Backend 定时校验后批量发布"
    （给人工审核留窗口）。当前实现没有这道闸门，LLM 生成内容直接上线（S12）。
    取舍：保持默认直发（现行为不变），但提供 draft 模式开关——
    - publish=False：只推送不发布，留给人工/定时审核；
    - publish=None（默认）：读环境变量 TLS_PUBLISH_DRAFT=1 → draft 模式，否则直发。
    """
    if publish is None:
        publish = os.environ.get("TLS_PUBLISH_DRAFT", "").lower() not in ("1", "true", "yes")

    publish_course(backend_url, admin_token, course_id, title, category, subject, frames, source_id)
    if not publish:
        return {"status": "draft", "course_id": course_id}
    r = _post(f"{backend_url}/api/admin/courses/{course_id}/publish",
              {}, {"X-Admin-Token": admin_token})
    r.raise_for_status()
    return r.json()
