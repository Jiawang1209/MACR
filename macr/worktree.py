from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    """Raised when the target repo is invalid or a git worktree op fails."""


# Files written into the worktree by agent tooling / language caches during a run.
# Excluded from the captured diff so they don't pollute the reviewer/human-gate/final
# output. (dogfood v2 finding A: `git add -A` was pulling .omc/ into the diff.)
_DIFF_EXCLUDES = (
    ":(exclude).omc",
    ":(exclude,glob).omc/**",
    ":(exclude,glob)**/__pycache__/**",
    ":(exclude,glob)**/*.pyc",
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


@dataclass
class Worktree:
    repo: Path
    path: Path
    base_commit: str

    @classmethod
    def create(cls, repo: Path, run_id: str, worktrees_dir: Path) -> "Worktree":
        repo = Path(repo)
        if not (repo / ".git").exists():
            inside = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(repo), capture_output=True, text=True,
            )
            if inside.returncode != 0 or inside.stdout.strip() != "true":
                raise WorktreeError(f"{repo} is not a git repository")
        status = _git(["status", "--porcelain"], repo).stdout.strip()
        if status:
            raise WorktreeError(f"{repo} has a dirty working tree; commit or stash first")
        base_commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        worktrees_dir = Path(worktrees_dir)
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        wt_path = worktrees_dir / run_id
        _git(["worktree", "add", "--detach", str(wt_path), base_commit], repo)
        return cls(repo=repo, path=wt_path, base_commit=base_commit)

    def diff(self) -> str:
        _git(["add", "-A"], self.path)
        return _git(["diff", "--cached", "--", ".", *_DIFF_EXCLUDES], self.path).stdout

    def cleanup(self) -> None:
        _git(["worktree", "remove", "--force", str(self.path)], self.repo)
