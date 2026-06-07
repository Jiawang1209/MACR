from macr.discussion_view import ConsoleView, FakeView, SilentView


def _plan():
    return {"summary": "do the thing", "steps": ["step-one", "step-two"]}


def _turn():
    return {"response": "I disagree", "agreements": ["a"], "concerns": ["risky"], "revised_steps": ["r1"]}


def test_console_view_plan_outputs_agent_and_steps():
    out = []
    v = ConsoleView(out=out.append)
    v.plan("claude", _plan())
    joined = "\n".join(out)
    assert "claude" in joined and "do the thing" in joined and "step-one" in joined


def test_console_view_turn_and_interjection_and_consensus():
    out = []
    v = ConsoleView(out=out.append)
    v.turn("codex", 2, _turn())
    v.interjection(2, "please add rollback")
    v.consensus({"summary": "agreed plan"})
    joined = "\n".join(out)
    assert "codex" in joined and "I disagree" in joined and "risky" in joined
    assert "rollback" in joined
    assert "agreed plan" in joined


def test_silent_view_is_noop():
    v = SilentView()
    v.plan("claude", _plan())
    v.turn("codex", 1, _turn())
    v.note("x")
    v.status("y")  # must not raise


def test_fake_view_records_events_in_order():
    v = FakeView()
    v.plan("claude", _plan())
    v.turn("codex", 1, _turn())
    v.interjection(1, "hi")
    v.consensus({"summary": "c"})
    kinds = [e[0] for e in v.events]
    assert kinds == ["plan", "turn", "interjection", "consensus"]
    assert v.events[0][1] == "claude"
    assert v.events[1][1] == "codex" and v.events[1][2] == 1


def test_views_are_context_managers():
    for v in (ConsoleView(out=lambda *_: None), SilentView(), FakeView()):
        with v as entered:
            assert entered is v
