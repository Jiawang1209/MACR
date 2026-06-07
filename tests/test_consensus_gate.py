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
