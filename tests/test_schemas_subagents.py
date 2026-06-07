from macr.schemas import SharedState, SubagentRecord


def test_subagent_record_defaults():
    r = SubagentRecord(source="claude", ref="toolu_1")
    assert r.agent_type == "unknown"
    assert r.source == "claude"
    assert r.ref == "toolu_1"


def test_shared_state_subagents_default_and_roundtrip():
    s = SharedState(run_id="R1", user_query="q")
    assert s.subagents == []
    s.subagents.append({"role": "planner", "attempt": 1, "count": 2, "types": ["Explore"]})
    assert s.model_dump()["subagents"][0]["count"] == 2
