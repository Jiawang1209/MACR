"""Fuse three observation signals into a per-agent Detection:
  on_output         — OSC 7748 markers in %output (confidence 100, reported)
  refresh_from_panes— tmux pane_dead/current_command (process facts, observed)
  detect_from_snapshot — capture-pane screen heuristic (observed, 70..92)
Higher confidence overrides lower; equal confidence = newer wins. Never emits
verified/approved — that's the control plane's Stage D gate + human gate."""
from __future__ import annotations

import re

from macr.runtime.agent_state import (
    AgentApp, AgentState, Detection, detect, parse_marker,
)
from macr.runtime.tmux_runtime import AgentInfo, TmuxRuntime

# OSC 7748 ; <payload> ST, where ST is BEL (\x07) or ESC \ (\x1b\\)
_OSC7748 = re.compile(r"\x1b\]7748;([^\x07\x1b]*)(?:\x07|\x1b\\)")


class AgentObserver:
    def __init__(self, runtime: TmuxRuntime) -> None:
        self._rt = runtime
        self._state: dict[str, Detection] = {}

    def on_output(self, pane: str, data: str) -> None:
        agent_id = self._rt.agent_for_pane(pane)
        if agent_id is None:
            return
        latest: Detection | None = None
        for m in _OSC7748.finditer(data):
            det = parse_marker(m.group(1))
            if det is not None:
                latest = det
        if latest is not None:
            self._apply(agent_id, latest)

    def refresh_from_panes(self, infos: "list[AgentInfo] | None" = None) -> None:
        for info in (infos if infos is not None else self._rt.list_agents()):
            if info.dead:
                state = AgentState.done if info.dead_status == 0 else AgentState.failed
                # process exit is a hard fact — authoritative (beats a stale marker)
                self._apply(info.agent_id,
                            Detection(app=_app_of(info), state=state, confidence=100))

    def detect_from_snapshot(self, agent_id: str, *, title: str = "") -> None:
        det = detect(title, self._rt.snapshot(agent_id))
        if det.visible():
            self._apply(agent_id, det)

    def state_of(self, agent_id: str) -> Detection:
        return self._state.get(agent_id, Detection())

    def _apply(self, agent_id: str, det: Detection) -> None:
        cur = self._state.get(agent_id)
        if cur is None or det.confidence >= cur.confidence:
            self._state[agent_id] = det


def _app_of(info: AgentInfo) -> AgentApp:
    cmd = (info.current_command or "").lower()
    if "codex" in cmd:
        return AgentApp.codex
    if "claude" in cmd:
        return AgentApp.claude_code
    return AgentApp.none
