"""tmux control-mode (`tmux -C`/`-CC`) transport + protocol parser.

Command responses are wrapped in guard lines (cmd-queue.c cmdq_guard):
    %begin <time> <number> <flags>
    …output…
    %end   <time> <number> <flags>     (success)
    %error <time> <number> <flags>     (failure)
Async events are `%`-notifications outside guards (control-notify.c):
    %output %<pane> <data> | %window-add @<w> | %window-close @<w>
    %layout-change @<w> <layout> … | %pause %<p> | %continue %<p> | …
IDs: $=session, @=window, %=pane.
"""
from __future__ import annotations

import select
import subprocess
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class TmuxError(Exception):
    def __init__(self, number: int, lines: list[str]):
        super().__init__(f"tmux command #{number} failed: {' '.join(lines)}")
        self.number = number
        self.lines = lines


class TmuxClosed(Exception):
    pass


@dataclass
class CommandResult:
    number: int
    ok: bool
    lines: list[str] = field(default_factory=list)


@dataclass
class Notification:
    kind: str
    pane: str | None = None
    window: str | None = None
    data: str = ""


@runtime_checkable
class TmuxTransport(Protocol):
    def send_line(self, line: str) -> None: ...
    def read_line(self, timeout: float | None = None) -> str | None: ...
    def close(self) -> None: ...


class FakeTmuxTransport:
    """Test double: `feed(*lines)` queues control output; `sent` records commands."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._inbox: list[str] = []

    def send_line(self, line: str) -> None:
        self.sent.append(line)

    def read_line(self, timeout: float | None = None) -> str | None:
        return self._inbox.pop(0) if self._inbox else None

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def feed(self, *lines: str) -> None:
        self._inbox.extend(lines)


class SubprocessTmuxTransport:
    """Real transport: pipes lines to/from `tmux -C`. Requires tmux on PATH."""

    def __init__(self, tmux_bin: str = "tmux", session: str = "macr-mat") -> None:
        args = [tmux_bin, "-C", "new-session", "-A", "-s", session]
        self._p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def send_line(self, line: str) -> None:
        assert self._p.stdin is not None
        self._p.stdin.write(line + "\n")
        self._p.stdin.flush()

    def read_line(self, timeout: float | None = None) -> str | None:
        assert self._p.stdout is not None
        if timeout is not None:
            r, _, _ = select.select([self._p.stdout], [], [], timeout)
            if not r:
                return None
        line = self._p.stdout.readline()
        return line if line else None

    def close(self) -> None:
        try:
            self.send_line("kill-server")
        except Exception:
            pass
        self._p.terminate()


def _guard_number(line: str) -> int:
    parts = line.split()
    try:
        return int(parts[2])
    except (IndexError, ValueError):
        return -1


def _parse_notification(line: str) -> Notification | None:
    head, _, rest = line.partition(" ")
    kind = head[1:]  # strip leading '%'
    if kind == "output":
        pane, _, data = rest.partition(" ")
        return Notification("output", pane=pane, data=data)
    if kind in ("pause", "continue"):
        return Notification(kind, pane=rest.strip())
    if kind in ("window-add", "window-close",
                "unlinked-window-add", "unlinked-window-close"):
        return Notification(kind, window=rest.strip())
    if kind in ("layout-change", "window-renamed", "window-pane-changed"):
        win, _, data = rest.partition(" ")
        return Notification(kind, window=win, data=data)
    return Notification(kind, data=rest.strip())  # preserve unknown %-events


class TmuxControl:
    def __init__(self, transport: TmuxTransport) -> None:
        self._t = transport
        self._closed = False
        self._pending: list[Notification] = []

    def send_command(self, cmd: str) -> CommandResult:
        if self._closed:
            raise TmuxClosed("tmux control transport is closed")
        self._t.send_line(cmd)
        in_block = False
        number = -1
        lines: list[str] = []
        while True:
            raw = self._t.read_line()
            if raw is None:
                self._closed = True
                raise TmuxClosed("transport closed mid-command")
            line = raw.rstrip("\n")
            if line.startswith("%begin"):
                in_block, number, lines = True, _guard_number(line), []
                continue
            if line.startswith("%end") or line.startswith("%error"):
                ok = line.startswith("%end")
                number = _guard_number(line)
                if not ok:
                    raise TmuxError(number, lines)
                return CommandResult(number=number, ok=True, lines=lines)
            if in_block:
                lines.append(line)
            elif line.startswith("%"):
                n = _parse_notification(line)
                if n is not None:
                    self._pending.append(n)

    def take_pending(self) -> list[Notification]:
        """Return notifications parked during send_command reads, WITHOUT reading
        the transport. Use this when interleaving with send_command calls (e.g. the
        observe loop) so you don't consume not-yet-issued command responses."""
        out = self._pending
        self._pending = []
        return out

    def poll(self, timeout: float | None = None) -> list[Notification]:
        out = list(self._pending)
        self._pending.clear()
        while True:
            raw = self._t.read_line(timeout=timeout)
            if raw is None:
                break
            line = raw.rstrip("\n")
            if line.startswith("%") and not line.startswith(("%begin", "%end", "%error")):
                n = _parse_notification(line)
                if n is not None:
                    out.append(n)
        return out
