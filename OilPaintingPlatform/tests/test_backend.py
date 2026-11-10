"""OilPaintingPlatform 后端单元测试.

覆盖三个核心组件（全部离线可跑, 不需要任何 API Key）:
1. prompt_builder  — 提示词合成引擎 (风格关键词/媒介提示/艺术家/负面词)
2. ProviderRegistry — 注册表 + get_provider 的 mock 回退逻辑
3. MockProvider     — SVG 占位图生成与落盘

（路由层 / provider 凭据链路 / gallery 并发等测试见 test_api.py、
  test_providers.py、test_gallery.py。sys.path 由根目录 conftest.py 设置。）
"""
from __future__ import annotations

import pytest

from app.schemas import GeneratedImage, StylePreset
from app.services.prompt_builder import (
    compose_negative_prompt,
    compose_prompt,
    get_style,
    list_styles,
)
from app.services.prompt_service import list_prompts
from app.services.providers import (
    ImageProvider,
    ProviderRegistry,
    get_provider,
)
from app.services.providers.mock_provider import MockProvider, _svg


@pytest.fixture(scope="module")
def impressionism() -> StylePreset:
    style = get_style("impressionism")
    assert style is not None, "styles.json 应含 impressionism"
    return style


# ---------------------------------------------------------------------------
# prompt_builder
# ---------------------------------------------------------------------------

class TestStylesData:
    def test_list_styles_loads_all(self):
        styles = list_styles()
        assert len(styles) >= 12, "styles.json 至少 12 种风格"

    def test_get_style_found_and_missing(self):
        assert get_style("impressionism") is not None
        assert get_style("no-such-style") is None

    def test_prompt_recommended_styles_exist(self):
        """prompts.json 的 recommended_style 必须都能在 styles.json 中找到，
        否则前端点击模板后不会切换风格（推荐 badge 静默消失）。"""
        style_ids = {s.id for s in list_styles()}
        prompts = list_prompts()
        assert len(prompts) >= 20, "prompts.json 至少 20 条模板"
        for p in prompts:
            assert p.recommended_style in style_ids, (
                f"模板 {p.id} 的 recommended_style '{p.recommended_style}' "
                "不在 styles.json 中"
            )


class TestComposePrompt:
    def test_appends_style_keywords(self, impressionism):
        out = compose_prompt("a quiet harbor", impressionism)
        assert out.startswith("a quiet harbor")
        for kw in impressionism.prompt_keywords:
            assert kw in out

    def test_medium_hint_added_when_missing(self, impressionism):
        out = compose_prompt("a quiet harbor", impressionism)
        assert "oil painting" in out

    def test_medium_hint_not_duplicated(self, impressionism):
        out = compose_prompt("an oil painting of a harbor", impressionism)
        # 用户已提 oil painting → 不追加媒介提示短语 "oil painting on canvas"
        assert "oil painting on canvas" not in out

    def test_medium_hint_not_duplicated_by_style_keywords(self, impressionism):
        """风格关键词已含 "oil painting" 时不再追加媒介提示（3.1）."""
        out = compose_prompt("a quiet harbor", impressionism)
        assert "oil painting" in out  # 来自风格关键词
        assert "oil painting on canvas" not in out
        # 整个合成结果中 "oil painting" 只出现一次
        assert out.count("oil painting") == 1

    def test_chinese_prompt_gets_medium_hint(self, impressionism):
        out = compose_prompt("宁静的港湾", impressionism)
        assert "oil painting" in out

    def test_reference_artists_capped_at_two(self):
        style = StylePreset(
            id="t", name="T", name_en="T", era="T", description="",
            reference_artists=["A", "B", "C", "D"],
        )
        out = compose_prompt("x", style)
        assert "in the manner of A / B" in out
        assert "C" not in out.split("manner of")[1]

    def test_extra_keywords_included(self, impressionism):
        out = compose_prompt("harbor", impressionism, extra_keywords=" sunset, calm")
        assert "sunset" in out and "calm" in out

    def test_whitespace_only_parts_dropped(self):
        style = StylePreset(id="t", name="T", name_en="T", era="T", description="")
        out = compose_prompt("  harbor  ", style)
        assert ", , " not in out
        assert out.startswith("harbor")


class TestComposeNegativePrompt:
    def test_base_negative_always_present(self):
        style = StylePreset(id="t", name="T", name_en="T", era="T", description="")
        neg = compose_negative_prompt(style)
        assert "low quality" in neg and "watermark" in neg

    def test_style_negative_keywords_appended(self):
        style = StylePreset(
            id="t", name="T", name_en="T", era="T", description="",
            negative_keywords=["photograph", "3d render"],
        )
        neg = compose_negative_prompt(style)
        assert "photograph" in neg and "3d render" in neg


# ---------------------------------------------------------------------------
# ProviderRegistry / get_provider 回退
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_six_providers_registered(self):
        names = ProviderRegistry.names()
        for expected in ("mock", "pollinations", "openai",
                         "dashscope", "zhipu", "sdwebui"):
            assert expected in names, f"缺少 provider: {expected}"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            ProviderRegistry.get("no-such-provider")

    def test_get_returns_instance_with_credentials(self):
        p = ProviderRegistry.get("mock", credentials={"api_key": "k"})
        assert isinstance(p, ImageProvider)
        assert p.api_key == "k"

    def test_info_lists_all_metadata(self):
        info = ProviderRegistry.info()
        assert len(info) >= 6
        mock_entry = next(i for i in info if i["id"] == "mock")
        assert isinstance(mock_entry["free"], bool)
        assert "name" in mock_entry and "needs_api_key" in mock_entry


class TestGetProviderFallback:
    def test_unknown_name_falls_back_to_mock(self):
        p = get_provider("no-such-provider")
        assert isinstance(p, MockProvider)

    def test_unavailable_provider_falls_back_to_mock(self, monkeypatch):
        """注册表中存在但 available()=False 的 provider 也回退 mock."""
        class _NeverAvailable(MockProvider):
            def available(self) -> bool:
                return False

        ProviderRegistry.register("_never", _NeverAvailable)
        try:
            p = get_provider("_never")
            assert isinstance(p, MockProvider)
            assert not isinstance(p, _NeverAvailable)
        finally:
            del ProviderRegistry._registry["_never"]

    def test_default_none_uses_settings_default(self):
        # settings.default_provider 默认 mock (无 env 时)
        p = get_provider(None)
        assert isinstance(p, ImageProvider)


# ---------------------------------------------------------------------------
# MockProvider 端到端 (离线)
# ---------------------------------------------------------------------------

class TestMockProvider:
    def test_available_always_true(self):
        assert MockProvider().available() is True

    def test_generate_returns_image_record(self, tmp_path, monkeypatch):
        from app.config import Settings
        monkeypatch.setattr("app.config.settings.output_dir", tmp_path)
        provider = MockProvider()
        results = provider.generate(
            "a quiet harbor at sunset", negative_prompt="blurry", n=1)
        assert len(results) == 1
        img = results[0]
        assert isinstance(img, GeneratedImage)
        assert img.url.startswith("/files/")
        path = tmp_path / img.url.split("/")[-1]
        assert path.exists()
        assert path.read_bytes().startswith(b"<?xml")  # SVG

    def test_generate_deterministic_output(self):
        """同一 prompt 生成完全相同的 SVG（md5 决定配色与 seed）."""
        svg1 = _svg("same prompt", "Mock Style", 42)
        svg2 = _svg("same prompt", "Mock Style", 42)
        assert svg1 == svg2

    def test_seed_deterministic_across_instances(self):
        """seed 由 md5 推导，跨进程/跨实例可复现（不依赖 PYTHONHASHSEED）."""
        img1 = MockProvider()._generate("same prompt", "", "1024x1024", 1)[0]
        img2 = MockProvider()._generate("same prompt", "", "1024x1024", 1)[0]
        assert img1.seed == img2.seed
        assert img1.seed is not None
