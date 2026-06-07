from __future__ import annotations

import subprocess
from pathlib import Path

from macr.schemas import TestResult


def run_tests(worktree_path: Path, test_cmd: list[str], timeout: int = 1800) -> TestResult:
    command = " ".join(test_cmd)
    try:
        proc = subprocess.run(
            test_cmd, cwd=str(worktree_path),
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return TestResult(command=command, passed=False, exit_code=127, log="command not found")
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
        return TestResult(command=command, passed=False, exit_code=-1, log=log, timed_out=True)
    return TestResult(
        command=command,
        passed=proc.returncode == 0,
        exit_code=proc.returncode,
        log=(proc.stdout or "") + (proc.stderr or ""),
    )
