from macr.human_gate import interactive_human_gate
from macr.schemas import SharedState


def _state_with_artifact():
    s = SharedState(run_id="R1", user_query="q")
    s.agent_outputs["executor"].append({"artifact": "FINAL ART", "notes": "", "evidence": []})
    return s


def test_approve():
    out = []
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: "a", printer=out.append,
        timestamp="2026-06-06T00:00:00Z",
    )
    assert hf.decision == "approve" and hf.feedback == ""
    assert any("FINAL ART" in line for line in out)


def test_reject_collects_reason():
    answers = iter(["r", "not good enough"])
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: next(answers), printer=lambda *_: None,
        timestamp="t",
    )
    assert hf.decision == "reject" and hf.feedback == "not good enough"


def test_edit_is_approve_with_feedback():
    answers = iter(["e", "tweak the wording"])
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: next(answers), printer=lambda *_: None,
        timestamp="t",
    )
    assert hf.decision == "approve" and hf.feedback == "tweak the wording"
