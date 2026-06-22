from macr.runtime.agent_state import AgentState
from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_control import FakeTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime


def _begin_end(*lines):
    return ["%begin 1 1 1", *lines, "%end 1 1 1"]


def _runtime_with_agent(extra_feeds=()):
    t = FakeTmuxTransport()
    t.feed(*_begin_end("$3")); t.feed(*_begin_end("%12"))
    for f in extra_feeds:
        t.feed(*f)
    rt = TmuxRuntime(TmuxControl(t))
    rt.open_session("t"); rt.spawn_agent("w", ["claude"], cwd="/r")
    return rt


def test_on_output_osc_marker_sets_authoritative_state():
    rt = _runtime_with_agent()
    obs = AgentObserver(rt)
    obs.on_output("%12", "blah \x1b]7748;wispterm-agent;state=waiting_approval;app=claude_code\x07 more")
    d = obs.state_of("w")
    assert d.state is AgentState.waiting_approval and d.confidence == 100


def test_marker_not_overwritten_by_lower_confidence_heuristic():
    rt = _runtime_with_agent(extra_feeds=[_begin_end("Done")])  # capture-pane → done (conf 76)
    obs = AgentObserver(rt)
    obs.on_output("%12", "\x1b]7748;wispterm-agent;state=running;app=claude_code\x07")
    obs.detect_from_snapshot("w", title="claude")
    assert obs.state_of("w").state is AgentState.running  # 100 wins over 76


def test_refresh_from_panes_accepts_prefetched_infos():
    from macr.runtime.tmux_runtime import AgentInfo
    rt = _runtime_with_agent()
    obs = AgentObserver(rt)
    obs.refresh_from_panes([AgentInfo(agent_id="w", pane="%12", dead=True, dead_status=0)])
    assert obs.state_of("w").state is AgentState.done


def test_refresh_from_panes_dead_status_maps_failed_or_done():
    rt = _runtime_with_agent(extra_feeds=[_begin_end("%12\t9\tclaude\t1\t2")])
    obs = AgentObserver(rt)
    obs.refresh_from_panes()
    assert obs.state_of("w").state is AgentState.failed  # nonzero exit
