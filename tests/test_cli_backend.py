import json

import pytest

from macr.agent import AgentError
from macr.agents.base import ProcResult, FakeProcessRunner
from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
from macr.collab_roles import EXECUTOR_C, PLANNER_C
from macr.schemas import SharedState


def _plan_dict():
    return {"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}


def _claude_envelope(inner: dict) -> str:
    return json.dumps({"type": "result", "result": json.dumps(inner)})


def test_claude_backend_parses_and_builds_message():
    runner = FakeProcessRunner([ProcResult(0, _claude_envelope(_plan_dict()), "")])
    backend = ClaudeCliBackend(runner=runner, model="claude-x")
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    argv = runner.calls[0]["argv"]
    assert argv[0] == "claude" and "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--model" in argv and "claude-x" in argv


def test_claude_backend_retries_on_invalid():
    runner = FakeProcessRunner([
        ProcResult(0, _claude_envelope({"summary": "bad"}), ""),
        ProcResult(0, _claude_envelope(_plan_dict()), ""),
    ])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    assert len(runner.calls) == 2


def test_claude_backend_nonzero_exit_raises():
    runner = FakeProcessRunner([ProcResult(1, "", "boom"), ProcResult(1, "", "boom")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_codex_backend_parses_stdout_and_passes_worktree():
    exec_json = {"artifact": "edited main.py", "notes": "", "evidence": ["main.py"]}
    stdout = "working...\nDone. " + json.dumps(exec_json)
    runner = FakeProcessRunner([ProcResult(0, stdout, "")])
    backend = CodexCliBackend(runner=runner, model="gpt-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["artifact"] == "edited main.py"
    argv = runner.calls[0]["argv"]
    assert argv[0] == "codex" and argv[1] == "exec"
    assert "--cd" in argv and "/tmp/wt" in argv
    assert "--sandbox" in argv and "workspace-write" in argv
    assert "--ask-for-approval" in argv and "never" in argv
    assert "--model" in argv and "gpt-x" in argv
