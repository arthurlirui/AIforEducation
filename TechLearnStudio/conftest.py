"""TechLearnStudio 根 conftest：统一测试环境，避免收集顺序依赖。

T1：TLS_DB_PATH 在此（收集任何测试模块之前）统一定向到系统临时目录的
一次性 DB 文件——backend 与 studio 的测试共用同一个已知是临时的 DB，
不再出现"studio/conftest 声称统一但实际被 backend 导入期覆盖"的静默失效。
backend/tests/conftest.py 仅在独立运行 backend 测试时提供本地兜底。
e2e 启动的是独立子进程 backend（setup_module 里显式传 env），不受影响。
"""
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

if "TLS_ADMIN_TOKEN" not in os.environ:
    os.environ["TLS_ADMIN_TOKEN"] = "test-token"

# 统一测试 DB：始终覆盖外部 env（测试绝不能写真实 DB）；
# 带 pid 避免并行会话互踩，会话结束由 pytest_sessionfinish 清理
_TMP_DB = Path(tempfile.gettempdir()) / f"tls_unified_test_{os.getpid()}.db"
os.environ["TLS_DB_PATH"] = str(_TMP_DB)

sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "studio"))
sys.path.insert(0, str(_ROOT))


def pytest_sessionfinish(session, exitstatus):
    """会话结束后清理统一临时 DB（尽力而为，含 WAL/SHM 旁文件）。"""
    try:
        db_mod = sys.modules.get("app.db")
        if db_mod is not None:
            db_mod.engine.dispose()
        for p in (_TMP_DB,
                  Path(str(_TMP_DB) + "-wal"),
                  Path(str(_TMP_DB) + "-shm")):
            if p.exists():
                p.unlink()
    except Exception:
        pass
