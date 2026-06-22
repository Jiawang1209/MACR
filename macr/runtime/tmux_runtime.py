"""High-level tmux Agent runtime over TmuxControl. One pane = one agent.
Maps long-lived agent_id ↔ ephemeral %pane (agent_id is the identity)."""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from macr.runtime.tmux_control import TmuxControl


@dataclass
class AgentInfo:
    agent_id: str
    pane: str
    pid: int | None = None
    current_command: str | None = None
    dead: bool = False
    dead_status: int | None = None


def _q(s: str) -> str:
    return shlex.quote(s)


def _join_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


_LIST_FMT = ("'#{pane_id}\t#{pane_pid}\t#{pane_current_command}"
             "\t#{pane_dead}\t#{pane_dead_status}'")


class TmuxRuntime:
    def __init__(self, control: TmuxControl) -> None:
        self._c = control
        self._panes: dict[str, str] = {}   # agent_id -> %pane
        self._session: str | None = None

    def open_session(self, name: str) -> str:
        res = self._c.send_command(f"new-session -d -s {name} -P -F '#{{session_id}}'")
        self._session = res.lines[0].strip() if res.lines else None
        return self._session  # type: ignore[return-value]

    def spawn_agent(self, agent_id: str, argv: list[str], cwd: str) -> str:
        res = self._c.send_command(
            f"split-window -d -t {self._session} -c {_q(cwd)} "
            f"-P -F '#{{pane_id}}' {_join_argv(argv)}")
        pane = res.lines[0].strip()
        self._panes[agent_id] = pane
        return pane

    def send_input(self, agent_id: str, text: str) -> None:
        pane = self._panes[agent_id]
        self._c.send_command(f"send-keys -t {pane} -l {_q(text)}")
        self._c.send_command(f"send-keys -t {pane} Enter")

    def snapshot(self, agent_id: str, *, recent: int = 200) -> str:
        pane = self._panes[agent_id]
        # -J joins wrapped lines back into logical lines (long JSON would otherwise
        # be split at the pane width and fail to parse).
        res = self._c.send_command(f"capture-pane -p -t {pane} -S -{recent} -J")
        return "\n".join(res.lines)

    def list_agents(self) -> list[AgentInfo]:
        res = self._c.send_command(f"list-panes -a -F {_LIST_FMT}")
        pane_to_agent = {p: a for a, p in self._panes.items()}
        out: list[AgentInfo] = []
        for line in res.lines:
            cols = line.split("\t")
            if len(cols) < 5:
                continue
            pane, pid, cmd, dead, dead_status = cols[:5]
            aid = pane_to_agent.get(pane)
            if aid is None:
                continue
            out.append(AgentInfo(
                agent_id=aid, pane=pane,
                pid=int(pid) if pid.isdigit() else None,
                current_command=cmd or None,
                dead=(dead == "1"),
                dead_status=int(dead_status) if dead_status.lstrip("-").isdigit() else None,
            ))
        return out

    def kill(self, agent_id: str) -> None:
        pane = self._panes.pop(agent_id, None)
        if pane is not None:
            self._c.send_command(f"kill-pane -t {pane}")

    def agent_for_pane(self, pane: str) -> str | None:
        for aid, p in self._panes.items():
            if p == pane:
                return aid
        return None
