"""Provider 层安全与凭据链路测试（全部 mock httpx，离线可跑）.

覆盖:
- 1.1 凭据泄露链: env Key + 客户端 base_url 互斥; scheme 白名单
- 1.2 DashScope 提交与轮询使用同一凭据
- 1.3 pollinations 重试 transport + negative_prompt 忽略提示 (notes)
- 1.4 pollinations md5 确定性 seed
- 1.5 sdwebui available() TTL 缓存
- 1.7 zhipu 下载失败显式抛错（不再静默入画廊）
"""
from __future__ import annotations

import base64
import hashlib
import time
import types

import httpx
import pytest

from app.config import settings
from app.schemas import GeneratedImage
from app.services.providers.dashscope_provider import DashscopeProvider
from app.services.providers.openai_provider import OpenAIProvider
from app.services.providers.pollinations_provider import PollinationsProvider
from app.services.providers.sdwebui_provider import (
    SDWebUIProvider,
    _AVAILABILITY_CACHE,
)
from app.services.providers.zhipu_provider import ZhipuProvider


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, content=b""):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._json


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------------------------------------------------------------------------
# 1.1 凭据泄露链: env Key 时禁止客户端覆盖 base_url
# ---------------------------------------------------------------------------

class TestBaseUrlSecurity:
    def _patch_openai_http(self, monkeypatch, calls):
        import app.services.providers.openai_provider as mod

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "headers": headers})
            return _FakeResponse(
                json_data={"data": [{"b64_json": _b64(b"img")}]}
            )

        monkeypatch.setattr(mod, "httpx", types.SimpleNamespace(post=fake_post))

    def test_env_key_ignores_malicious_base_url(self, monkeypatch, tmp_path):
        """(a) 无客户端凭据 + 恶意 base_url → 实际请求走 default/env base_url."""
        monkeypatch.setattr(settings, "openai_api_key", "env-secret-key")
        monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
        monkeypatch.setattr(settings, "output_dir", tmp_path)

        calls: list = []
        self._patch_openai_http(monkeypatch, calls)

        provider = OpenAIProvider(credentials={"base_url": "http://attacker.example/v1"})
        assert provider.available()  # env key 在用
        provider.generate("a harbor", negative_prompt="blurry")

        assert len(calls) == 1
        assert calls[0]["url"].startswith("https://api.openai.com/v1")
        assert "attacker.example" not in calls[0]["url"]
        # Authorization 头也只发给可信 host
        assert calls[0]["headers"]["Authorization"] == "Bearer env-secret-key"

    def test_client_key_allows_custom_base_url(self, monkeypatch, tmp_path):
        """(b) 自带 api_key + 自定义 base_url → 尊重客户端设置."""
        monkeypatch.setattr(settings, "openai_api_key", "env-secret-key")
        monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
        monkeypatch.setattr(settings, "output_dir", tmp_path)

        calls: list = []
        self._patch_openai_http(monkeypatch, calls)

        provider = OpenAIProvider(
            credentials={
                "api_key": "client-key",
                "base_url": "https://my-proxy.example/v1",
            }
        )
        provider.generate("a harbor", negative_prompt="blurry")

        assert calls[0]["url"].startswith("https://my-proxy.example/v1")
        assert calls[0]["headers"]["Authorization"] == "Bearer client-key"

    def test_bad_scheme_base_url_rejected(self, monkeypatch, tmp_path):
        """scheme 只允许 http/https，其余回退默认."""
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")

        for bad in ("ftp://evil.example", "javascript:alert(1)", "not a url", "http://"):
            provider = OpenAIProvider(
                credentials={"api_key": "k", "base_url": bad}
            )
            assert provider.base_url == "https://api.openai.com/v1", bad

    def test_valid_client_base_url_accepted(self):
        provider = OpenAIProvider(
            credentials={"api_key": "k", "base_url": "http://192.168.1.5:9000/v1"}
        )
        assert provider.base_url == "http://192.168.1.5:9000/v1"

    def test_no_env_key_allows_client_base_url(self, monkeypatch):
        """无 env Key 的 provider（如 sdwebui）不受互斥限制."""
        monkeypatch.setattr(settings, "sdwebui_base_url", "http://127.0.0.1:7860")
        provider = SDWebUIProvider(
            credentials={"base_url": "http://127.0.0.1:7861"}
        )
        assert provider.base_url == "http://127.0.0.1:7861"


# ---------------------------------------------------------------------------
# 1.2 DashScope 凭据链路: 提交 + 轮询同一 Key
# ---------------------------------------------------------------------------

class TestDashscopeCredentials:
    def _patch(self, monkeypatch, submit, polls, downloads):
        import app.services.providers.dashscope_provider as mod

        def fake_post(url, json=None, headers=None, timeout=None):
            submit.append({"url": url, "headers": headers})
            return _FakeResponse(json_data={"output": {"task_id": "task-123"}})

        def fake_get(url, headers=None, timeout=None):
            polls.append({"url": url, "headers": headers})
            return _FakeResponse(
                json_data={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [{"url": "http://cdn.example/img.png"}],
                    }
                }
            )

        class _FakeClient:
            def __init__(self, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                downloads.append(url)
                return _FakeResponse(content=b"png-bytes")

        monkeypatch.setattr(
            mod, "httpx",
            types.SimpleNamespace(post=fake_post, get=fake_get, Client=_FakeClient),
        )

    def test_submit_and_poll_use_client_key(self, monkeypatch, tmp_path):
        """前端传入的 Key 必须同时用于提交与轮询（回归 1.2）."""
        monkeypatch.setattr(settings, "dashscope_api_key", "env-key-should-not-be-used")
        monkeypatch.setattr(settings, "output_dir", tmp_path)

        submit: list = []
        polls: list = []
        downloads: list = []
        self._patch(monkeypatch, submit, polls, downloads)

        provider = DashscopeProvider(credentials={"api_key": "client-key"})
        assert provider.available()
        images = provider.generate("a harbor", negative_prompt="", n=1)

        assert len(submit) == 1
        assert len(polls) == 1
        assert submit[0]["headers"]["Authorization"] == "Bearer client-key"
        assert polls[0]["headers"]["Authorization"] == "Bearer client-key"
        assert "task-123" in polls[0]["url"]
        # 走统一 base_url（1.6）
        assert submit[0]["url"].startswith("https://dashscope.aliyuncs.com/api/v1")
        assert polls[0]["url"].startswith("https://dashscope.aliyuncs.com/api/v1")
        # 图片落盘
        assert len(images) == 1
        assert images[0].url.startswith("/files/")
        assert (tmp_path / images[0].url.split("/")[-1]).read_bytes() == b"png-bytes"

    def test_env_key_used_when_no_client_key(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "dashscope_api_key", "env-key")
        monkeypatch.setattr(settings, "output_dir", tmp_path)

        submit: list = []
        polls: list = []
        downloads: list = []
        self._patch(monkeypatch, submit, polls, downloads)

        provider = DashscopeProvider()
        provider.generate("a harbor", negative_prompt="", n=1)

        assert submit[0]["headers"]["Authorization"] == "Bearer env-key"
        assert polls[0]["headers"]["Authorization"] == "Bearer env-key"


# ---------------------------------------------------------------------------
# 1.3 / 1.4 pollinations: notes + 确定性 seed
# ---------------------------------------------------------------------------

class TestPollinations:
    def _patch(self, monkeypatch, urls):
        import app.services.providers.pollinations_provider as mod

        class _FakeClient:
            def __init__(self, timeout=None, transport=None):
                # 1.3: 幂等 GET 应带重试 transport
                assert isinstance(transport, httpx.HTTPTransport)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                urls.append(url)
                return _FakeResponse(content=b"jpg-bytes")

        monkeypatch.setattr(mod, "httpx", types.SimpleNamespace(
            Client=_FakeClient, HTTPTransport=httpx.HTTPTransport,
        ))

    def test_seed_is_md5_deterministic(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        prompt = "a quiet harbor"
        expected = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 1000000

        urls1: list = []
        self._patch(monkeypatch, urls1)
        img = PollinationsProvider().generate(prompt, n=1)[0]
        assert img.seed == expected
        assert f"seed={expected}" in urls1[0]

    def test_seed_same_across_instances_and_n_offsets(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        prompt = "a quiet harbor"
        expected = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % 1000000

        urls: list = []
        self._patch(monkeypatch, urls)
        p1 = PollinationsProvider().generate(prompt, n=2)
        p2 = PollinationsProvider().generate(prompt, n=2)
        # 跨实例一致（不依赖 PYTHONHASHSEED），n 张图 seed 递增
        assert [i.seed for i in p1] == [expected, expected + 1]
        assert [i.seed for i in p2] == [expected, expected + 1]

    def test_negative_prompt_note(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "output_dir", tmp_path)
        urls: list = []
        self._patch(monkeypatch, urls)
        provider = PollinationsProvider()
        provider.generate("a harbor", negative_prompt="blurry", n=1)
        assert any("负面提示词" in n for n in provider.notes)


# ---------------------------------------------------------------------------
# 1.5 sdwebui available() TTL 缓存
# ---------------------------------------------------------------------------

class TestSDWebUIAvailabilityCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _AVAILABILITY_CACHE.clear()
        yield
        _AVAILABILITY_CACHE.clear()

    def _patch(self, monkeypatch, counter):
        import app.services.providers.sdwebui_provider as mod

        def fake_get(url, timeout=None):
            counter.append(url)
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(mod, "httpx", types.SimpleNamespace(get=fake_get))

    def test_available_cached_within_ttl(self, monkeypatch):
        counter: list = []
        self._patch(monkeypatch, counter)
        provider = SDWebUIProvider()
        assert provider.available() is True
        assert provider.available() is True
        assert len(counter) == 1  # 第二次命中 30s TTL 缓存

    def test_cache_expires_after_ttl(self, monkeypatch):
        counter: list = []
        self._patch(monkeypatch, counter)
        provider = SDWebUIProvider()
        assert provider.available() is True
        # 手动让缓存过期
        _AVAILABILITY_CACHE[provider.base_url.rstrip("/")] = (
            time.monotonic() - 60.0, True,
        )
        assert provider.available() is True
        assert len(counter) == 2

    def test_failure_also_cached(self, monkeypatch):
        import app.services.providers.sdwebui_provider as mod

        counter: list = []

        def fake_get(url, timeout=None):
            counter.append(url)
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(mod, "httpx", types.SimpleNamespace(get=fake_get))
        provider = SDWebUIProvider()
        assert provider.available() is False
        assert provider.available() is False
        assert len(counter) == 1


# ---------------------------------------------------------------------------
# 1.7 zhipu: 下载失败显式抛错
# ---------------------------------------------------------------------------

class TestZhipuDownloadFailure:
    def test_download_failure_raises(self, monkeypatch, tmp_path):
        import app.services.providers.zhipu_provider as mod

        monkeypatch.setattr(settings, "zhipu_api_key", "k")
        monkeypatch.setattr(settings, "output_dir", tmp_path)

        def fake_post(url, json=None, headers=None, timeout=None):
            return _FakeResponse(
                json_data={"data": [{"url": "http://cdn.example/expiring.png"}]}
            )

        def fake_get(url, timeout=None):
            return _FakeResponse(status_code=403)

        monkeypatch.setattr(
            mod, "httpx", types.SimpleNamespace(post=fake_post, get=fake_get)
        )

        provider = ZhipuProvider(credentials={"api_key": "k"})
        with pytest.raises(httpx.HTTPStatusError):
            provider.generate("a harbor", negative_prompt="", n=1)

    def test_negative_prompt_note(self, monkeypatch, tmp_path):
        import app.services.providers.openai_provider as openai_mod

        monkeypatch.setattr(settings, "output_dir", tmp_path)

        def fake_post(url, json=None, headers=None, timeout=None):
            return _FakeResponse(json_data={"data": [{"b64_json": _b64(b"x")}]})

        monkeypatch.setattr(
            openai_mod, "httpx", types.SimpleNamespace(post=fake_post)
        )
        provider = OpenAIProvider(credentials={"api_key": "k"})
        provider.generate("a harbor", negative_prompt="blurry", n=1)
        assert any("负面提示词" in n for n in provider.notes)


# ---------------------------------------------------------------------------
# 5.3 响应模型不再暴露服务器本地路径
# ---------------------------------------------------------------------------

def test_generated_image_schema_has_no_local_path():
    assert "local_path" not in GeneratedImage.model_fields
