from macr.agents.trace import stream_error


def _jl(*objs):
    import json
    return [json.dumps(o) for o in objs]


def test_codex_error_event():
    lines = _jl({"type": "thread.started"}, {"type": "error", "message": "boom"})
    assert stream_error(lines, source="codex") == "boom"


def test_codex_turn_failed():
    lines = _jl({"type": "turn.started"},
                {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    assert stream_error(lines, source="codex") == "You've hit your usage limit."


def test_claude_error_message():
    lines = _jl({"type": "system"}, {"type": "x", "error": {"message": "claude broke"}})
    assert stream_error(lines, source="claude") == "claude broke"


def test_claude_is_error_result():
    lines = _jl({"type": "result", "is_error": True, "result": "overloaded"})
    assert stream_error(lines, source="claude") == "overloaded"


def test_no_error_returns_none():
    lines = _jl({"type": "turn.started"}, {"type": "turn.completed"})
    assert stream_error(lines, source="codex") is None


def test_non_json_and_empty_are_safe():
    assert stream_error(["not json", "", "   "], source="codex") is None
    assert stream_error([], source="claude") is None
