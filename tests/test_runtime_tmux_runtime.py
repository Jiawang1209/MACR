from macr.runtime.tmux_control import FakeTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import AgentInfo, TmuxRuntime


def _begin_end(*lines):
    return ["%begin 1 1 1", *lines, "%end 1 1 1"]


def test_open_session_and_spawn_agent_map_pane():
    t = FakeTmuxTransport()
    t.feed(*_begin_end("$3"))         # open_session → session_id
    t.feed(*_begin_end("%12"))        # spawn_agent → pane_id
    rt = TmuxRuntime(TmuxControl(t))
    assert rt.open_session("team1") == "$3"
    assert rt.spawn_agent("worker-1", ["claude"], cwd="/repo") == "%12"
    assert rt.agent_for_pane("%12") == "worker-1"
    assert any(s.startswith("new-session -d -s team1") and "#{session_id}" in s for s in t.sent)
    assert any(s.startswith("split-window -d -t $3") and "#{pane_id}" in s and s.endswith("claude") for s in t.sent)


def test_send_input_uses_literal_then_enter():
    t = FakeTmuxTransport()
    t.feed(*_begin_end("$3")); t.feed(*_begin_end("%12"))
    t.feed(*_begin_end()); t.feed(*_begin_end())  # send-keys -l ; send-keys Enter
    rt = TmuxRuntime(TmuxControl(t))
    rt.open_session("t"); rt.spawn_agent("w", ["codex"], cwd="/r")
    rt.send_input("w", "do the task")
    assert any(s.startswith("send-keys -t %12 -l ") for s in t.sent)
    assert any(s == "send-keys -t %12 Enter" for s in t.sent)


def test_list_agents_parses_pane_facts_for_known_panes_only():
    t = FakeTmuxTransport()
    t.feed(*_begin_end("$3")); t.feed(*_begin_end("%12"))
    t.feed(*_begin_end(
        "%12\t4242\tclaude\t0\t",
        "%99\t5\tbash\t0\t",
    ))
    rt = TmuxRuntime(TmuxControl(t))
    rt.open_session("t"); rt.spawn_agent("w", ["claude"], cwd="/r")
    infos = rt.list_agents()
    assert infos == [AgentInfo(agent_id="w", pane="%12", pid=4242,
                               current_command="claude", dead=False, dead_status=None)]


def test_list_agents_marks_dead_with_status():
    t = FakeTmuxTransport()
    t.feed(*_begin_end("$3")); t.feed(*_begin_end("%12"))
    t.feed(*_begin_end("%12\t4242\tclaude\t1\t0"))
    rt = TmuxRuntime(TmuxControl(t))
    rt.open_session("t"); rt.spawn_agent("w", ["claude"], cwd="/r")
    info = rt.list_agents()[0]
    assert info.dead is True and info.dead_status == 0
