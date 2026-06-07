from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CollabConfig:
    target_repo: Path
    test_cmd: list[str]
    claude_model: str | None = None
    codex_model: str | None = None
    sandbox: str = "workspace-write"
    approval: str = "never"
    timeout: int = 1800
    max_revisions: int = 2
