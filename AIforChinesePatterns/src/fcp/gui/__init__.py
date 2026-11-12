"""fcp.gui — 傅里叶纹样桌面编辑器（论文 Demo 软件）.

运行::

    py -m fcp.gui            # 或 py -m fcp.gui.app [图片路径]
"""

from .app import PatternApp, main

__all__ = ["PatternApp", "main"]
