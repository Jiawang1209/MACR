import json

import pytest

from macr.agent import AgentError
from macr.agents.base import ProcResult, FakeProcessRunner
from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
from macr.agents.trace import TraceSink
from macr.collab_roles import EXECUTOR_C, PLANNER_C
from macr.schemas import SharedState


def _claude_stream(inner: dict, *, with_sub: bool = False) -> str:
    lines = []
    if with_sub:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_s1", "name": "Agent",
             "input": {"subagent_type": "Explore"}}]}, "parent_tool_use_id": None}))
        lines.append(json.dumps({"type": "stream_event", "event": {}, "parent_tool_use_id": "toolu_s1"}))
    lines.append(json.dumps({"type": "result", "result": json.dumps(inner), "session_id": "s1"}))
    return "\n".join(lines)


def _codex_stream(inner: dict, *, with_sub: bool = False) -> str:
    lines = [json.dumps({"type": "thread.started", "thread_id": "root"})]
    if with_sub:
        lines.append(json.dumps({"type": "thread.started", "thread_id": "sub-1"}))
    lines.append(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(inner)}}))
    lines.append(json.dumps({"type": "turn.completed"}))
    return "\n".join(lines)


def _plan():
    return {"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}


def test_claude_streaming_parses_and_argv_has_agent_and_cwd():
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner, model="claude-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    call = runner.calls[0]
    argv = call["argv"]
    assert argv[0] == "claude" and "--output-format" in argv and "stream-json" in argv
    assert "--allowedTools" in argv
    tools = argv[argv.index("--allowedTools") + 1]
    assert "Agent" in tools
    assert call["cwd"] == "/tmp/wt"


def test_claude_no_subagents_drops_agent_tool():
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner, enable_subagents=False)
    state = SharedState(run_id="R1", user_query="task")
    backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    argv = runner.calls[0]["argv"]
    tools = argv[argv.index("--allowedTools") + 1]
    assert "Agent" not in tools


def test_claude_captures_trace(tmp_path):
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan(), with_sub=True), "")])
    backend = ClaudeCliBackend(runner=runner)
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="task")
    backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t", trace=sink)
    assert (tmp_path / "planner.v1.events.jsonl").exists()
    assert len(sink.records) == 1 and sink.records[0].agent_type == "Explore"


def test_claude_nonzero_exit_raises():
    runner = FakeProcessRunner([ProcResult(1, "", "boom"), ProcResult(1, "", "boom")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_claude_empty_result_retries_then_raises():
    empty = json.dumps({"type": "turn.completed"})
    runner = FakeProcessRunner([ProcResult(0, empty, ""), ProcResult(0, empty, "")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_codex_streaming_parses_and_argv():
    inner = {"artifact": "edited", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner), "")])
    backend = CodexCliBackend(runner=runner, model="gpt-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["artifact"] == "edited"
    argv = runner.calls[0]["argv"]
    assert argv[0] == "codex" and argv[1] == "exec"
    assert "--json" in argv and "--cd" in argv and "/tmp/wt" in argv
    # codex exec is non-interactive and has no approval flag (regression: dogfood found
    # `codex exec` rejects --ask-for-approval on codex >=0.137)
    assert "--sandbox" in argv and "--ask-for-approval" not in argv


def test_codex_no_subagents_disables_multi_agent():
    inner = {"artifact": "x", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner), "")])
    backend = CodexCliBackend(runner=runner, enable_subagents=False)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    argv = runner.calls[0]["argv"]
    assert "features.multi_agent=false" in argv


def test_codex_captures_trace(tmp_path):
    inner = {"artifact": "x", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner, with_sub=True), "")])
    backend = CodexCliBackend(runner=runner)
    sink = TraceSink(tmp_path, "executor.v1")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t", trace=sink)
    assert (tmp_path / "executor.v1.subagents.json").exists()
    assert len(sink.records) == 1 and sink.records[0].ref == "sub-1"


def test_claude_capture_failure_does_not_crash_run(tmp_path):
    class _BadSink(TraceSink):
        def capture(self, raw_lines, subagents):
            raise OSError("disk full")

    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner)
    bad = _BadSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t", trace=bad)
    assert msg.content["steps"] == ["a"]  # run succeeds despite capture failure


def test_codex_nonzero_surfaces_stream_error_over_stderr():
    from macr.agent import AgentError
    from macr.agents.base import FakeProcessRunner, ProcResult

    stdout = '{"type":"turn.started"}\n{"type":"turn.failed","error":{"message":"usage limit"}}'
    runner = FakeProcessRunner([ProcResult(1, stdout, "Reading additional input from stdin...")])
    backend = CodexCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    with pytest.raises(AgentError) as ei:
        backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert "usage limit" in str(ei.value)
    assert "Reading additional input" not in str(ei.value)


def test_claude_argv_contract():
    """Pin the exact claude CLI flags we send — regression guard against arg drift.

    Fakes can only freeze the contract we *think* the CLI has (dogfood finding 5,
    where a fake test froze a wrong codex flag). This pins claude's argv explicitly.
    """
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner, model="claude-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    argv = runner.calls[0]["argv"]
    assert argv[0] == "claude"
    assert "-p" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--include-partial-messages" in argv
    assert "--allowedTools" in argv
    assert argv[argv.index("--model") + 1] == "claude-x"
    # codex's removed approval flag must never leak onto the claude argv either
    assert "--ask-for-approval" not in argv


def test_codex_sandbox_value_reaches_argv():
    """The configured sandbox flows to `codex exec --sandbox <value>` (guards dogfood finding 1).

    discuss wires read-only for the reviewer codex and workspace-write for the impl codex;
    if that wiring drifts, the reviewer could gain write access or the impl lose it.
    """
    for sandbox in ("read-only", "workspace-write"):
        inner = {"artifact": "x", "notes": "", "evidence": []}
        runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner), "")])
        backend = CodexCliBackend(runner=runner, sandbox=sandbox)
        state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
        backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
        argv = runner.calls[0]["argv"]
        assert argv[0] == "codex" and argv[1] == "exec"
        assert argv[argv.index("--sandbox") + 1] == sandbox
        # codex exec is non-interactive and rejects this flag (dogfood finding 1/5)
        assert "--ask-for-approval" not in argv


def test_codex_nonzero_falls_back_to_stderr_when_no_stream_error():
    from macr.agent import AgentError
    from macr.agents.base import FakeProcessRunner, ProcResult

    runner = FakeProcessRunner([ProcResult(2, "", "boom on stderr")])
    backend = CodexCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    with pytest.raises(AgentError) as ei:
        backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert "boom on stderr" in str(ei.value)
