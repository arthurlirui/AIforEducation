"""ComfyUI HTTP 客户端（复用 OilPaintingVideo 的实现模式）。

调用流程：POST /upload/image → POST /prompt → 轮询 GET /history/{id} → GET /view 下载产物。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3.0
DEFAULT_TIMEOUT = 120.0


class ComfyClient:
    def __init__(self, base_url: str, concurrency: int = 1) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = str(uuid.uuid4())
        self._sem = asyncio.Semaphore(concurrency)
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def health(self) -> tuple[bool, str]:
        try:
            r = await self._get_http().get(f"{self.base_url}/system_stats", timeout=10)
            return (r.status_code == 200, "ok" if r.status_code == 200 else f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            return False, f"{type(e).__name__}: {e}"

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/object_info"
        if node_class:
            url += f"/{node_class}"
        r = await self._get_http().get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    async def upload_image(self, image_path: Path) -> dict[str, str]:
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "application/octet-stream")}
            r = await self._get_http().post(f"{self.base_url}/upload/image", files=files, timeout=120)
        r.raise_for_status()
        return r.json()

    async def upload_video(self, video_path: Path) -> dict[str, str]:
        """上传视频文件（ComfyUI /upload/image 也接受非图片）。"""
        with video_path.open("rb") as f:
            files = {"image": (video_path.name, f, "application/octet-stream")}
            r = await self._get_http().post(f"{self.base_url}/upload/image", files=files, timeout=300)
        r.raise_for_status()
        return r.json()

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        r = await self._get_http().post(f"{self.base_url}/prompt", json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"ComfyUI 排队失败: {data['error']}")
        return data["prompt_id"]

    async def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        r = await self._get_http().get(f"{self.base_url}/history/{prompt_id}", timeout=30)
        r.raise_for_status()
        return r.json().get(prompt_id)

    async def download_view(self, filename: str, subfolder: str = "", item_type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": item_type}
        r = await self._get_http().get(f"{self.base_url}/view", params=params, timeout=300)
        r.raise_for_status()
        return r.content

    async def interrupt(self) -> None:
        await self._get_http().post(f"{self.base_url}/interrupt", json={}, timeout=10)

    async def free_memory(self, unload_models: bool = True) -> None:
        await self._get_http().post(
            f"{self.base_url}/free", json={"unload_models": unload_models, "free_memory": True}, timeout=10
        )

    async def run(
        self,
        workflow: dict[str, Any],
        outputs_node: str,
        save_to: Path | None = None,
        timeout: float = 1800,
    ) -> list[Path]:
        async with self._sem:
            prompt_id = await self.queue_prompt(workflow)
            logger.info("ComfyUI 排队 prompt_id=%s", prompt_id)
            elapsed = 0.0
            while elapsed < timeout:
                hist = await self.get_history(prompt_id)
                if hist is not None:
                    status = hist.get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError(f"ComfyUI 执行出错: {status.get('messages', [])}")
                    node_out = hist.get("outputs", {}).get(outputs_node, {})
                    return await self._collect(node_out, save_to)
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
            raise TimeoutError(f"ComfyUI 超时 ({timeout}s): {prompt_id}")

    async def _collect(self, node_out: dict[str, Any], save_to: Path | None) -> list[Path]:
        results: list[Path] = []
        items: list[dict[str, str]] = []
        for key in ("images", "gifs", "videos"):
            items.extend(node_out.get(key, []) or [])
        if not items:
            raise RuntimeError(f"ComfyUI 输出为空: {node_out}")
        for it in items:
            fname = it["filename"]
            sub = it.get("subfolder", "")
            typ = it.get("type", "output")
            data = await self.download_view(fname, sub, typ)
            if save_to:
                save_to.mkdir(parents=True, exist_ok=True)
                p = save_to / fname
                p.write_bytes(data)
                results.append(p)
            else:
                results.append(Path(fname))
        return results
