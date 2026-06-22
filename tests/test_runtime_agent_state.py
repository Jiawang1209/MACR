from macr.runtime.agent_state import (
    AgentApp, AgentState, Detection, parse_marker,
)


def test_parse_marker_authoritative_detection():
    d = parse_marker("wispterm-agent;state=running;app=claude_code")
    assert d == Detection(app=AgentApp.claude_code, state=AgentState.running, confidence=100)
    assert d.visible()


def test_parse_marker_state_only_defaults_app_none():
    d = parse_marker("wispterm-agent;state=waiting_approval")
    assert d.app is AgentApp.none and d.state is AgentState.waiting_approval and d.confidence == 100


def test_parse_marker_rejects_wrong_tag_or_missing_or_unknown_state():
    assert parse_marker("other;state=running") is None
    assert parse_marker("wispterm-agent;app=claude_code") is None
    assert parse_marker("wispterm-agent;state=bogus") is None


from macr.runtime.agent_state import detect, aggregate


def test_detect_picks_latest_state_marker_for_known_app():
    out = "claude working...\nesc to interrupt\nDo you want to proceed?"
    d = detect("claude", out)
    assert d.app is AgentApp.claude_code and d.state is AgentState.waiting_approval
    assert 0 < d.confidence < 100


def test_detect_running_then_done_order_matters():
    assert detect("codex", "esc to interrupt\n...\nDone").state is AgentState.done
    assert detect("codex", "Done\n...\nesc to interrupt").state is AgentState.running


def test_detect_unknown_app_is_invisible():
    assert detect("vim", "just editing").visible() is False


def test_aggregate_attention_priority():
    assert aggregate([AgentState.running, AgentState.waiting_approval, AgentState.done]) is AgentState.waiting_approval
    assert aggregate([AgentState.done, AgentState.running]) is AgentState.running
    assert aggregate([]) is AgentState.none
