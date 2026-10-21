"""阿里云通义万相 (DashScope) text-to-image provider.

Docs: https://help.aliyun.com/zh/dashscope/developer-reference/api-details-9
The API is asynchronous: submit → poll task → fetch result URL.
"""
from __future__ import annotations

import time

import httpx
from typing import List

from .base import ImageProvider
from ...config import settings
from ...schemas import GeneratedImage


DASHSCOPE_API = "https://dashscope.aliyuncs.com/api/v1"


class DashscopeProvider(ImageProvider):
    name = "dashscope"
    display_name = "阿里通义万相"
    description = "阿里云 DashScope 通义万相文生图，异步轮询"
    needs_api_key = True
    default_base_url = "https://dashscope.aliyuncs.com/api/v1"

    def _env_api_key(self) -> str:
        return settings.dashscope_api_key

    def available(self) -> bool:
        return bool(self.api_key)

    def _generate(self, prompt, negative_prompt, size, n):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        # wanx-v1 expects size like "1024*1024"
        size_str = size.replace("x", "*")
        payload = {
            "model": settings.dashscope_image_model,
            "input": {"prompt": prompt, "negative_prompt": negative_prompt},
            "parameters": {"size": size_str, "n": n},
        }

        # 1) Submit task
        resp = httpx.post(
            f"{DASHSCOPE_API}/services/aigc/text2image/image-synthesis",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        task = resp.json()
        task_id = task.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"DashScope submit failed: {task}")

        # 2) Poll
        poll_headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            r = httpx.get(
                f"{DASHSCOPE_API}/tasks/{task_id}",
                headers=poll_headers,
                timeout=30,
            )
            r.raise_for_status()
            body = r.json().get("output", {})
            status = body.get("task_status")
            if status == "SUCCEEDED":
                results = body.get("results", [])
                break
            if status == "FAILED":
                raise RuntimeError(f"DashScope task failed: {body}")
            time.sleep(2)
        else:
            raise RuntimeError("DashScope task timed out")

        # 3) Download + persist
        images: List[GeneratedImage] = []
        with httpx.Client(timeout=60) as client:
            for item in results:
                img_url = item.get("url") or item.get("b64_image")
                if img_url and img_url.startswith("http"):
                    r = client.get(img_url)
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
        return images
