"""Pollinations.ai provider — free text-to-image, no API key required.

Docs: https://pollinations.ai
The legacy image endpoint works without registration:
  GET https://image.pollinations.ai/prompt/{prompt}?width=W&height=H&model=flux&nologo=true
Returns the image bytes directly.
"""
from __future__ import annotations

import hashlib
from urllib.parse import quote

import httpx
from typing import List

from .base import ImageProvider
from ...config import settings
from ...schemas import GeneratedImage


class PollinationsProvider(ImageProvider):
    name = "pollinations"
    display_name = "Pollinations.ai（免费无需Key）"
    description = "免费文生图，基于 Flux 模型，无需 API Key 即可使用"
    is_free = True
    supported_sizes = ["1024x1024", "1024x1792", "1792x1024", "768x768", "512x512"]

    def available(self) -> bool:
        return True  # always available, no key needed

    def _generate(self, prompt, negative_prompt, size, n):
        w, h = size.lower().split("x")
        # Deterministic seed (md5) so the same prompt is reproducible
        # across process restarts; computed once per request.
        base_seed = int(hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8], 16) % 1000000
        self.notes.append("该模型不支持负面提示词，负面提示词设置已被忽略")
        images: List[GeneratedImage] = []

        # The prompt endpoint is an idempotent GET: retry transient
        # connection failures a couple of times via httpx's transport.
        with httpx.Client(
            timeout=self.timeout,
            transport=httpx.HTTPTransport(retries=2),
        ) as client:
            for i in range(n):
                seed = base_seed + i
                url = (
                    f"https://image.pollinations.ai/prompt/{quote(prompt)}"
                    f"?width={w}&height={h}&model=flux&nologo=true&seed={seed}"
                )
                resp = client.get(url)
                resp.raise_for_status()
                path = self.save_image_bytes(resp.content, ext="jpg")
                images.append(
                    GeneratedImage(
                        url=self.file_url(path),
                        provider=self.name,
                        revised_prompt=prompt,
                        seed=seed,
                    )
                )
        return images
