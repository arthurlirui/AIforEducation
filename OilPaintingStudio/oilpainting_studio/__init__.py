"""OilPaintingStudio — 经典油画风格动态艺术生成统一项目.

整合两个互补的油画动态生成管线:

- **video** (原 OilPaintingVideo): LLM 剧本 → ComfyUI 油画关键帧 → I2V 视频 → ffmpeg 剪辑
- **revive** (原 OilPaintingRevive): 单幅油画 → 4 模块 Canvas3D (PaintParse / MonoSplat / SketchComp / ArtiFlow)

共享基础设施在 ``common/``: 配置 / LLM 客户端 / ComfyUI HTTP 客户端 / 工具函数.

入口:
    - Python: ``from oilpainting_studio.video.cli import cli`` 或 ``from oilpainting_studio.revive.cli import cli``
    - CLI (待 pyproject 注册): ``oilpainting-studio video ...`` / ``oilpainting-studio revive ...``
"""

__version__ = "1.0.0"
