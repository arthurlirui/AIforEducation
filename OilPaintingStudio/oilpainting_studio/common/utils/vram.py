"""显存调度工具。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def empty_cuda_cache() -> None:
    """释放 CUDA 缓存的显存块（torch.cuda.empty_cache）。

    注意: 只归还缓存的空闲块, 不卸载模型权重; 模型对象由各 stage
    局部持有、阶段结束后由 GC 回收。
    """
    try:
        import torch
        torch.cuda.empty_cache()
        logger.info("CUDA 缓存显存已清空 (empty_cache)")
    except ImportError:
        pass


def release_gpu_memory() -> None:
    """empty_cuda_cache 的旧名别名（保留兼容, 语义见 empty_cuda_cache）。"""
    empty_cuda_cache()


def unload_all_models() -> None:
    """触发 GC 并清空 CUDA 缓存（不持有模型引用, 卸载依赖 GC）。"""
    try:
        import gc
        import torch
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("已触发 GC 并清空 CUDA 缓存")
    except ImportError:
        import gc
        gc.collect()
