"""video — OilPaintingVideo 管线 (LLM 剧本 → ComfyUI 关键帧 → I2V → ffmpeg 剪辑).

迁自原 OilPaintingVideo/src/oilpaint/. 子模块:
- ``screenplay`` — LLM 剧本生成 (pydantic schemas + prompts + generator)
- ``pipeline`` — 导演编排 / 关键帧 / 动画 / 剪辑 (ffmpeg)
- ``mesh2video`` — 风格×几何解耦的 mesh 渲染管线 (trimesh + imageio)
- ``audio`` — BGM 情绪匹配 + TTS (stub)
- ``cli`` — click CLI 入口
"""
