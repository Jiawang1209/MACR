import subprocess
from pathlib import Path

import pytest

from macr.worktree import Worktree, WorktreeError


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    env = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", *env, "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_create_rejects_non_git(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(WorktreeError):
        Worktree.create(tmp_path / "plain", "R1", tmp_path / "wts")


def test_create_rejects_dirty_tree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("dirty\n")
    with pytest.raises(WorktreeError):
        Worktree.create(repo, "R1", tmp_path / "wts")


def test_create_and_diff_captures_edits_and_new_files(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = Worktree.create(repo, "R1", tmp_path / "wts")
    assert Path(wt.path).exists()
    (Path(wt.path) / "a.txt").write_text("hello world\n")
    (Path(wt.path) / "new.py").write_text("print('x')\n")
    diff = wt.diff()
    assert "hello world" in diff
    assert "new.py" in diff


def test_cleanup_removes_worktree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = Worktree.create(repo, "R1", tmp_path / "wts")
    assert Path(wt.path).exists()
    wt.cleanup()
    assert not Path(wt.path).exists()
