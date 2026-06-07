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
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 2,
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


def test_discuss_prints_artifact_path(tmp_path, monkeypatch, capsys):
    """At the end of discuss, the .macr/runs/<id> artifact dir is printed."""
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
    out = capsys.readouterr().out
    assert "artifacts" in out
    assert ".macr/runs" in out


def test_discuss_abort_returns_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("abort"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
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


def test_discuss_tui_non_tty_uses_auto_control(tmp_path, monkeypatch):
    # non-tty --tui WITHOUT an injected discussion_control: must auto-advance (not EOFError on input)
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1", "--tui"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0  # before the fix this would EOFError on the round-boundary input -> rc 2


def test_discuss_max_plan_revisions_threaded(tmp_path, monkeypatch):
    """--max-plan-revisions reaches run_discuss; reviewer runs and zero exit on approve."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    codex = _codex_discuss()
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true",
         "--max-rounds", "1", "--max-plan-revisions", "0"],
        claude_backend=_claude(), codex_backend=codex, impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    # max_plan_revisions=0 => exactly one review, no revision rounds
    assert codex.calls.count("discuss_reviewer") == 1


def test_discuss_yes_auto_approves_without_stdin(tmp_path, monkeypatch):
    """--yes makes both gates auto-approve; no stdin read; zero exit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true",
         "--max-rounds", "1", "--yes"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        # NOTE: do NOT inject gates — let --yes wire auto_approve_gate
    )
    assert rc == 0


def test_discuss_non_tty_without_yes_errors_clearly(tmp_path, monkeypatch, capsys):
    """Non-TTY + interactive gates + no --yes → exit 2 with a --yes hint (not raw EOFError)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        # gates NOT injected → resolve to interactive console gates → guard fires
    )
    assert rc == 2
    assert "--yes" in capsys.readouterr().err
