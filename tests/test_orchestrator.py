import json

from macr.llm import FakeLLM
from macr.orchestrator import run_task
from macr.schemas import HumanFeedback


def _plan():
    return {"summary": "plan", "steps": ["s1"], "tools_needed": [], "risks": []}


def _exec(v):
    return {"artifact": f"artifact-{v}", "notes": "", "evidence": []}


def _review(decision):
    return {"summary": "rev", "findings": [], "decision": decision}


def _eval(decision):
    return {"decision": decision, "reasons": ["r"], "confidence": 0.9}


def _approve_gate(state, **kwargs):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def test_pass_path_writes_all_artifacts(tmp_path):
    llm = FakeLLM([_plan(), _exec(1), _review("approve"), _eval("PASS")])
    state = run_task(
        "build a thing", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    run_path = tmp_path / "R20260606_001"
    assert (run_path / "input.md").exists()
    assert (run_path / "planner.output.md").exists()
    assert "artifact-1" in (run_path / "executor.output.md").read_text()
    assert (run_path / "evaluator.output.json").exists()
    assert state.human_feedback.decision == "approve"
    assert state.final_output is not None and "artifact-1" in state.final_output
    saved = json.loads((run_path / "state.json").read_text())
    assert saved["decisions"][-1]["decision"] == "PASS"


def test_needs_fix_then_pass_runs_revision(tmp_path):
    llm = FakeLLM([
        _plan(),
        _exec(1), _review("needs_fix"), _eval("NEEDS_FIX"),
        _exec(2), _review("approve"), _eval("PASS"),
    ])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    run_path = tmp_path / "R20260606_001"
    assert "artifact-2" in (run_path / "executor.output.md").read_text()
    assert (run_path / "executor.output.v1.md").exists()
    assert (run_path / "executor.output.v2.md").exists()
    assert [d["decision"] for d in state.decisions] == ["NEEDS_FIX", "PASS"]


def test_blocked_goes_straight_to_gate(tmp_path):
    llm = FakeLLM([_plan(), _exec(1), _review("needs_fix"), _eval("BLOCKED")])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    assert [d["decision"] for d in state.decisions] == ["BLOCKED"]
    assert state.human_feedback is not None


def test_revisions_exhausted_goes_to_gate(tmp_path):
    # max_revisions=1 -> total 2 attempts, both NEEDS_FIX -> gate
    llm = FakeLLM([
        _plan(),
        _exec(1), _review("needs_fix"), _eval("NEEDS_FIX"),
        _exec(2), _review("needs_fix"), _eval("NEEDS_FIX"),
    ])
    state = run_task(
        "task", llm, tmp_path, max_revisions=1,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    assert len(state.decisions) == 2
    assert all(d["decision"] == "NEEDS_FIX" for d in state.decisions)
    assert state.human_feedback is not None


def test_reject_sets_feedback(tmp_path):
    def reject_gate(state, **kwargs):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")

    llm = FakeLLM([_plan(), _exec(1), _review("approve"), _eval("PASS")])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=reject_gate, printer=lambda *_: None, today="20260606",
    )
    assert state.human_feedback.decision == "reject"


def test_agent_failure_routes_to_blocked_gate_and_persists_state(tmp_path):
    # Planner returns invalid output twice -> AgentError -> BLOCKED -> still reaches gate
    llm = FakeLLM([{"bad": 1}, {"still": "bad"}])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    assert any(d["decision"] == "BLOCKED" for d in state.decisions)
    assert state.human_feedback is not None  # gate was reached, not aborted
    assert (tmp_path / "R20260606_001" / "state.json").exists()


def test_decisions_are_plain_strings_not_enums(tmp_path):
    llm = FakeLLM([_plan(), _exec(1), _review("approve"), _eval("PASS")])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    # content went through model_dump(mode="json") so decision is a str, not an enum member
    assert state.decisions[-1]["decision"] == "PASS"
    assert type(state.decisions[-1]["decision"]) is str
