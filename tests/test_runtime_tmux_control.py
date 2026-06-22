import pytest

from macr.runtime.tmux_control import (
    FakeTmuxTransport, Notification, TmuxControl, TmuxError,
)


def test_send_command_pairs_begin_end_and_returns_lines():
    t = FakeTmuxTransport()
    t.feed("%begin 1700000000 5 1", "$2", "%end 1700000000 5 1")
    c = TmuxControl(t)
    res = c.send_command("new-session -P -F '#{session_id}'")
    assert t.sent == ["new-session -P -F '#{session_id}'"]
    assert res.ok and res.number == 5 and res.lines == ["$2"]


def test_send_command_error_raises():
    t = FakeTmuxTransport()
    t.feed("%begin 1700000000 6 1", "no current session", "%error 1700000000 6 1")
    c = TmuxControl(t)
    with pytest.raises(TmuxError) as ei:
        c.send_command("split-window")
    assert ei.value.number == 6 and "no current session" in " ".join(ei.value.lines)


def test_notifications_interleaved_then_polled():
    t = FakeTmuxTransport()
    t.feed("%output %12 hello world",
           "%begin 1 7 1", "%end 1 7 1",
           "%window-add @3", "%layout-change @3 abc,80x24 abc,80x24 *",
           "%pause %12")
    c = TmuxControl(t)
    res = c.send_command("list-panes")
    assert res.ok
    notes = c.poll()
    kinds = [(n.kind, n.pane, n.window) for n in notes]
    assert ("output", "%12", None) in kinds
    assert ("window-add", None, "@3") in kinds
    assert ("layout-change", None, "@3") in kinds
    assert ("pause", "%12", None) in kinds
    out = next(n for n in notes if n.kind == "output")
    assert out.data == "hello world"
