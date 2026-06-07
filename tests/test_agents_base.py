import pytest

from macr.agent import AgentError
from macr.agents.base import (
    FakeAgentBackend,
    FakeProcessRunner,
    ProcResult,
    extract_json_object,
    message_from_content,
    validate_with_retry,
)
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def test_extract_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_from_fence_and_prose():
    text = "Here you go:\n```json\n{\"a\": 2, \"b\": [1,2]}\n```\nDone."
    assert extract_json_object(text) == {"a": 2, "b": [1, 2]}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_validate_with_retry_success_first_try():
    calls = []

    def call_fn(extra):
        calls.append(extra)
        return {"summary": "ok", "steps": ["a"], "tools_needed": [], "risks": []}

    model = validate_with_retry(PLANNER, call_fn)
    assert model.steps == ["a"]
    assert calls == [""]  # no retry


def test_validate_with_retry_retries_then_succeeds():
    seq = [{"summary": "bad"}, {"summary": "ok", "steps": ["x"], "tools_needed": [], "risks": []}]

    def call_fn(extra):
        return seq.pop(0)

    model = validate_with_retry(PLANNER, call_fn)
    assert model.steps == ["x"]


def test_validate_with_retry_raises_after_two():
    def call_fn(extra):
        return {"summary": "bad"}

    with pytest.raises(AgentError):
        validate_with_retry(PLANNER, call_fn)


def test_message_from_content():
    from macr.schemas import PlannerOutput

    msg = message_from_content(
        PLANNER, PlannerOutput(summary="s", steps=["a"]),
        run_id="R1", task_id="R1", timestamp="t",
    )
    assert msg.role == "planner" and msg.message_type is MessageType.PLAN
    assert msg.content["steps"] == ["a"]


def test_fake_process_runner_pops_and_records():
    fr = FakeProcessRunner([ProcResult(0, "out", "")])
    res = fr.run(["claude", "-p", "x"], cwd="/tmp")
    assert res.stdout == "out"
    assert fr.calls[0]["argv"][0] == "claude"


def test_fake_agent_backend_returns_scripted_and_calls_hook():
    edited = []
    fab = FakeAgentBackend(
        {"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]},
        on_run=lambda role, state: edited.append(role.name),
    )
    state = SharedState(run_id="R1", user_query="q")
    msg = fab.run_role(PLANNER, state, run_id="R1", task_id="R1")
    assert msg.content["steps"] == ["a"]
    assert edited == ["planner"]


def test_subprocess_runner_timeout_raises_agent_error():
    import pytest
    from macr.agents.base import SubprocessRunner
    from macr.agent import AgentError

    runner = SubprocessRunner()
    with pytest.raises(AgentError):
        runner.run(["python", "-c", "import time; time.sleep(5)"], timeout=1)


def test_extract_json_ignores_trailing_prose():
    assert extract_json_object('{"a": {"b": 1}} -- done }') == {"a": {"b": 1}}


def test_extract_json_takes_first_of_multiple():
    assert extract_json_object('{"a": 1}\n{"b": 2}') == {"a": 1}
