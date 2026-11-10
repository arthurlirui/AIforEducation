"""Backend 测试环境兜底（T1）。

仅在独立运行 backend 测试（根 conftest 未加载）时生效：
- TLS_DB_PATH 指向本目录临时 DB，teardown 由 test_backend.py 清理；
- TLS_ADMIN_TOKEN 与全仓测试一致。

全仓运行时根 conftest 已设统一 DB，setdefault 不会覆盖。
"""
import os
from pathlib import Path

os.environ.setdefault("TLS_DB_PATH", str(Path(__file__).resolve().parent / "_test.db"))
os.environ.setdefault("TLS_ADMIN_TOKEN", "test-token")
