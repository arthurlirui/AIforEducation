"""TechLearnStudio 根 conftest：统一测试环境，避免收集顺序依赖。

backend/tests 与 studio/tests 都以 TLS_ADMIN_TOKEN=test-token 推送；
e2e 启动的是独立子进程 backend（setup_module 里显式传 e2e-token），
不受这里的影响。在导入任何 app 模块之前先固定环境变量，
保证 `pytest` 无论按什么顺序收集，settings 单例读到的都一致。
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

if "TLS_ADMIN_TOKEN" not in os.environ:
    os.environ["TLS_ADMIN_TOKEN"] = "test-token"

sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "studio"))
sys.path.insert(0, str(_ROOT))
