"""Manual smoke test against the real Anthropic API.

Usage:
    ANTHROPIC_API_KEY=... .venv/bin/python scripts/smoke.py
Requires a network connection and a valid key. Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "写一个 Python 函数,判断一个字符串是否为回文,并附简短说明。"
    raise SystemExit(main(["run", task]))
