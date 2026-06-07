from macr.discussion_view import ConsoleView, FakeView, SilentView, TwoPaneView
from macr.schemas import Decision


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


def test_two_pane_routes_to_buffers():
    v = TwoPaneView(enabled=False)  # no Live; buffers only
    v.plan("claude", {"summary": "csum", "steps": ["cs1"]})
    v.plan("codex", {"summary": "xsum", "steps": ["xs1"]})
    v.turn("claude", 1, {"response": "cresp", "concerns": [], "revised_steps": []})
    v.interjection(1, "human-says")
    v.status("tests passed=True")
    assert any("csum" in l for l in v.claude_lines)
    assert any("xsum" in l for l in v.codex_lines)
    assert any("cresp" in l for l in v.claude_lines)
    assert any("human-says" in l for l in v.status_lines)
    assert any("passed=True" in l for l in v.status_lines)


def test_two_pane_render_contains_text():
    from rich.console import Console
    v = TwoPaneView(enabled=False)
    v.plan("claude", {"summary": "HELLO-CLAUDE", "steps": []})
    v.plan("codex", {"summary": "HELLO-CODEX", "steps": []})
    rec = Console(record=True, width=120)
    rec.print(v._render())
    text = rec.export_text()
    assert "Claude" in text and "Codex" in text
    assert "HELLO-CLAUDE" in text and "HELLO-CODEX" in text


def test_two_pane_non_tty_does_not_start_live():
    v = TwoPaneView(enabled=False)
    with v:
        v.note("x")  # must not raise, no Live
    assert v._live is None


def test_two_pane_control_delegates(monkeypatch):
    from macr.schemas import SharedState
    v = TwoPaneView(enabled=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "c")
    d = v.control(SharedState(run_id="R1", user_query="q", topic="z"), 1)
    assert d.action == "continue"


def _review():
    return {"summary": "rev-sum",
            "findings": [{"level": "blocking", "issue": "missing X", "evidence": "e", "recommendation": "add X"}],
            "decision": "needs_fix"}


def test_console_view_review_and_evaluation_output():
    out = []
    v = ConsoleView(out=out.append)
    v.review(0, _review())
    v.evaluation(0, Decision.NEEDS_FIX)
    joined = "\n".join(out)
    assert "rev-sum" in joined and "missing X" in joined
    assert "NEEDS_FIX" in joined


def test_silent_view_review_evaluation_noop():
    v = SilentView()
    v.review(0, _review())
    v.evaluation(0, Decision.PASS)  # must not raise


def test_fake_view_records_review_and_evaluation():
    v = FakeView()
    v.review(1, _review())
    v.evaluation(1, Decision.PASS)
    assert ("review", 1, _review()) == v.events[0]
    assert v.events[1] == ("evaluation", 1, Decision.PASS)


def test_two_pane_view_review_goes_to_status_lines():
    v = TwoPaneView(enabled=False)
    v.review(0, _review())
    v.evaluation(0, Decision.NEEDS_FIX)
    joined = "\n".join(v.status_lines)
    assert "rev-sum" in joined and "NEEDS_FIX" in joined
