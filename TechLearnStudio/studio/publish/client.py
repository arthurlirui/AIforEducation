"""Publish client: 把 compose 产出的帧推送到 Backend admin API。"""
from __future__ import annotations

import httpx


def _post(url: str, json: dict, headers: dict, timeout: float = 30):
    """发 POST 请求。测试时可 monkeypatch 此函数。"""
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


def publish_course(backend_url: str, admin_token: str, course_id: str,
                   title: str, category: str, subject: str, frames: list[dict],
                   source_id: str = "") -> dict:
    """推送课件（含帧）到 Backend。返回 backend 响应 JSON。"""
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
                        source_id: str = "") -> dict:
    """推送 + 发布上线。"""
    publish_course(backend_url, admin_token, course_id, title, category, subject, frames, source_id)
    r = _post(f"{backend_url}/api/admin/courses/{course_id}/publish",
              {}, {"X-Admin-Token": admin_token})
    r.raise_for_status()
    return r.json()
