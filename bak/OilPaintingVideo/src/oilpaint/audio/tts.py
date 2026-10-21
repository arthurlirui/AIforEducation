"""TTS 旁白接口（预留，默认关闭）。

未来可接入 GPT-SoVITS / Edge-TTS / 火山 TTS 等。当前仅返回空，剪辑时跳过旁白音轨。
"""
from __future__ import annotations

from pathlib import Path


def synthesize_narration(text: str, out_path: Path) -> Path | None:
    """合成旁白音频。预留实现，当前不生成。"""
    if not text.strip():
        return None
    # TODO: 接入 TTS 引擎
    return None
