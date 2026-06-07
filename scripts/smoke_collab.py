"""Manual smoke test for `macr collab` against the real claude + codex CLIs.

Usage:
    .venv/bin/python scripts/smoke_collab.py /path/to/target-repo "pytest -q" "add a hello() function"
Requires `claude` and `codex` on PATH (logged in), and a clean git target repo.
Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: smoke_collab.py <repo> <test-cmd> <task>", file=sys.stderr)
        raise SystemExit(2)
    repo, test_cmd, task = sys.argv[1], sys.argv[2], sys.argv[3]
    raise SystemExit(main(["collab", task, "--repo", repo, "--test-cmd", test_cmd]))
