import pytest

from macr.agent import AgentError, run_agent
from macr.llm import FakeLLM
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def _state():
    return SharedState(run_id="R1", user_query="build a parser")


def test_run_agent_returns_validated_message():
    llm = FakeLLM([{"summary": "plan it", "steps": ["a", "b"], "tools_needed": [], "risks": []}])
    msg = run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="2026-06-06T00:00:00Z")
    assert msg.message_type is MessageType.PLAN
    assert msg.role == "planner"
    assert msg.agent_id == "planner_agent"
    assert msg.content["steps"] == ["a", "b"]
    # forced tool was requested
    assert llm.calls[0]["tool_name"] == "submit_plan"


def test_run_agent_retries_once_on_invalid_then_succeeds():
    llm = FakeLLM([
        {"summary": "missing steps"},  # invalid: steps required -> triggers retry
        {"summary": "ok", "steps": ["x"], "tools_needed": [], "risks": []},
    ])
    msg = run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="t")
    assert msg.content["steps"] == ["x"]
    assert len(llm.calls) == 2
    # the retry user prompt should mention validation failure
    assert "validation" in llm.calls[1]["user"].lower()


def test_run_agent_raises_after_second_failure():
    llm = FakeLLM([{"bad": 1}, {"also": "bad"}])
    with pytest.raises(AgentError):
        run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="t")
