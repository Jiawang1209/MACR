import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.discussion import run_discuss
from macr.discussion_control import ControlDecision
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _plan(tag):
    return {"summary": f"plan-{tag}", "steps": [f"step-{tag}"], "tools_needed": [], "risks": []}


def _turn(tag):
    return {"response": f"resp-{tag}", "agreements": [], "concerns": [], "revised_steps": [f"rev-{tag}"]}


def _consensus():
    return {"summary": "agreed", "steps": ["do-1", "do-2"], "rationale": "r", "open_questions": []}


def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path) / "a.txt").write_text("changed\n")


def _approve(state, **kw):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def _build(tmp_path, *, control_actions, max_rounds=2, consensus_gate=_approve, final_gate=_approve):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1"), _turn("c2"), _turn("c3")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")],
        "discuss_turn": [_turn("x1"), _turn("x2"), _turn("x3")],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    actions = iter(control_actions)
    def control(state, round_no, **kw):
        return next(actions)
    return run_discuss(
        "build a thing", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=max_rounds, max_revisions=2,
        consensus_gate=consensus_gate, human_gate=final_gate, discussion_control=control,
        printer=lambda *_: None, today="20260607",
    )


def test_full_flow_to_implementation(tmp_path):
    state = _build(tmp_path, control_actions=[ControlDecision("continue"), ControlDecision("end")])
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "discussion" / "plan.claude.md").exists()
    assert (run_path / "discussion" / "plan.codex.md").exists()
    assert (run_path / "discussion" / "transcript.md").exists()
    assert (run_path / "consensus.md").exists()
    assert state.consensus["steps"] == ["do-1", "do-2"]
    assert state.decisions[-1]["decision"] == "PASS"
    assert state.human_feedback.decision == "approve"
    assert "changed" in (run_path / "diff.v1.patch").read_text()
    saved = json.loads((run_path / "state.json").read_text())
    assert any(e["agent"] == "claude" and e["kind"] == "plan" for e in saved["discussion"])


def test_human_interjection_enters_transcript(tmp_path):
    state = _build(tmp_path, control_actions=[
        ControlDecision("interject", "please prioritize rollback"),
        ControlDecision("end"),
    ], max_rounds=2)
    assert any(e["agent"] == "human" and "rollback" in e["content"] for e in state.discussion)
    run_path = tmp_path / "runs" / "R20260607_001"
    assert "rollback" in (run_path / "discussion" / "transcript.md").read_text()


def test_abort_skips_implementation(tmp_path):
    state = _build(tmp_path, control_actions=[ControlDecision("abort")])
    assert state.consensus is None
    assert state.human_feedback is None
    assert state.decisions == []


def test_consensus_reject_skips_implementation(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")
    state = _build(tmp_path, control_actions=[ControlDecision("end")], consensus_gate=reject)
    assert state.consensus is not None
    assert state.human_feedback.decision == "reject"
    assert state.decisions == []
