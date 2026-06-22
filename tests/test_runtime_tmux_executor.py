import json

import pytest

from macr.agent import AgentError
from macr.collab_roles import EXECUTOR_C
from macr.runtime.agent_state import AgentState
from macr.runtime.tmux_control import FakeTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime
from macr.runtime.tmux_executor import TmuxExecutorBackend
from macr.schemas import SharedState


def _be(*lines):
    return ["%begin 1 1 1", *lines, "%end 1 1 1"]


def _codex_final_line(obj):
    # codex --json: final agent message carried in an item.completed event
    return json.dumps({"type": "item.completed",
                       "item": {"type": "agent_message", "text": json.dumps(obj)}})


def _state(tmp_path):
    return SharedState(run_id="R1", user_query="do it", worktree_path=str(tmp_path))


def test_run_role_spawns_observes_and_returns_executor_output(tmp_path):
    t = FakeTmuxTransport()
    exec_obj = {"artifact": "added hello()", "notes": "ok", "evidence": []}
    t.feed(*_be())                                                  # set-option remain-on-exit
    t.feed(*_be("%12"))                                              # spawn → %pane
    t.feed("%output %12 \x1b]7748;wispterm-agent;state=running;app=codex\x07")  # interleaved OSC
    t.feed(*_be("%12\t9\tcodex\t0\t"))                              # iter1: alive
    t.feed(*_be("%12\t9\tcodex\t1\t0"))                            # iter2: dead status 0
    t.feed(*_be(_codex_final_line(exec_obj)))                       # snapshot output

    obs_events = []
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0, obs_sink=obs_events.append)
    msg = be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")

    assert msg.content["artifact"] == "added hello()"
    assert any(s.startswith("split-window") and "codex exec" in s and "--json" in s for s in t.sent)
    states = {e["state"] for e in obs_events}
    assert AgentState.running.value in states
    assert AgentState.done.value in states


def test_nonzero_exit_raises_agent_error(tmp_path):
    t = FakeTmuxTransport()
    t.feed(*_be())                                                 # set-option remain-on-exit
    t.feed(*_be("%12"))                                            # spawn
    t.feed(*_be("%12\t9\tcodex\t1\t3"))                            # dead, status 3
    t.feed(*_be(json.dumps({"type": "error", "message": "boom"}))) # snapshot output
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0)
    with pytest.raises(AgentError) as ei:
        be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")
    assert "exited 3" in str(ei.value) and "boom" in str(ei.value)


def test_timeout_kills_and_raises(tmp_path):
    t = FakeTmuxTransport()
    t.feed(*_be())                                                 # set-option remain-on-exit
    t.feed(*_be("%12"))                                            # spawn
    t.feed(*_be("%12\t9\tcodex\t0\t"))                            # iter1 alive
    t.feed(*_be())                                                 # kill-pane response
    clock = iter([0.0, 5.0, 5.0])                                  # start; check > deadline(1)
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0, timeout=1, time_fn=lambda: next(clock))
    with pytest.raises(AgentError) as ei:
        be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")
    assert "timed out" in str(ei.value)
    assert any(s.startswith("kill-pane") for s in t.sent)
