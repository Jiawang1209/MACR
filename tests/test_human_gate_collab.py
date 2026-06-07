from macr.human_gate import collab_human_gate
from macr.schemas import SharedState


def _state():
    s = SharedState(run_id="R1", user_query="q")
    s.diffs.append("DIFF-BODY")
    s.test_results.append({"command": "t", "passed": True, "exit_code": 0, "log": "ok"})
    return s


def test_collab_gate_shows_diff_and_test_then_approves():
    out = []
    hf = collab_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    assert hf.decision == "approve"
    assert any("DIFF-BODY" in line for line in out)


def test_collab_gate_reject_collects_reason():
    answers = iter(["r", "no good"])
    hf = collab_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "reject" and hf.feedback == "no good"


def test_collab_gate_edit_is_approve_with_feedback():
    answers = iter(["e", "tweak it"])
    hf = collab_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "approve" and hf.feedback == "tweak it"
