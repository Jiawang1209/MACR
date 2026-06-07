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


def test_collab_prints_artifact_path(tmp_path, monkeypatch, capsys):
    """At the end of collab, the .macr/runs/<id> artifact dir is printed."""
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
    out = capsys.readouterr().out
    assert "artifacts" in out
    assert ".macr/runs" in out


def test_collab_yes_auto_approves_without_stdin(tmp_path, monkeypatch):
    """--yes makes the human gate auto-approve; no stdin read; zero exit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true", "--yes"],
        claude_backend=_claude(),
        codex_backend=_codex(),
        # NOTE: do NOT inject human_gate — let --yes wire auto_approve_gate
    )
    assert rc == 0


def test_collab_non_tty_without_yes_errors_clearly(tmp_path, monkeypatch, capsys):
    """Non-TTY + interactive gate + no --yes → exit 2 with a --yes hint (not raw EOFError)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true"],
        claude_backend=_claude(),
        codex_backend=_codex(),
        # gate NOT injected → resolves to interactive collab gate → guard fires
    )
    assert rc == 2
    assert "--yes" in capsys.readouterr().err
