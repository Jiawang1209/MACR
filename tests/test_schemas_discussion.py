from macr.schemas import ConsensusPlan, DiscussionTurn, SharedState


def test_discussion_turn_defaults():
    t = DiscussionTurn(response="I disagree about X")
    assert t.agreements == [] and t.concerns == [] and t.revised_steps == []


def test_consensus_plan():
    c = ConsensusPlan(summary="do it", steps=["a", "b"], rationale="because")
    assert c.open_questions == []


def test_shared_state_discussion_fields_default():
    s = SharedState(run_id="R1", user_query="q")
    assert s.topic is None
    assert s.discussion == []
    assert s.consensus is None


def test_shared_state_discussion_roundtrip():
    s = SharedState(run_id="R1", user_query="q", topic="build X")
    s.discussion.append({"round": 0, "agent": "claude", "kind": "plan", "content": {"steps": ["a"]}})
    s.consensus = {"summary": "c", "steps": ["a"]}
    d = s.model_dump()
    assert d["topic"] == "build X"
    assert d["discussion"][0]["agent"] == "claude"
    assert d["consensus"]["steps"] == ["a"]
