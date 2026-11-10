"""Stable Diffusion WebUI (Automatic1111) provider via the /sdapi/v1/txt2img
HTTP endpoint. Useful for a fully local, free, self-hosted backend."""
from __future__ import annotations

import base64
import time

import httpx
from typing import List

from .base import ImageProvider
from ...config import settings
from ...schemas import GeneratedImage


def _parse_size(size: str) -> tuple[int, int]:
    w, h = size.lower().split("x")
    # SD1.5 prefers multiples of 8; round to nearest 8
    return (int(w) // 8) * 8, (int(h) // 8) * 8


# Module-level TTL cache for availability probes so a stopped SD WebUI
# does not cost every generate request a 5s TCP timeout.
_AVAILABILITY_CACHE: dict[str, tuple[float, bool]] = {}
_AVAILABILITY_TTL = 30.0  # seconds


class SDWebUIProvider(ImageProvider):
    name = "sdwebui"
    display_name = "Stable Diffusion WebUI"
    description = "本地 Automatic1111 SD WebUI，免费自托管"
    needs_base_url = True
    is_free = True
    default_base_url = "http://127.0.0.1:7860"
    supported_sizes = ["512x512", "768x768", "1024x1024", "1024x1792", "1792x1024"]

    def _env_base_url(self) -> str:
        return settings.sdwebui_base_url

    def available(self) -> bool:
        key = self.base_url.rstrip("/")
        now = time.monotonic()
        cached = _AVAILABILITY_CACHE.get(key)
        if cached is not None and now - cached[0] < _AVAILABILITY_TTL:
            return cached[1]
        try:
            r = httpx.get(f"{key}/sdapi/v1/options", timeout=5)
            ok = r.status_code == 200
        except Exception:
            ok = False
        _AVAILABILITY_CACHE[key] = (now, ok)
        return ok

    def _generate(self, prompt, negative_prompt, size, n):
        w, h = _parse_size(size)
        url = f"{self.base_url.rstrip('/')}/sdapi/v1/txt2img"
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": w,
            "height": h,
            "batch_size": n,
            "steps": settings.sdwebui_steps,
            "sampler_name": settings.sdwebui_sampler,
        }
        resp = httpx.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        images: List[GeneratedImage] = []
        for i, b64 in enumerate(data.get("images", [])):
            raw = base64.b64decode(b64)
            path = self.save_image_bytes(raw, ext="png")
            seed = data.get("info", {}).get("seed", i)
            images.append(
                GeneratedImage(
                    url=self.file_url(path),
                    provider=self.name,
                    revised_prompt=prompt,
                    seed=seed,
                )
            )
        return images
