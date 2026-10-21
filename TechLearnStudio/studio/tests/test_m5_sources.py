"""M5-M6 测试：内容源 adapter。"""
from __future__ import annotations

from crawler import get_source, list_sources, REGISTRY
from composer import compose


def test_registry_has_all_sources():
    assert len(REGISTRY) == 7
    for sid in ["python_docs", "rust_docs", "go_docs", "ts_docs",
                "course_signal", "course_wireless", "course_llm"]:
        assert sid in REGISTRY


def test_list_sources():
    sources = list_sources()
    assert len(sources) == 7
    ids = [s["id"] for s in sources]
    assert "python_docs" in ids


def test_python_source_sections():
    src = get_source("python_docs")
    sections = src.get_sections()
    assert len(sections) == 2
    titles = [s.title for s in sections]
    assert "Python 异步编程" in titles
    assert "Python 装饰器" in titles
    # 每节有代码
    for s in sections:
        assert len(s.code_blocks) > 0


def test_rust_source_with_anim():
    src = get_source("rust_docs")
    sections = src.get_sections()
    own = next(s for s in sections if "所有权" in s.title)
    assert own.anim_kind == "ownership_move"


def test_go_source():
    src = get_source("go_docs")
    sections = src.get_sections()
    assert len(sections) == 2
    assert any("goroutine" in s.title for s in sections)
    assert any("接口" in s.title for s in sections)


def test_ts_source():
    src = get_source("ts_docs")
    sections = src.get_sections()
    assert len(sections) == 2
    assert any("类型系统" in s.title for s in sections)
    assert any("泛型" in s.title for s in sections)


def test_signal_source_with_formula_and_anim():
    src = get_source("course_signal")
    sections = src.get_sections()
    conv = next(s for s in sections if "卷积" in s.title)
    assert conv.formula  # 有公式
    assert conv.anim_kind == "convolution"
    fft = next(s for s in sections if "傅里叶" in s.title)
    assert fft.formula


def test_wireless_source():
    src = get_source("course_wireless")
    sections = src.get_sections()
    ofdm = next(s for s in sections if "OFDM" in s.title)
    assert ofdm.formula
    assert ofdm.anim_kind == "ofdm_subcarriers"
    ch = next(s for s in sections if "信道" in s.title)
    assert ch.formula


def test_llm_source_with_attention_anim():
    src = get_source("course_llm")
    sections = src.get_sections()
    attn = next(s for s in sections if "注意力" in s.title)
    assert attn.formula
    assert attn.anim_kind == "attention_flow"
    transformer = next(s for s in sections if "Transformer" in s.title)
    assert len(transformer.code_blocks) > 0


def test_compose_from_each_source():
    """每个源的每节都能 compose 成帧。"""
    for sid in REGISTRY:
        src = get_source(sid)
        for section in src.get_sections():
            frames = compose(section)
            assert len(frames) >= 4
            assert frames[0]["layout"] == "title"


def test_fingerprint_deterministic():
    src = get_source("python_docs")
    docs1 = src.fetch()
    docs2 = src.fetch()
    assert src.fingerprint(docs1) == src.fingerprint(docs2)


def test_get_source_unknown():
    assert get_source("nonexistent") is None
