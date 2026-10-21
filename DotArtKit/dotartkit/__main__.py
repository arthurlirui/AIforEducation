"""__main__.py — 支持 ``python -m dotartkit`` 调用 CLI."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
