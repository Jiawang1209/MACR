import subprocess
from pathlib import Path

from macr import cli
from macr.agents.base import FakeAgentBackend
from macr.discussion_control import ControlDecision
from macr.discussion_view import FakeView
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
        "discuss_planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
        "discuss_turn": [{"response": "r", "agreements": [], "concerns": [], "revised_steps": []}] * 4,
        "consensus": [{"summary": "c", "steps": ["s"], "rationale": "r", "open_questions": []}],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })


def _codex_discuss():
    return FakeAgentBackend({
        "discuss_planner": [{"summary": "p2", "steps": ["s2"], "tools_needed": [], "risks": []}],
        "discuss_turn": [{"response": "r2", "agreements": [], "concerns": [], "revised_steps": []}] * 4,
    })


def _codex_impl():
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")
    return FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=on_run)


def test_discuss_approve_returns_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_discuss_abort_returns_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("abort"),
    )
    assert rc == 1


def test_discuss_tui_flag_falls_back_non_tty(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1", "--tui"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0


def test_discuss_accepts_injected_view(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    view = FakeView()
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        view=view,
    )
    assert rc == 0
    assert any(e[0] == "plan" for e in view.events)
