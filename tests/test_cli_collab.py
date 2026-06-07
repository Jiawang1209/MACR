import subprocess
from pathlib import Path

from macr import cli
from macr.agents.base import FakeAgentBackend
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _claude():
    return FakeAgentBackend({
        "planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })


def _codex():
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")
    return FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=on_run)


def test_collab_approve_returns_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true"],
        claude_backend=_claude(),
        codex_backend=_codex(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_collab_reject_returns_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true"],
        claude_backend=_claude(),
        codex_backend=_codex(),
        human_gate=lambda state, **kw: HumanFeedback(decision="reject", feedback="no", timestamp="t"),
    )
    assert rc == 1


def test_collab_missing_binary_errors(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    rc = cli.main(["collab", "do it", "--repo", str(repo), "--test-cmd", "true"])
    assert rc == 2
