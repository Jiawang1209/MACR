from macr.agents.api_backend import ApiBackend
from macr.llm import FakeLLM
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def test_api_backend_delegates_to_run_agent():
    llm = FakeLLM([{"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}])
    backend = ApiBackend(llm)
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER, state, run_id="R1", task_id="R1", timestamp="t")
    assert backend.name == "api"
    assert msg.message_type is MessageType.PLAN
    assert msg.content["steps"] == ["a"]
