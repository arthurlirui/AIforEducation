"""路由层 TestClient 冒烟测试（离线，全部走 mock provider 或参数校验失败路径）.

覆盖:
- health / styles / gallery / providers 只读端点
- POST /api/generate 的 400 (未知风格) / 422 (Pydantic 校验) / 200 (mock)
- 错误映射: 上游 401/403/429/5xx/连接错误 → 友好中文提示且不透传原始异常
- POST /api/compose-preview 与 generate 的合成提示词一致性
- /api/generate 每 IP 滑动窗口限流 (429)
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.services import generate_service


@pytest.fixture()
def client() -> TestClient:
    # Fresh app per test → fresh rate-limit window.
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# 只读端点冒烟
# ---------------------------------------------------------------------------

class TestReadOnlyEndpoints:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "mock" in body["providers"]

    def test_styles_list_and_404(self, client):
        r = client.get("/api/styles")
        assert r.status_code == 200
        assert len(r.json()) >= 12
        assert client.get("/api/styles/impressionism").status_code == 200
        assert client.get("/api/styles/no-such").status_code == 404

    def test_gallery(self, client):
        r = client.get("/api/gallery")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_providers_metadata_includes_supported_sizes(self, client):
        r = client.get("/api/providers")
        assert r.status_code == 200
        entries = {p["id"]: p for p in r.json()}
        assert entries["openai"]["supported_sizes"] == [
            "1024x1024", "1024x1792", "1792x1024",
        ]
        assert entries["dashscope"]["supported_sizes"][0] == "1024x1024"
        assert isinstance(entries["mock"]["supported_sizes"], list)


# ---------------------------------------------------------------------------
# POST /api/generate
# ---------------------------------------------------------------------------

class TestGenerateValidation:
    def test_unknown_style_400(self, client):
        r = client.post("/api/generate", json={"prompt": "x", "style_id": "no-such"})
        assert r.status_code == 400
        assert "no-such" in r.json()["detail"]

    def test_malformed_size_422(self, client):
        r = client.post(
            "/api/generate",
            json={"prompt": "x", "style_id": "impressionism", "size": "abc"},
        )
        assert r.status_code == 422

    def test_missing_x_size_422(self, client):
        r = client.post(
            "/api/generate",
            json={"prompt": "x", "style_id": "impressionism", "size": "1024"},
        )
        assert r.status_code == 422

    def test_n_out_of_range_422(self, client):
        r = client.post(
            "/api/generate",
            json={"prompt": "x", "style_id": "impressionism", "n": 5},
        )
        assert r.status_code == 422

    def test_empty_prompt_422(self, client):
        r = client.post("/api/generate", json={"prompt": "", "style_id": "impressionism"})
        assert r.status_code == 422


class TestGenerateMock:
    def test_mock_generate_ok(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        monkeypatch.setattr(generate_service, "GALLERY_INDEX", tmp_path / "gallery.json")
        r = client.post(
            "/api/generate",
            json={
                "prompt": "a quiet harbor",
                "style_id": "impressionism",
                "provider": "mock",
                "n": 2,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["images"]) == 2
        assert body["provider"] == "mock"
        assert body["elapsed_ms"] >= 0
        # 5.3: 服务器本地路径不暴露给客户端
        assert "local_path" not in body["images"][0]
        # notes 字段存在（mock 无提示时为空列表）
        assert body["notes"] == []
        # 正常路径无降级（2.5）
        assert body["fallback_from"] is None
        # 合成提示词与 compose-preview 完全一致（4.3 一致性）
        pv = client.post(
            "/api/compose-preview",
            json={"prompt": "a quiet harbor", "style_id": "impressionism"},
        )
        assert pv.status_code == 200
        assert pv.json()["composed_prompt"] == body["composed_prompt"]
        # 画廊写入
        import json as _json
        saved = _json.loads((tmp_path / "gallery.json").read_text(encoding="utf-8"))
        assert len(saved) == 2

    def test_unavailable_provider_falls_back_with_fallback_from(
        self, client, tmp_path, monkeypatch
    ):
        """2.5: 所选 provider 不可用回退 mock 时不再静默降级——
        响应携带 fallback_from=原请求名，图片照常生成。"""
        from app.services.providers.sdwebui_provider import SDWebUIProvider

        monkeypatch.setattr(SDWebUIProvider, "available", lambda self: False)
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        monkeypatch.setattr(generate_service, "GALLERY_INDEX", tmp_path / "gallery.json")
        r = client.post(
            "/api/generate",
            json={
                "prompt": "a quiet harbor",
                "style_id": "impressionism",
                "provider": "sdwebui",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "mock"
        assert body["fallback_from"] == "sdwebui"
        assert len(body["images"]) == 1
        assert body["images"][0]["url"].startswith("/files/")


# ---------------------------------------------------------------------------
# 2.2 错误映射（不透传原始异常文本）
# ---------------------------------------------------------------------------

class _FailingProvider:
    name = "mock"
    notes: list = []

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def generate(self, **kwargs):
        raise self._exc


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://upstream.example.com/images")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"Server error '{status_code}' for url 'https://upstream.example.com/images'",
        request=request,
        response=response,
    )


def _post_with_provider_error(client, monkeypatch, exc):
    monkeypatch.setattr(
        generate_service, "get_provider", lambda *a, **k: _FailingProvider(exc)
    )
    return client.post(
        "/api/generate", json={"prompt": "x", "style_id": "impressionism"}
    )


class TestErrorMapping:
    def test_upstream_401_maps_to_400(self, client, monkeypatch):
        r = _post_with_provider_error(client, monkeypatch, _status_error(401))
        assert r.status_code == 400
        assert r.json()["detail"] == "API Key 无效或未授权"
        # 不透传原始异常文本（含上游 URL）
        assert "upstream.example.com" not in r.json()["detail"]

    def test_upstream_403_maps_to_400(self, client, monkeypatch):
        r = _post_with_provider_error(client, monkeypatch, _status_error(403))
        assert r.status_code == 400
        assert r.json()["detail"] == "API Key 无效或未授权"

    def test_upstream_429_maps_to_429(self, client, monkeypatch):
        r = _post_with_provider_error(client, monkeypatch, _status_error(429))
        assert r.status_code == 429
        assert r.json()["detail"] == "调用过于频繁，请稍后重试"

    def test_upstream_500_maps_to_502(self, client, monkeypatch):
        r = _post_with_provider_error(client, monkeypatch, _status_error(500))
        assert r.status_code == 502
        assert r.json()["detail"] == "模型服务暂时不可用"

    def test_connect_error_maps_to_502(self, client, monkeypatch):
        r = _post_with_provider_error(
            client, monkeypatch, httpx.ConnectError("connection refused")
        )
        assert r.status_code == 502
        assert r.json()["detail"] == "模型服务暂时不可用"

    def test_timeout_maps_to_502(self, client, monkeypatch):
        r = _post_with_provider_error(
            client, monkeypatch, httpx.ReadTimeout("timed out")
        )
        assert r.status_code == 502
        assert r.json()["detail"] == "模型服务暂时不可用"

    def test_unexpected_error_maps_to_502_generic(self, client, monkeypatch):
        r = _post_with_provider_error(
            client, monkeypatch, RuntimeError("secret internals")
        )
        assert r.status_code == 502
        assert r.json()["detail"] == "图像生成失败，请稍后重试"
        assert "secret internals" not in r.json()["detail"]


# ---------------------------------------------------------------------------
# compose-preview
# ---------------------------------------------------------------------------

class TestComposePreview:
    def test_ok(self, client):
        r = client.post(
            "/api/compose-preview",
            json={
                "prompt": "a quiet harbor",
                "style_id": "impressionism",
                "extra_keywords": "golden hour",
            },
        )
        assert r.status_code == 200
        composed = r.json()["composed_prompt"]
        assert composed.startswith("a quiet harbor")
        assert "golden hour" in composed
        assert "in the manner of Claude Monet" in composed

    def test_unknown_style_400(self, client):
        r = client.post(
            "/api/compose-preview",
            json={"prompt": "x", "style_id": "no-such"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5.1 限流
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_generate_rate_limited_429(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
        client = TestClient(create_app())
        payload = {"prompt": "x", "style_id": "no-such"}  # 400 但计入限流窗口
        for _ in range(3):
            assert client.post("/api/generate", json=payload).status_code == 400
        r = client.post("/api/generate", json=payload)
        assert r.status_code == 429
        assert "频繁" in r.json()["detail"]

    def test_rate_limit_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
        client = TestClient(create_app())
        payload = {"prompt": "x", "style_id": "no-such"}
        for _ in range(3):
            assert client.post("/api/generate", json=payload).status_code == 400

    def test_only_generate_is_limited(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
        client = TestClient(create_app())
        assert (
            client.post("/api/generate", json={"prompt": "x", "style_id": "no-such"})
            .status_code
            == 400
        )
        # 其它端点不受限流影响
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/styles").status_code == 200
        assert (
            client.post(
                "/api/compose-preview",
                json={"prompt": "x", "style_id": "impressionism"},
            ).status_code
            == 200
        )
