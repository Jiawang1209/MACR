"""Agent run-state vocabulary + detection. Ported from WispTerm's
agent_detector.zig (claude_code + codex subset). Pure functions, no IO.

Three confidence tiers: OSC 7748 marker = 100 (authoritative, self-reported);
screen heuristic = 70..92 (observed). See the Multi-Agent Term design spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentState(str, Enum):
    none = "none"
    running = "running"
    waiting_approval = "waiting_approval"
    needs_input = "needs_input"
    halted = "halted"
    failed = "failed"
    done = "done"


class AgentApp(str, Enum):
    none = "none"
    codex = "codex"
    claude_code = "claude_code"


OSC_NUM = 7748
TAG = "wispterm-agent"

_STATE_BY_LABEL = {s.value: s for s in AgentState}
_APP_BY_LABEL = {a.value: a for a in AgentApp}


@dataclass
class Detection:
    app: AgentApp = AgentApp.none
    state: AgentState = AgentState.none
    confidence: int = 0  # 0..100

    def visible(self) -> bool:
        return (self.app is not AgentApp.none
                and self.state is not AgentState.none
                and self.confidence > 0)


def parse_marker(payload: str) -> Detection | None:
    """Parse an OSC 7748 payload `wispterm-agent;state=…;app=…` into an
    authoritative Detection (confidence 100). Requires a recognized state;
    app optional (defaults none). Returns None on wrong tag / missing /
    unknown state. Mirrors agent_detector.parseMarker.
    """
    parts = [p.strip() for p in payload.split(";")]
    if not parts or parts[0] != TAG:
        return None
    state: AgentState | None = None
    app = AgentApp.none
    for f in parts[1:]:
        if f.startswith("state="):
            state = _STATE_BY_LABEL.get(f[len("state="):])
        elif f.startswith("app="):
            app = _APP_BY_LABEL.get(f[len("app="):], AgentApp.none)
    if state is None:
        return None
    return Detection(app=app, state=state, confidence=100)


# Heuristic keyword groups (lowercased match). Faithful subset of
# agent_detector.zig's detectClaudeCode/detect: pick the state whose marker
# appears LATEST in recent output (newer wins).
_RUNNING = ["esc to interrupt", "working", "thinking", "running"]
_WAITING = ["do you want to proceed", "press enter to confirm",
            "would you like to make the following", "[y/n]", "approve"]
_HALTED = ["execution halted", "interrupted"]
_FAILED = ["command failed", "permission denied", "error:"]
_DONE = ["done", "completed"]


def _last_index(haystack: str, needles: list[str]) -> int:
    low = haystack.lower()
    best = -1
    for n in needles:
        i = low.rfind(n)
        if i > best:
            best = i
    return best


def _app_of(title: str, output: str) -> AgentApp:
    blob = (title + " " + output).lower()
    if "codex" in blob:
        return AgentApp.codex
    if "claude" in blob:
        return AgentApp.claude_code
    return AgentApp.none


def detect(title: str, recent_output: str) -> Detection:
    """Heuristic detection from screen text. Returns invisible Detection when
    no known agent app is seen. Confidence 70..92 (always < 100 marker)."""
    app = _app_of(title, recent_output)
    if app is AgentApp.none:
        return Detection()
    groups = [
        (AgentState.waiting_approval, _WAITING, 90),
        (AgentState.halted, _HALTED, 92),
        (AgentState.failed, _FAILED, 76),
        (AgentState.done, _DONE, 76),
        (AgentState.running, _RUNNING, 82),
    ]
    best_state, best_idx, best_conf = AgentState.none, -1, 0
    for state, needles, conf in groups:
        idx = _last_index(recent_output, needles)
        if idx > best_idx:
            best_state, best_idx, best_conf = state, idx, conf
    if best_idx < 0:
        return Detection(app=app, state=AgentState.running, confidence=70)  # seen but unsure
    return Detection(app=app, state=best_state, confidence=best_conf)


_RANK = {
    AgentState.none: 0, AgentState.done: 1, AgentState.running: 2,
    AgentState.halted: 3, AgentState.failed: 3,
    AgentState.needs_input: 4, AgentState.waiting_approval: 5,
}


def aggregate(states: list[AgentState]) -> AgentState:
    """Collapse pane states into one indicator by attention priority
    (waiting_approval > needs_input > halted/failed > running > done)."""
    best = AgentState.none
    for s in states:
        if _RANK[s] > _RANK[best]:
            best = s
    return best
