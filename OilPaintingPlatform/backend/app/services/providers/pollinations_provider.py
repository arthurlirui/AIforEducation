"""Pollinations.ai provider — free text-to-image, no API key required.

Docs: https://pollinations.ai
The legacy image endpoint works without registration:
  GET https://image.pollinations.ai/prompt/{prompt}?width=W&height=H&model=flux&nologo=true
Returns the image bytes directly.
"""
from __future__ import annotations

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

    def available(self) -> bool:
        return True  # always available, no key needed

    def _generate(self, prompt, negative_prompt, size, n):
        w, h = size.lower().split("x")
        images: List[GeneratedImage] = []

        with httpx.Client(timeout=self.timeout) as client:
            for i in range(n):
                url = (
                    f"https://image.pollinations.ai/prompt/{quote(prompt)}"
                    f"?width={w}&height={h}&model=flux&nologo=true&seed={hash(prompt) % 1000000 + i}"
                )
                resp = client.get(url)
                resp.raise_for_status()
                path = self.save_image_bytes(resp.content, ext="jpg")
                images.append(
                    GeneratedImage(
                        url=self.file_url(path),
                        provider=self.name,
                        revised_prompt=prompt,
                        seed=hash(prompt) % 1000000 + i,
                        local_path=str(path),
                    )
                )
        return images
