from macr.runtime.agent_state import AgentState
from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_control import FakeTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime


def _be(*lines):
    return ["%begin 1 1 1", *lines, "%end 1 1 1"]


def test_one_terminal_two_agents_observed():
    t = FakeTmuxTransport()
    t.feed(*_be("$3"))     # open_session
    t.feed(*_be("%12"))    # spawn worker-1 (claude)
    t.feed(*_be("%13"))    # spawn worker-2 (codex)
    rt = TmuxRuntime(TmuxControl(t))
    obs = AgentObserver(rt)

    rt.open_session("team")
    rt.spawn_agent("worker-1", ["claude"], cwd="/repo")
    rt.spawn_agent("worker-2", ["codex"], cwd="/repo")

    # two agents emit different authoritative states on their panes
    obs.on_output("%12", "\x1b]7748;wispterm-agent;state=running;app=claude_code\x07")
    obs.on_output("%13", "\x1b]7748;wispterm-agent;state=waiting_approval;app=codex\x07")
    assert obs.state_of("worker-1").state is AgentState.running
    assert obs.state_of("worker-2").state is AgentState.waiting_approval

    # worker-1's process then exits cleanly → done; worker-2 still alive
    t.feed(*_be("%12\t9\tclaude\t1\t0", "%13\t10\tcodex\t0\t"))
    obs.refresh_from_panes()
    assert obs.state_of("worker-1").state is AgentState.done
    assert obs.state_of("worker-2").state is AgentState.waiting_approval
