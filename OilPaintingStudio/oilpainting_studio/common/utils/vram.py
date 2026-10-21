"""显存调度工具。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def release_gpu_memory() -> None:
    """释放 GPU 显存。"""
    try:
        import torch
        torch.cuda.empty_cache()
        logger.info("GPU 显存已释放")
    except ImportError:
        pass


def unload_all_models() -> None:
    """卸载所有已加载模型。"""
    try:
        import gc
        import torch
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("模型已卸载")
    except ImportError:
        import gc
        gc.collect()
