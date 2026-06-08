import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.discussion import run_discuss
from macr.discussion_control import ControlDecision
from macr.discussion_view import FakeView, SilentView
from macr.schemas import Decision, HumanFeedback


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


def _build(tmp_path, *, control_actions, max_rounds=2, consensus_gate=_approve, final_gate=_approve, view=None):
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
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 2,
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
        view=view or SilentView(), today="20260607",
    )


def test_discuss_announces_run_dir_at_start(tmp_path):
    """The first view event is a banner note with the run_id + artifact dir."""
    view = FakeView()
    _build(tmp_path, control_actions=[ControlDecision("end")], view=view)
    assert view.events
    kind, text = view.events[0][0], view.events[0][1]
    assert kind == "note"
    assert "R20260607_001" in text and "artifacts" in text


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
    # plan review runs before consensus_gate; only plan_review decisions present (no impl decisions)
    assert all(d.get("stage") == "plan_review" for d in state.decisions)


def test_abort_keeps_worktree(tmp_path):
    state = _build(tmp_path, control_actions=[ControlDecision("abort")])
    assert (tmp_path / "wts" / "R20260607_001").exists()
    assert state.worktree_path is not None


def test_consensus_reject_keeps_worktree(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")
    state = _build(tmp_path, control_actions=[ControlDecision("end")], consensus_gate=reject)
    assert (tmp_path / "wts" / "R20260607_001").exists()
    assert state.worktree_path is not None


def test_final_reject_cleans_worktree(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")
    state = _build(tmp_path, control_actions=[ControlDecision("end")], final_gate=reject)
    assert not (tmp_path / "wts" / "R20260607_001").exists()
    assert state.worktree_path is None


def test_view_receives_structured_events(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({"discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")],
                                       "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]})
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    view = FakeView()
    actions = iter([ControlDecision("continue"), ControlDecision("end")])
    from macr.discussion import run_discuss
    run_discuss(
        "topic", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, max_revisions=2,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: next(actions),
        view=view, today="20260607",
    )
    kinds = [e[0] for e in view.events]
    assert kinds[0] == "note"  # run banner (run_id + artifact dir) comes first
    assert kinds[1:3] == ["plan", "plan"]
    assert view.events[1][1] == "claude"
    assert any(e[0] == "turn" for e in view.events)
    assert any(e[0] == "consensus" for e in view.events)


def _needs_fix_review():
    return {"summary": "needs work",
            "findings": [{"level": "blocking", "issue": "no error handling",
                          "evidence": "step list", "recommendation": "add try/except"}],
            "decision": "needs_fix"}


def _approve_review():
    return {"summary": "ok", "findings": [], "decision": "approve"}


def _build_with_review(tmp_path, *, reviews, max_plan_revisions, max_rounds=1):
    """Run discuss with a scripted Codex reviewer sequence; discussion ends immediately."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1"), _turn("c2"), _turn("c3"), _turn("c4")],
        "consensus": [_consensus(), _consensus(), _consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 3,
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")],
        "discuss_turn": [_turn("x1"), _turn("x2"), _turn("x3"), _turn("x4")],
        "discuss_reviewer": list(reviews),
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    view = FakeView()
    state = run_discuss(
        "build a thing", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=max_rounds, max_revisions=2, max_plan_revisions=max_plan_revisions,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=view, today="20260607",
    )
    return state, view, codex_discuss


def test_plan_review_pass_first_try_no_extra_rounds(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_approve_review()], max_plan_revisions=1)
    # exactly one review call, decision PASS recorded
    assert codex.calls.count("discuss_reviewer") == 1
    plan_decisions = [d for d in state.decisions if d.get("stage") == "plan_review"]
    assert plan_decisions[-1]["decision"] == "PASS"
    assert ("evaluation", 0, Decision.PASS) in view.events
    # no revision turn was injected into the transcript
    assert not any(e.get("agent") == "codex_reviewer" for e in state.discussion)


def test_plan_review_needs_fix_then_revise_then_pass(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_needs_fix_review(), _approve_review()], max_plan_revisions=1)
    assert codex.calls.count("discuss_reviewer") == 2
    plan_decisions = [d["decision"] for d in state.decisions if d.get("stage") == "plan_review"]
    assert plan_decisions == ["NEEDS_FIX", "PASS"]
    # findings were injected back into the discussion as a 'review' record
    assert any(e.get("kind") == "review" and e.get("agent") == "codex_reviewer"
               for e in state.discussion)
    # re-consensus happened (claude consensus called twice)


def test_plan_review_exhausts_then_escalates(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_needs_fix_review(), _needs_fix_review()], max_plan_revisions=1)
    plan_decisions = [d for d in state.decisions if d.get("stage") == "plan_review"]
    assert plan_decisions[-1]["decision"] == "NEEDS_FIX"
    # still reached consensus gate + implementation (final approved → reaches final gate)
    assert state.human_feedback is not None


def test_plan_review_reviewer_error_is_blocked(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")], "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })

    class _CodexNoReviewer(FakeAgentBackend):
        def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None):
            if role.name == "discuss_reviewer":
                from macr.agent import AgentError
                raise AgentError("reviewer down")
            return super().run_role(role, state, run_id=run_id, task_id=task_id,
                                    timestamp=timestamp, trace=trace)

    codex = _CodexNoReviewer({
        "discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    state = run_discuss(
        "t", repo=repo, test_cmd=["true"], claude_backend=claude, codex_backend=codex,
        impl_codex_backend=codex_impl, runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, max_revisions=2, max_plan_revisions=1,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=SilentView(), today="20260607",
    )
    plan_decisions = [d for d in state.decisions if d.get("stage") == "plan_review"]
    assert plan_decisions[-1]["decision"] == "BLOCKED"
    assert state.human_feedback is not None  # gracefully reached the gates


def test_run_discuss_accepts_injected_run_id(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    from macr.discussion import run_discuss
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")], "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()], "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")],
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    state = run_discuss(
        "topic", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=SilentView(), run_id="CUSTOM_ID2",
    )
    assert state.run_id == "CUSTOM_ID2"
    assert (tmp_path / "runs" / "CUSTOM_ID2" / "state.json").exists()
