"""剧本 schema 与 generator 的单元测试（mock LLM，不依赖真实 API）。"""
from __future__ import annotations

import json

import pytest

from oilpaint.screenplay.generator import _repair_shot_numbering
from oilpaint.screenplay.schemas import Scene, Script, Shot


def test_shot_validation_ok():
    s = Shot(index=1, scene_index=1, prompt="a quiet harbor at dawn")
    assert s.camera_motion == "static"
    assert s.i2v_model == "ltx"
    assert s.duration_sec == 3.0


def test_shot_invalid_motion():
    with pytest.raises(ValueError):
        Shot(index=1, scene_index=1, prompt="x", camera_motion="spin")


def test_shot_invalid_model():
    with pytest.raises(ValueError):
        Shot(index=1, scene_index=1, prompt="x", i2v_model="sora")


def test_script_recompute_duration():
    sc = Script(
        title="t", style="impressionism",
        scenes=[
            Scene(index=1, shots=[Shot(index=1, scene_index=1, prompt="a", duration_sec=2.0)]),
            Scene(index=2, shots=[Shot(index=2, scene_index=2, prompt="b", duration_sec=3.5)]),
        ],
    )
    sc.recompute_duration()
    assert sc.total_duration_sec == 5.5
    assert len(sc.shots) == 2


def test_repair_shot_numbering():
    raw = {
        "scenes": [
            {"index": 1, "shots": [{"prompt": "a"}, {"prompt": "b"}]},
            {"index": 2, "shots": [{"prompt": "c"}]},
        ]
    }
    fixed = _repair_shot_numbering(raw)
    idxs = [sh["index"] for sc in fixed["scenes"] for sh in sc["shots"]]
    assert idxs == [1, 2, 3]
    assert fixed["scenes"][1]["shots"][0]["scene_index"] == 2


class _MockLLM:
    """返回固定剧本 JSON 的假客户端。"""

    def __init__(self, payload: dict):
        self.payload = payload

    async def chat_json(self, messages, **kw):
        return self.payload, json.dumps(self.payload, ensure_ascii=False)


class _MockSettings:
    """最小 settings 替身。"""
    aspect = "9:16"
    target_duration_sec = 15

    def style(self, key=None):
        from oilpaint.config import StylePreset
        return StylePreset(
            key="impressionism", name="印象派",
            painters=["Claude Monet"],
            positive_prefix="impressionism", negative="bad",
            sampler="dpmpp_2m", scheduler="karras", cfg=7.0, steps=30, bgm_mood="gentle",
        )


@pytest.mark.asyncio
async def test_generate_script_from_mock():
    from oilpaint.screenplay.generator import generate_script

    payload = {
        "title": "晨曦归舟",
        "synopsis": "渔夫在晨光中归港",
        "scenes": [
            {"index": 1, "title": "出海", "summary": "清晨",
             "shots": [
                 {"prompt": "harbor at dawn, boats, mist", "painter": "Claude Monet",
                  "camera_motion": "pan_right", "duration_sec": 3, "i2v_model": "ltx",
                  "narration": "晨光初现", "mood": "calm"},
             ]},
        ],
    }
    client = _MockLLM(payload)
    script, info = await generate_script(client, _MockSettings(), "渔夫归港")
    assert script is not None
    assert script.title == "晨曦归舟"
    assert len(script.shots) == 1
    assert script.shots[0].painter == "Claude Monet"
    assert script.total_duration_sec == 3.0


@pytest.mark.asyncio
async def test_generate_script_parse_retry():
    from oilpaint.screenplay.generator import generate_script

    # 第一轮返回非法 JSON 文本，第二轮返回合法 payload
    class _Seq:
        def __init__(self):
            self.n = 0

        async def chat_json(self, messages, **kw):
            self.n += 1
            if self.n == 1:
                return None, "not json"
            return payload, json.dumps(payload, ensure_ascii=False)

    payload = {
        "title": "夜读", "synopsis": "学者夜读",
        "scenes": [{"index": 1, "shots": [
            {"prompt": "scholar reading by candle", "camera_motion": "zoom_in",
             "duration_sec": 4, "i2v_model": "wan", "narration": "", "mood": "solemn"},
        ]}],
    }
    script, info = await generate_script(_Seq(), _MockSettings(), "夜读")
    assert script is not None
    assert script.shots[0].i2v_model == "wan"
