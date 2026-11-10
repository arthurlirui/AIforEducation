"""revive 内部共享工具：cv2 中文路径兼容 (Windows)。

实现已上移到 common 层（oilpainting_studio.common.imio）；
本模块保留为兼容别名, revive 内既有 import 不受影响。
"""
from ..common.imio import imread_, imwrite_  # noqa: F401
