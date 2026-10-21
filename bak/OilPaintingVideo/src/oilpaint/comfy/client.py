"""ComfyUI HTTP 客户端。

调用流程：
  1. 上传输入图像（如需）：POST /upload/image
  2. 提交工作流：POST /prompt  → 返回 prompt_id
  3. 轮询历史：GET /history/{prompt_id}，直到出现 outputs
  4. 拉取产物：GET /view?filename=...&subfolder=...&type=output

支持并发限流（asyncio.Semaphore）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0
POLL_INTERVAL = 2.0
PER_JOB_TIMEOUT = 600.0  # 单次生图/生视频最多等 10 分钟


class ComfyClient:
    def __init__(self, base_url: str, concurrency: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = str(uuid.uuid4())
        self._sem = asyncio.Semaphore(concurrency)
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    async def health(self) -> tuple[bool, str]:
        """探测 ComfyUI 是否在线，并返回 /object_info 概要。"""
        try:
            r = await self._get_http().get(f"{self.base_url}/system_stats", timeout=10)
            if r.status_code != 200:
                return False, f"system_stats HTTP {r.status_code}"
            return True, "ok"
        except httpx.HTTPError as e:
            return False, f"{type(e).__name__}: {e}"

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        """获取节点/模型信息。node_class 为空则返回全部。"""
        url = f"{self.base_url}/object_info"
        if node_class:
            url += f"/{node_class}"
        r = await self._get_http().get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    async def upload_image(self, image_path: Path) -> dict[str, str]:
        """上传图像到 ComfyUI input 目录，返回 {name, subfolder, type}。"""
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            r = await self._get_http().post(
                f"{self.base_url}/upload/image", files=files, timeout=60
            )
        r.raise_for_status()
        return r.json()

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        """提交工作流（API 格式），返回 prompt_id。"""
        payload = {"prompt": workflow, "client_id": self.client_id}
        r = await self._get_http().post(f"{self.base_url}/prompt", json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"ComfyUI 排队失败: {data['error']}")
        return data["prompt_id"]

    async def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        """读取某 prompt 的历史记录，未完成返回 None。"""
        r = await self._get_http().get(f"{self.base_url}/history/{prompt_id}", timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get(prompt_id)

    async def download_view(
        self, filename: str, subfolder: str = "", item_type: str = "output"
    ) -> bytes:
        """从 /view 拉取产物二进制。"""
        params = {"filename": filename, "subfolder": subfolder, "type": item_type}
        r = await self._get_http().get(f"{self.base_url}/view", params=params, timeout=120)
        r.raise_for_status()
        return r.content

    async def run(
        self,
        workflow: dict[str, Any],
        *,
        outputs_node: str = "output",
        save_to: Path | None = None,
        timeout: float = PER_JOB_TIMEOUT,
    ) -> list[Path]:
        """端到端：提交 → 轮询 → 下载产物。返回产物本地路径列表。

        outputs_node: 工作流中保存最终产物的节点 id（SaveImage / SaveAnimatedPNG / VHS_VideoCombine 等）。
        """
        async with self._sem:
            prompt_id = await self.queue_prompt(workflow)
            logger.info("ComfyUI 排队成功 prompt_id=%s", prompt_id)

            elapsed = 0.0
            while elapsed < timeout:
                hist = await self.get_history(prompt_id)
                if hist is not None:
                    # 完成或失败
                    outputs = hist.get("outputs", {})
                    node_out = outputs.get(outputs_node, {})
                    # 检查执行错误
                    status = hist.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(f"ComfyUI 执行出错: {msgs}")
                    return await self._collect_outputs(node_out, save_to)
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
            raise TimeoutError(f"ComfyUI 任务超时 ({timeout}s): prompt_id={prompt_id}")

    async def _collect_outputs(
        self, node_out: dict[str, Any], save_to: Path | None
    ) -> list[Path]:
        """从节点输出中收集图片/视频文件。兼容 SaveImage 与 VHS_VideoCombine。"""
        results: list[Path] = []
        # SaveImage: {"images": [{"filename","subfolder","type"}]}
        # VHS_VideoCombine: {"gifs": [...], "videos": [...]} 或 {"images":[...]}
        items: list[dict[str, str]] = []
        for key in ("images", "gifs", "videos"):
            items.extend(node_out.get(key, []) or [])

        if not items:
            raise RuntimeError(f"ComfyUI 节点输出为空: {node_out}")

        for it in items:
            fname = it["filename"]
            sub = it.get("subfolder", "")
            typ = it.get("type", "output")
            data = await self.download_view(fname, sub, typ)
            if save_to is not None:
                save_to.mkdir(parents=True, exist_ok=True)
                p = save_to / fname
                p.write_bytes(data)
                results.append(p)
            else:
                results.append(Path(fname))
        return results
