"""Studio 测试环境兜底（T1）。

仅独立运行 studio 测试（根 conftest 未加载）时生效：
TLS_DB_PATH 指向本目录临时 DB。全仓运行时根 conftest 已统一设置
（系统临时目录的一次性 DB），setdefault 不会覆盖。
"""
import os
from pathlib import Path

os.environ.setdefault("TLS_DB_PATH", str(Path(__file__).resolve().parent / "_test_unified.db"))
os.environ.setdefault("TLS_ADMIN_TOKEN", "test-token")
