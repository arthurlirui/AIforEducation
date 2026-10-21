"""OpenAI DALL·E provider (also compatible with any OpenAI-compatible
image API that supports the /images/generations endpoint)."""
from __future__ import annotations

import base64
import httpx
from typing import List

from .base import ImageProvider
from ...config import settings
from ...schemas import GeneratedImage


class OpenAIProvider(ImageProvider):
    name = "openai"
    display_name = "OpenAI DALL·E 3"
    description = "OpenAI 官方文生图，支持 DALL·E 3"
    needs_api_key = True
    needs_base_url = True
    default_base_url = "https://api.openai.com/v1"

    def _env_api_key(self) -> str:
        return settings.openai_api_key

    def _env_base_url(self) -> str:
        return settings.openai_base_url

    def available(self) -> bool:
        return bool(self.api_key)

    def _generate(self, prompt, negative_prompt, size, n):
        url = f"{self.base_url.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.openai_image_model,
            "prompt": prompt,
            "n": n,
            "size": size,
            "response_format": "b64_json",
        }
        resp = httpx.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()

        images: List[GeneratedImage] = []
        for item in data.get("data", []):
            b64 = item.get("b64_json")
            if b64:
                raw = base64.b64decode(b64)
                path = self.save_image_bytes(raw, ext="png")
                images.append(
                    GeneratedImage(
                        url=self.file_url(path),
                        provider=self.name,
                        revised_prompt=item.get("revised_prompt", prompt),
                        local_path=str(path),
                    )
                )
            elif item.get("url"):
                # Some proxies only return a URL
                images.append(
                    GeneratedImage(
                        url=item["url"],
                        provider=self.name,
                        revised_prompt=item.get("revised_prompt", prompt),
                    )
                )
        return images
