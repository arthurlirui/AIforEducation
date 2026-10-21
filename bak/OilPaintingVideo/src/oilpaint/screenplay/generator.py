"""剧本生成器：调 LLM 产出结构化剧本，解析失败自动重试。"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Settings
from ..llm_client import LLMClient, LLM_ERROR_PREFIX
from .prompts import user_prompt
from .schemas import Scene, Script, Shot

logger = logging.getLogger(__name__)

MAX_PARSE_RETRIES = 3


def _repair_shot_numbering(script: dict[str, Any]) -> dict[str, Any]:
    """修正镜头序号与 scene_index，保证全局连续。"""
    global_idx = 0
    for scene in script.get("scenes", []):
        si = scene.get("index", 0)
        for shot in scene.get("shots", []):
            global_idx += 1
            shot["index"] = global_idx
            shot["scene_index"] = si
    return script


async def generate_script(
    client: LLMClient,
    settings: Settings,
    topic: str,
    *,
    style_key: str | None = None,
    aspect: str | None = None,
    target_duration_sec: int | None = None,
) -> tuple[Script | None, str]:
    """生成剧本。返回 (Script|None, error_or_info)。

    解析失败时会把错误回灌给 LLM 让其修正，最多 MAX_PARSE_RETRIES 轮。
    """
    style = settings.style(style_key)
    aspect = aspect or settings.aspect
    target = target_duration_sec or settings.target_duration_sec

    messages: list[dict[str, str]] = [
        {
            "role": "user",
            "content": user_prompt(
                topic, target, style.key, style.name, style.painters, aspect
            ),
        }
    ]

    last_err = ""
    for attempt in range(1, MAX_PARSE_RETRIES + 1):
        parsed, raw = await client.chat_json(messages, temperature=0.8)
        if parsed is None:
            last_err = raw
            logger.warning("剧本生成第 %d 轮失败: %s", attempt, last_err)
            if raw.startswith(LLM_ERROR_PREFIX):
                # API 级失败，不回灌
                break
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"上一段不是合法 JSON 或字段不符合要求，错误：{raw}。"
                    "请严格只输出符合 schema 的单个 JSON 对象，不要任何解释。"
                ),
            })
            continue

        # 修正序号并校验
        parsed = _repair_shot_numbering(parsed)
        try:
            script = Script(
                title=parsed.get("title", "未命名"),
                synopsis=parsed.get("synopsis", ""),
                style=style.key,
                aspect=aspect,
                scenes=[Scene(**s) for s in parsed.get("scenes", [])],
            )
            # 递归构造 Shot
            for scene, raw_scene in zip(script.scenes, parsed.get("scenes", [])):
                scene.shots = [Shot(**sh) for sh in raw_scene.get("shots", [])]
            script.recompute_duration()
            if not script.shots:
                last_err = "剧本无镜头"
                continue
            return script, f"ok (scenes={len(script.scenes)}, shots={len(script.shots)}, dur={script.total_duration_sec}s)"
        except Exception as e:  # pydantic 校验失败
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("剧本校验失败第 %d 轮: %s", attempt, last_err)
            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append({
                "role": "user",
                "content": f"JSON 字段不符合要求：{last_err}。请修正后重新输出完整 JSON 对象。",
            })

    return None, last_err
