"""智谱 AI CogView text-to-image provider.

Docs: https://open.bigmodel.cn/dev/api/text2image
The API is synchronous and returns base64-encoded images.
"""
from __future__ import annotations

import base64

import httpx
from typing import List

from .base import ImageProvider
from ...config import settings
from ...schemas import GeneratedImage


class ZhipuProvider(ImageProvider):
    name = "zhipu"
    display_name = "智谱 CogView"
    description = "智谱 AI CogView 文生图，CogView-3-Flash 永久免费"
    needs_api_key = True
    needs_base_url = True
    is_free = True
    default_base_url = "https://open.bigmodel.cn/api/paas/v4"

    def _env_api_key(self) -> str:
        return settings.zhipu_api_key

    def _env_base_url(self) -> str:
        return settings.zhipu_base_url

    def available(self) -> bool:
        return bool(self.api_key)

    def _generate(self, prompt, negative_prompt, size, n):
        url = f"{self.base_url.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.zhipu_image_model,
            "prompt": prompt,
            "size": size,
            "n": n,
        }
        resp = httpx.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()

        images: List[GeneratedImage] = []
        for item in data.get("data", []):
            b64 = item.get("b64_json")
            url_val = item.get("url")
            if b64:
                raw = base64.b64decode(b64)
                path = self.save_image_bytes(raw, ext="png")
                images.append(
                    GeneratedImage(
                        url=self.file_url(path),
                        provider=self.name,
                        revised_prompt=prompt,
                        local_path=str(path),
                    )
                )
            elif url_val:
                # Download so the file is served locally
                try:
                    r = httpx.get(url_val, timeout=60)
                    r.raise_for_status()
                    path = self.save_image_bytes(r.content, ext="png")
                    images.append(
                        GeneratedImage(
                            url=self.file_url(path),
                            provider=self.name,
                            revised_prompt=prompt,
                            local_path=str(path),
                        )
                    )
                except Exception:
                    images.append(
                        GeneratedImage(
                            url=url_val, provider=self.name, revised_prompt=prompt
                        )
                    )
        return images
