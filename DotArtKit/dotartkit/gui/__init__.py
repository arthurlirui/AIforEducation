"""dotartkit.gui — 桌面端波点艺术编辑器 (tkinter).

- :mod:`.polka_document`  核心文档模型 (可独立测试)
- :mod:`.polka_app`       tkinter 桌面应用入口

命令行启动::

    py -m dotartkit.gui [图片路径] [模型目录]
"""

from .polka_document import (
    PolkaDocument,
    Dot,
    DEPTH_BACKENDS,
    ACTIVATIONS,
    FILTERS,
)


def main():
    """桌面应用入口 (等价 ``py -m dotartkit.gui.polka_app``)."""
    from .polka_app import main as _main
    _main()


__all__ = [
    "PolkaDocument",
    "Dot",
    "DEPTH_BACKENDS",
    "ACTIVATIONS",
    "FILTERS",
    "main",
]

