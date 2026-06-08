from macr.web.live import WebView
from macr.web.session import RunSession


def _events_of_type(session, t):
    return [e for e in session.events if e["type"] == t]


def test_webview_plan_emits_stage_event():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.plan("claude", {"summary": "the plan", "steps": ["a", "b"]})
    stages = _events_of_type(s, "stage")
    assert len(stages) == 1
    st = stages[0]["stage"]
    assert st["kind"] == "plan" and st["agent"] == "claude"
    assert st["body"]["summary"] == "the plan" and st["body"]["steps"] == ["a", "b"]


def test_webview_consensus_and_evaluation_and_note():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.consensus({"summary": "agreed", "steps": ["x"], "rationale": "r"})
    v.evaluation(0, "PASS")
    v.note("hello")
    kinds = [e["stage"]["kind"] for e in _events_of_type(s, "stage")]
    assert "consensus" in kinds and "evaluator" in kinds
    assert _events_of_type(s, "note")[0]["text"] == "hello"


def test_webview_printer_emits_note():
    s = RunSession(run_id="R1", command="collab")
    v = WebView(s)
    v.printer("[tests #1] passed=True")
    assert _events_of_type(s, "note")[0]["text"] == "[tests #1] passed=True"
