import pytest
from pydantic import ValidationError

from macr.schemas import (
    Decision,
    EvaluatorOutput,
    ExecutorOutput,
    Finding,
    HumanFeedback,
    Message,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_message_type_values():
    assert MessageType.PROPOSAL.value == "proposal"
    assert MessageType.EVALUATION.value == "evaluation"


def test_decision_enum():
    assert Decision.PASS.value == "PASS"
    assert {d.value for d in Decision} == {"PASS", "NEEDS_FIX", "BLOCKED"}


def test_planner_output_defaults():
    p = PlannerOutput(summary="do it", steps=["a", "b"])
    assert p.tools_needed == [] and p.risks == []


def test_reviewer_output_requires_decision():
    with pytest.raises(ValidationError):
        ReviewerOutput(summary="x")  # missing decision


def test_reviewer_finding_roundtrip():
    r = ReviewerOutput(
        summary="ok",
        findings=[Finding(level="blocking", issue="i", evidence="e", recommendation="r")],
        decision="needs_fix",
    )
    assert r.findings[0].level == "blocking"


def test_evaluator_output():
    e = EvaluatorOutput(decision=Decision.PASS, reasons=["good"], confidence=0.9)
    assert e.decision is Decision.PASS


def test_executor_output_defaults():
    ex = ExecutorOutput(artifact="hello")
    assert ex.notes == "" and ex.evidence == []


def test_shared_state_default_buckets():
    s = SharedState(run_id="R1", user_query="q")
    assert set(s.agent_outputs) == {"planner", "executor", "reviewer", "evaluator"}
    assert s.human_feedback is None and s.final_output is None


def test_human_feedback():
    hf = HumanFeedback(decision="approve", feedback="", timestamp="2026-06-06T00:00:00Z")
    assert hf.decision == "approve"


def test_message_construct():
    m = Message(
        task_id="T1", run_id="R1", agent_id="planner_agent", role="planner",
        message_type=MessageType.PLAN, content={"summary": "x"},
        timestamp="2026-06-06T00:00:00Z",
    )
    assert m.status == "submitted"
