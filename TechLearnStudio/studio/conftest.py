"""Studio test conftest: 统一管理 DB 路径，避免跨文件环境变量污染。"""
import os
import sys
from pathlib import Path

# 统一用同一个临时 DB
_TMP_DB = Path(__file__).resolve().parent / "_test_unified.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["TLS_DB_PATH"] = str(_TMP_DB)
os.environ["TLS_ADMIN_TOKEN"] = "test-token"

# 确保 backend 和 studio 在 path 上
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
