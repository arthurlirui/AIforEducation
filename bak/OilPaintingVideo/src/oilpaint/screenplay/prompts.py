"""剧本生成系统提示词。"""
from __future__ import annotations

import json

from .schemas import SCRIPT_JSON_SCHEMA_HINT


def system_prompt(style_key: str, style_name: str, painters: list[str]) -> str:
    return (
        "你是一位精通经典油画美学与影视叙事的短片导演/编剧。"
        "你的任务是把用户给定的主题，编写成一段 {total} 秒左右的油画风格剧情短片剧本，"
        "用于 AI 图生视频生成。\n\n"
        "## 美学约束\n"
        f"- 统一采用「{style_name}」油画风格（风格 key: {style_key}）。\n"
        f"- 可选画家（单镜头可指定其一以聚焦风格）：{', '.join(painters) or '由风格预设决定'}。\n"
        "- 画面描述应契合油画质感：构图、光影、笔触、色调、氛围，避免现代/数字元素。\n"
        "- 叙事要有起承转合，每个场景是一个情绪单元，每个镜头是一幅可动起来的油画。\n\n"
        "## 镜头设计\n"
        "- 每镜头时长 2~5 秒，总时长尽量贴近目标。\n"
        "- camera_motion 从 static/pan_left/pan_right/zoom_in/zoom_out/tilt_up/tilt_down 中选，"
        "让画面「动得起来」且有情绪。\n"
        "- i2v_model：动作剧烈或需要高质量时用 wan，其余用 ltx（更轻快）。\n"
        "- prompt 只描述画面本身，不要写风格词（系统会自动叠加油画风格）。\n"
        "- narration 是该镜头的字幕旁白，简短有诗意，可为空。\n\n"
        "## 输出格式\n"
        "严格输出单个 JSON 对象，不要任何解释文字。结构如下：\n"
        f"{json.dumps(SCRIPT_JSON_SCHEMA_HINT, ensure_ascii=False, indent=2)}\n"
    ).replace("{total}", "{target_duration_sec}")  # 占位，由 generator 注入


def user_prompt(
    topic: str,
    target_duration_sec: int,
    style_key: str,
    style_name: str,
    painters: list[str],
    aspect: str,
) -> str:
    sysp = system_prompt(style_key, style_name, painters)
    return (
        f"{sysp}\n"
        f"## 本次创作参数\n"
        f"- 主题：{topic}\n"
        f"- 风格：{style_name}（{style_key}）\n"
        f"- 画幅：{aspect}\n"
        f"- 目标总时长：约 {target_duration_sec} 秒\n\n"
        f"请输出剧本 JSON。"
    )
