from macr.discussion_control import (
    ControlDecision,
    auto_discussion_control,
    interactive_discussion_control,
)
from macr.schemas import SharedState


def _state():
    return SharedState(run_id="R1", user_query="q", topic="z")


def test_auto_always_continue():
    d = auto_discussion_control(_state(), 1, printer=lambda *_: None)
    assert d.action == "continue" and d.interjection == ""


def test_interactive_continue():
    d = interactive_discussion_control(_state(), 1, input_fn=lambda p: "c", printer=lambda *_: None)
    assert d.action == "continue"


def test_interactive_interject():
    answers = iter(["i", "please add rollback"])
    d = interactive_discussion_control(_state(), 1, input_fn=lambda p: next(answers), printer=lambda *_: None)
    assert d.action == "interject" and d.interjection == "please add rollback"


def test_interactive_end_and_abort():
    assert interactive_discussion_control(_state(), 1, input_fn=lambda p: "e", printer=lambda *_: None).action == "end"
    assert interactive_discussion_control(_state(), 1, input_fn=lambda p: "a", printer=lambda *_: None).action == "abort"


def test_control_decision_default():
    assert ControlDecision(action="continue").interjection == ""
