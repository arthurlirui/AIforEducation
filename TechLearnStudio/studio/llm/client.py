"""OpenAI-compatible LLM client with multi-provider fallback.

Providers (priority order):
  1. OpenAI (env OPENAI_API_KEY)
  2. 智谱 GLM (env ZHIPU_API_KEY)
  3. Pollinations free (no key, https://text.pollinations.ai)

When no API key is set and Pollinations is unreachable, the client is
"unavailable" and callers must fall back to rule-based templates.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class LLMResponse:
    text: str
    provider: str
    ok: bool


class LLMClient:
    """Thin OpenAI-compatible chat completion client with fallback."""

    def __init__(self) -> None:
        self._providers = self._build_providers()

    def _build_providers(self) -> list[dict]:
        providers: list[dict] = []
        # OpenAI
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            providers.append({
                "name": "openai",
                "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "api_key": key,
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            })
        # 智谱 GLM
        zkey = os.environ.get("ZHIPU_API_KEY", "")
        if zkey:
            providers.append({
                "name": "zhipu",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key": zkey,
                "model": os.environ.get("ZHIPU_MODEL", "glm-4-flash"),
            })
        # Pollinations free (no key needed)
        providers.append({
            "name": "pollinations",
            "base_url": "https://text.pollinations.ai/openai",
            "api_key": "dummy",
            "model": "openai",
        })
        return providers

    @property
    def available(self) -> bool:
        return len(self._providers) > 0

    def chat(self, system: str, user: str, *, json_mode: bool = False, timeout: float = 30) -> LLMResponse:
        """Call the first available provider. Returns LLMResponse with ok=False on all failures."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for p in self._providers:
            try:
                r = httpx.post(
                    f"{p['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {p['api_key']}"},
                    json={
                        "model": p["model"],
                        "messages": messages,
                        "temperature": 0.7,
                        **({"response_format": {"type": "json_object"}} if json_mode else {}),
                    },
                    timeout=timeout,
                )
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                return LLMResponse(text=text, provider=p["name"], ok=True)
            except Exception:
                continue
        return LLMResponse(text="", provider="none", ok=False)

    def chat_json(self, system: str, user: str, timeout: float = 30) -> dict | None:
        """Call LLM expecting JSON output. Returns parsed dict or None on failure."""
        resp = self.chat(system, user, json_mode=True, timeout=timeout)
        if not resp.ok:
            return None
        try:
            return json.loads(resp.text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            t = resp.text
            start = t.find("{")
            end = t.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(t[start:end])
                except json.JSONDecodeError:
                    pass
            return None


# 单例
_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
