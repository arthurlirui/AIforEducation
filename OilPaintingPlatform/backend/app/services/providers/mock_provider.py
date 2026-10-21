"""Mock provider – generates a simple SVG placeholder so the platform is
demoable without any API key. Always available."""
from __future__ import annotations

import base64
import hashlib
import textwrap
from typing import List

from .base import ImageProvider
from ...schemas import GeneratedImage


_PALETTE = [
    "#e8b04b", "#c0392b", "#2c3e50", "#27ae60",
    "#8e44ad", "#16a085", "#d35400", "#34495e",
]


def _svg(prompt: str, style_name: str, seed: int) -> bytes:
    # Deterministic color from prompt
    digest = hashlib.md5(prompt.encode("utf-8")).hexdigest()
    c1 = _PALETTE[int(digest[0], 16) % len(_PALETTE)]
    c2 = _PALETTE[int(digest[1], 16) % len(_PALETTE)]
    c3 = _PALETTE[int(digest[2], 16) % len(_PALETTE)]

    # Wrap prompt for display
    wrapped = textwrap.fill(prompt, width=40)
    lines = wrapped.splitlines()[:6]

    text_blocks = "".join(
        f'<text x="40" y="{520 + i*32}" font-family="serif" font-size="22" fill="#222">{_escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{c1}"/>
      <stop offset="50%" stop-color="{c2}"/>
      <stop offset="100%" stop-color="{c3}"/>
    </linearGradient>
  </defs>
  <rect width="1024" height="1024" fill="url(#g)"/>
  <circle cx="760" cy="240" r="120" fill="#fff" opacity="0.25"/>
  <circle cx="220" cy="780" r="180" fill="#000" opacity="0.18"/>
  <rect x="40" y="40" width="944" height="944" fill="none" stroke="#fff" stroke-width="6" opacity="0.5"/>
  <text x="40" y="100" font-family="serif" font-size="36" fill="#fff" font-weight="bold">OilPaintingPlatform · Mock</text>
  <text x="40" y="150" font-family="serif" font-size="28" fill="#fff">Style: {_escape(style_name)}</text>
  <text x="40" y="190" font-family="serif" font-size="22" fill="#fff">Seed: {seed}</text>
  <rect x="20" y="480" width="984" height="280" fill="#fff" opacity="0.85"/>
  {text_blocks}
</svg>"""
    return svg.encode("utf-8")


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class MockProvider(ImageProvider):
    name = "mock"
    display_name = "Mock（内置占位图）"
    description = "无需配置，生成 SVG 占位图用于演示"
    is_free = True

    def available(self) -> bool:
        return True

    def _generate(self, prompt, negative_prompt, size, n):
        images: List[GeneratedImage] = []
        for i in range(n):
            seed = abs(hash(prompt)) % 100000 + i
            svg = _svg(prompt, "Mock Style", seed)
            path = self.save_image_bytes(svg, ext="svg")
            images.append(
                GeneratedImage(
                    url=self.file_url(path),
                    provider=self.name,
                    revised_prompt=prompt,
                    seed=seed,
                    local_path=str(path),
                )
            )
        return images
