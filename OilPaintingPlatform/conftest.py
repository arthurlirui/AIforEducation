"""Pytest configuration: make the backend ``app`` package importable.

Replaces the previous ``sys.path.insert`` hack inside tests/test_backend.py.
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
