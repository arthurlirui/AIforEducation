"""OpenAI 兼容 LLM 客户端 —— 借鉴 story-studio 的重试/超时模式。

支持：
- /chat/completions（含 reasoning 字段提取）
- JSON 模式（response_format=json_object）
- 429/5xx 指数退避重试
- 超时降级
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 6
BASE_DELAY = 3.0
MAX_DELAY = 60.0
DEFAULT_TIMEOUT = 300.0

LLM_ERROR_PREFIX = "[LLM API error"


class LLMClient:
    """OpenAI 兼容 API 客户端。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.last_usage: dict[str, int] | None = None
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        json_mode: bool = False,
        retries: int = MAX_RETRIES,
    ) -> str:
        """调用 chat/completions，返回 content 字符串。失败返回以 LLM_ERROR_PREFIX 开头的哨兵串。"""
        if not self.api_key:
            return f"{LLM_ERROR_PREFIX} missing api_key]"

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        delay = BASE_DELAY
        last_err = ""
        for attempt in range(1, retries + 1):
            try:
                resp = await self._get_http().post(url, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning("LLM 重试 %d/%d: %s", attempt, retries, last_err)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, MAX_DELAY)
                    continue
                resp.raise_for_status()
                data = resp.json()
                self.last_usage = data.get("usage")
                choice = data["choices"][0]
                msg = choice.get("message", {})
                content = msg.get("content") or ""
                return content
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
                logger.warning("LLM 异常 %d/%d: %s", attempt, retries, last_err)
                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, MAX_DELAY)
        return f"{LLM_ERROR_PREFIX} {last_err}]"

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        retries: int = MAX_RETRIES,
    ) -> tuple[dict[str, Any] | None, str]:
        """请求 JSON 模式并解析为 dict。返回 (parsed|None, raw_or_error)。"""
        raw = await self.chat(
            messages,
            model=model,
            temperature=temperature,
            json_mode=True,
            retries=retries,
        )
        if raw.startswith(LLM_ERROR_PREFIX):
            return None, raw
        # 容错：模型可能把 JSON 包在 ```json ... ``` 里
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        try:
            return json.loads(text), raw
        except json.JSONDecodeError as e:
            return None, f"[JSON parse error: {e}] raw={raw[:300]}"
