import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.collab_orchestrator import run_collab
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _plan():
    return {"summary": "p", "steps": ["edit a.txt"], "tools_needed": [], "risks": []}


def _exec(tag):
    return {"artifact": f"edited-{tag}", "notes": "", "evidence": ["a.txt"]}


def _review(decision):
    return {"summary": "rev", "findings": [], "decision": decision}


def _approve(state, **kw):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path) / "a.txt").write_text("changed by codex\n")


def _run(tmp_path, *, claude_script, codex_script, test_cmd, max_revisions=2, gate=_approve):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude_backend = FakeAgentBackend(claude_script)
    codex_backend = FakeAgentBackend(codex_script, on_run=_editor)
    return run_collab(
        "do the task", repo=repo, test_cmd=test_cmd,
        claude_backend=claude_backend, codex_backend=codex_backend,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_revisions=max_revisions, human_gate=gate, printer=lambda *_: None,
        today="20260607",
    )


def test_collab_announces_run_dir_at_start(tmp_path):
    """First thing printed is a banner with the run_id + artifact dir."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    lines = []
    run_collab(
        "do the task", repo=repo, test_cmd=["true"],
        claude_backend=FakeAgentBackend({"planner": [_plan()], "reviewer": [_review("approve")]}),
        codex_backend=FakeAgentBackend({"executor": [_exec(1)]}, on_run=_editor),
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        human_gate=_approve, printer=lines.append, today="20260607",
    )
    assert lines and "R20260607_001" in lines[0] and "artifacts" in lines[0]


def test_pass_path(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve")]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
    )
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "planner.output.md").exists()
    assert (run_path / "diff.v1.patch").read_text().strip() != ""
    assert (run_path / "test.v1.json").exists()
    assert [d["decision"] for d in state.decisions] == ["PASS"]
    assert state.human_feedback.decision == "approve"
    assert "changed by codex" in (run_path / "diff.v1.patch").read_text()
    saved = json.loads((run_path / "state.json").read_text())
    assert saved["worktree_path"] is not None


def test_failing_then_pass(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("needs_fix"), _review("approve")]},
        codex_script={"executor": [_exec(1), _exec(2)]},
        test_cmd=["sh", "-c", "test -f a.txt && grep -q changed a.txt"],
        max_revisions=2,
    )
    assert state.decisions[-1]["decision"] == "PASS"


def test_persistent_failure_exhausts_to_gate(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve"), _review("approve")]},
        codex_script={"executor": [_exec(1), _exec(2)]},
        test_cmd=["false"],
        max_revisions=1,
    )
    assert len(state.decisions) == 2
    assert all(d["decision"] == "NEEDS_FIX" for d in state.decisions)
    assert state.human_feedback is not None


def test_blocking_review_needs_fix(tmp_path):
    blocking = {"summary": "bad", "findings": [{"level": "blocking", "issue": "i", "evidence": "e", "recommendation": "r"}], "decision": "needs_fix"}
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [blocking]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
        max_revisions=0,
    )
    assert state.decisions[-1]["decision"] == "NEEDS_FIX"


def test_reject_cleans_up_worktree(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")

    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve")]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
        gate=reject,
    )
    assert state.human_feedback.decision == "reject"
    assert not (tmp_path / "wts" / "R20260607_001").exists()


def test_agent_error_routes_to_blocked_gate_and_persists(tmp_path):
    from macr.agent import AgentError
    from macr.schemas import Message, MessageType

    class _RaisingBackend:
        name = "raising"

        def run_role(self, role, state, *, run_id, task_id, timestamp=None, **kwargs):
            raise AgentError("planner failed twice")

    repo = tmp_path / "repo"
    _init_repo(repo)
    codex = FakeAgentBackend({"executor": [_exec(1)]}, on_run=_editor)
    state = run_collab(
        "task", repo=repo, test_cmd=["true"],
        claude_backend=_RaisingBackend(), codex_backend=codex,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_revisions=2, human_gate=_approve, printer=lambda *_: None, today="20260607",
    )
    assert state.decisions[-1]["decision"] == "BLOCKED"
    assert state.human_feedback is not None  # gate still reached
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "evaluator.output.json").exists()  # BLOCKED decision landed on disk
    assert (run_path / "state.json").exists()
