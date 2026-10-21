"""M3 测试：LLM 接入 Composer。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from composer import compose, compose_with_llm, Section
from composer.samples import PYTHON_ASYNCIO
from llm.client import LLMClient


def test_llm_unavailable_falls_back_to_rules():
    """无 API key 时 LLMClient.available 可能为 True（pollinations），但 chat 失败也应降级。"""
    # 用 mock 强制 LLM 不可用
    mock_llm = MagicMock()
    mock_llm.available = False
    frames = compose_with_llm(PYTHON_ASYNCIO, llm=mock_llm)
    # 应该降级到规则模板，产出和 compose() 一样
    rule_frames = compose(PYTHON_ASYNCIO)
    assert len(frames) == len(rule_frames)
    assert frames[0]["layout"] == "title"


def test_llm_enhances_outline():
    """mock LLM 返回大纲 + 帧内容，验证 compose_with_llm 使用 LLM 输出。"""
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.chat_json.side_effect = [
        # 第一次调用：大纲
        {"steps": ["为什么需要异步", "asyncio 事件循环", "最小示例", "常见陷阱", "小结"]},
        # 后续调用：每帧内容
        {"blocks": [{"type": "text", "md": "## 为什么需要异步\n阻塞 IO 浪费资源。", "fragment": 0}],
         "notes": "强调 IO 等待的浪费。"},
        {"blocks": [{"type": "text", "md": "## 事件循环\n单线程并发调度。", "fragment": 0},
                    {"type": "formula", "tex": r"\text{loop} = \text{poll} + \text{dispatch}", "fragment": 1}],
         "notes": "事件循环是核心。"},
        {"blocks": [{"type": "code", "lang": "python", "src": "import asyncio\nasyncio.run(print('hi'))",
                     "runnable": True, "fragment": 0}],
         "notes": "运行看看。"},
        {"blocks": [{"type": "callout", "kind": "pitfall", "md": "忘记 await。", "fragment": 0}],
         "notes": ""},
        {"blocks": [{"type": "text", "md": "## 小结\n- async/await\n- 事件循环\n- 不要阻塞", "fragment": 0}],
         "notes": "回顾。"},
    ]
    frames = compose_with_llm(PYTHON_ASYNCIO, llm=mock_llm)

    # 封面 + 5 个 LLM 步骤 = 6 帧
    assert len(frames) == 6
    assert frames[0]["layout"] == "title"
    assert frames[1]["title"] == "为什么需要异步"
    assert frames[2]["title"] == "asyncio 事件循环"

    # 验证 LLM 生成的 block 进入了 blocks_json
    frame1_blocks = json.loads(frames[1]["blocks_json"])
    assert frame1_blocks[0]["md"] == "## 为什么需要异步\n阻塞 IO 浪费资源。"

    # 验证 notes
    assert frames[1]["notes"] == "强调 IO 等待的浪费。"

    # 确认 chat_json 被调用了 6 次（1 大纲 + 5 帧）
    assert mock_llm.chat_json.call_count == 6


def test_llm_frame_failure_uses_rule_fallback_block():
    """LLM 对某帧返回 None 时，该帧用规则块降级。"""
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.chat_json.side_effect = [
        {"steps": ["动机", "示例"]},
        {"blocks": [{"type": "text", "md": "## 动机", "fragment": 0}], "notes": ""},
        None,  # 第二帧 LLM 失败
    ]
    frames = compose_with_llm(PYTHON_ASYNCIO, llm=mock_llm)
    assert len(frames) == 3  # 封面 + 2 步骤
    # 第二帧（示例）LLM 失败但有规则降级块
    blocks = json.loads(frames[2]["blocks_json"])
    assert len(blocks) > 0


def test_llm_client_providers():
    """验证 LLMClient 至少有 pollinations provider。"""
    client = LLMClient()
    assert client.available
    names = [p["name"] for p in client._providers]
    assert "pollinations" in names
