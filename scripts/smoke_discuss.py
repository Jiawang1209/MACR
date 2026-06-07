"""Manual smoke test for `macr discuss` against the real claude + codex CLIs.

Usage:
    .venv/bin/python scripts/smoke_discuss.py /path/to/repo "pytest -q" "add a hello() function"
Requires `claude` and `codex` on PATH (logged in), and a clean git target repo.
Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: smoke_discuss.py <repo> <test-cmd> <topic>", file=sys.stderr)
        raise SystemExit(2)
    repo, test_cmd, topic = sys.argv[1], sys.argv[2], sys.argv[3]
    raise SystemExit(main(["discuss", topic, "--repo", repo, "--test-cmd", test_cmd]))
