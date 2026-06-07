from macr.human_gate import consensus_human_gate
from macr.schemas import SharedState


def _state():
    s = SharedState(run_id="R1", user_query="q", topic="z")
    s.consensus = {"summary": "agreed plan", "steps": ["s1", "s2"], "rationale": "r", "open_questions": []}
    return s


def test_consensus_gate_shows_consensus_and_approves():
    out = []
    hf = consensus_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    assert hf.decision == "approve"
    assert any("agreed plan" in line for line in out)


def test_consensus_gate_reject():
    answers = iter(["r", "not good"])
    hf = consensus_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "reject" and hf.feedback == "not good"


def _state_with_review(decision="needs_fix", eval_decision="NEEDS_FIX"):
    s = _state()
    s.reviews.append({"summary": "rev", "decision": decision,
                      "findings": [{"level": "blocking", "issue": "missing rollback",
                                    "evidence": "e", "recommendation": "add rollback step"}]})
    s.decisions.append({"stage": "plan_review", "attempt": 0, "decision": eval_decision})
    return s


def test_consensus_gate_shows_plan_review_when_present():
    out = []
    consensus_human_gate(_state_with_review(), input_fn=lambda p: "a",
                         printer=out.append, timestamp="t")
    joined = "\n".join(out)
    assert "Plan review" in joined or "计划审查" in joined
    assert "missing rollback" in joined
    assert "NEEDS_FIX" in joined


def test_consensus_gate_no_review_is_backward_compatible():
    out = []
    consensus_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    joined = "\n".join(out)
    assert "agreed plan" in joined
    assert "Plan review" not in joined and "计划审查" not in joined
