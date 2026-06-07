import pytest

from macr.agent import AgentError
from macr.agents.base import FakeAgentBackend, validate_with_retry
from macr.agents.trace import TraceSink
from macr.roles import PLANNER
from macr.schemas import SharedState, SubagentRecord


def test_validate_with_retry_retries_on_parse_valueerror_then_raises():
    def call_fn(extra):
        raise ValueError("no JSON object found")

    with pytest.raises(AgentError):
        validate_with_retry(PLANNER, call_fn)


def test_fake_agent_backend_accepts_and_ignores_trace_without_script(tmp_path):
    fab = FakeAgentBackend({"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]})
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="q")
    msg = fab.run_role(PLANNER, state, run_id="R1", task_id="R1", trace=sink)
    assert msg.content["steps"] == ["a"]
    assert sink.records == []


def test_fake_agent_backend_captures_scripted_subagents(tmp_path):
    fab = FakeAgentBackend(
        {"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]},
        subagents={"planner": [SubagentRecord(source="claude", agent_type="Explore", ref="r1")]},
    )
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="q")
    fab.run_role(PLANNER, state, run_id="R1", task_id="R1", trace=sink)
    assert len(sink.records) == 1 and sink.records[0].agent_type == "Explore"
    assert (tmp_path / "planner.v1.subagents.json").exists()
