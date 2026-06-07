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


def test_collab_accepts_no_subagents_flag(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true", "--no-subagents"],
        claude_backend=_claude(), codex_backend=_codex(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0


def test_build_real_backends_respects_no_subagents(monkeypatch):
    captured = {}

    class _FakeClaude:
        def __init__(self, *, model=None, timeout=1800, enable_subagents=True):
            captured["claude"] = enable_subagents

    class _FakeCodex:
        def __init__(self, *, model=None, timeout=1800, enable_subagents=True):
            captured["codex"] = enable_subagents

    import macr.agents.cli_backend as clib
    monkeypatch.setattr(clib, "ClaudeCliBackend", _FakeClaude)
    monkeypatch.setattr(clib, "CodexCliBackend", _FakeCodex)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)

    import argparse
    args = argparse.Namespace(task="t", repo=".", test_cmd="true", max_revisions=2,
                              claude_model=None, codex_model=None, timeout=1800, no_subagents=True)
    cli._collab_command(args, claude_backend=None, codex_backend=None,
                        human_gate=lambda *a, **k: None)
    assert captured == {"claude": False, "codex": False}
