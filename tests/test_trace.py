import json

from macr.agents.trace import TraceSink, parse_claude_stream, parse_codex_stream
from macr.schemas import SubagentRecord


def test_parse_claude_stream_extracts_result_and_subagent():
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_sub1", "name": "Agent",
             "input": {"subagent_type": "Explore", "prompt": "look"}}]},
            "parent_tool_use_id": None}),
        json.dumps({"type": "stream_event", "event": {"type": "x"}, "parent_tool_use_id": "toolu_sub1"}),
        json.dumps({"type": "result", "result": '{"summary":"p","steps":["a"]}', "session_id": "s1"}),
    ]
    final_text, subs = parse_claude_stream(lines)
    assert json.loads(final_text)["steps"] == ["a"]
    assert len(subs) == 1
    assert subs[0].source == "claude" and subs[0].agent_type == "Explore" and subs[0].ref == "toolu_sub1"


def test_parse_claude_stream_tolerates_garbage_and_missing_result():
    final_text, subs = parse_claude_stream(["not json", json.dumps({"type": "assistant"})])
    assert final_text == ""
    assert subs == []


def test_parse_codex_stream_extracts_message_and_subthread():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "root"}),
        json.dumps({"type": "thread.started", "thread_id": "sub-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                                                       "text": '{"artifact":"x","notes":"","evidence":[]}'}}),
        json.dumps({"type": "turn.completed"}),
    ]
    final_text, subs = parse_codex_stream(lines)
    assert json.loads(final_text)["artifact"] == "x"
    assert len(subs) == 1
    assert subs[0].source == "codex" and subs[0].ref == "sub-1"


def test_parse_codex_stream_tolerates_garbage():
    final_text, subs = parse_codex_stream(["", "{bad", json.dumps({"type": "turn.completed"})])
    assert final_text == "" and subs == []


def test_parse_claude_stream_ignores_non_string_parent():
    import json as _json
    final_text, subs = parse_claude_stream([
        _json.dumps({"parent_tool_use_id": {"x": 1}}),
        _json.dumps({"parent_tool_use_id": ["y"]}),
    ])
    assert subs == [] and final_text == ""


def test_parse_codex_stream_ignores_non_string_thread_id():
    import json as _json
    lines = [
        _json.dumps({"type": "thread.started", "thread_id": 1}),
        _json.dumps({"type": "thread.started", "thread_id": 2}),
    ]
    final_text, subs = parse_codex_stream(lines)
    assert subs == [] and final_text == ""


def test_trace_sink_capture_writes_two_files(tmp_path):
    sink = TraceSink(tmp_path / "subagents", "planner.v1")
    sink.capture(['{"a":1}', '{"b":2}'],
                 [SubagentRecord(source="claude", agent_type="Explore", ref="r1")])
    events = (tmp_path / "subagents" / "planner.v1.events.jsonl").read_text()
    assert '{"a":1}' in events and '{"b":2}' in events
    summary = json.loads((tmp_path / "subagents" / "planner.v1.subagents.json").read_text())
    assert summary[0]["agent_type"] == "Explore"
    assert sink.records[0].ref == "r1"
