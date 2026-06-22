# Multi-Agent Term — Phase 0: tmux runtime + OSC 7748 observation (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runtime + observation layer between MACR's control plane and tmux: open a tmux session in control mode, spawn N agent panes, send input, snapshot output, list pane facts, and fuse three signals (OSC 7748 authoritative marker / tmux process facts / screen heuristic) into a unified `Detection`. The tmux transport is injectable, so the whole layer is unit-tested with a fake tmux — no real `tmux`/`claude`/`codex` needed. Demonstrates "one terminal, multiple observable agents" at the logic layer.

**Architecture:** `TmuxTransport` (Protocol; `SubprocessTmuxTransport` real + `FakeTmuxTransport` test) carries control-mode lines. `TmuxControl` parses `%begin/%end/%error` guard frames (command responses) and `%`-notifications (async events). `TmuxRuntime` issues high-level ops (open/spawn/send/snapshot/list/kill) over `TmuxControl` and maps `agent_id ↔ %pane`. `agent_state` provides the `AgentState` vocabulary + `parse_marker`/`detect`/`aggregate` (ported from WispTerm `agent_detector.zig`). `AgentObserver` fuses signals into a per-agent `Detection`. Control plane (discuss roles / Stage D gate / worktree / `.macr/runs/`) is unchanged — wiring is Phase 1.

**Tech Stack:** Python stdlib (`dataclasses`, `enum`, `re`, `shlex`, `subprocess`, `select`) + pydantic-free pure modules; pytest. Spec: `docs/superpowers/specs/2026-06-22-multi-agent-term-design.md`. Mirrors MACR's injectable-runner convention (`ProcessRunner`/`FakeProcessRunner` in `macr/agents/base.py`).

---

## File Structure

**New package `macr/runtime/`:**
- `__init__.py` (new) — empty package marker.
- `agent_state.py` (new) — `AgentState`/`AgentApp` enums, `Detection`, `parse_marker`, `detect`, `aggregate`. Pure functions; ported from `agent_detector.zig`.
- `tmux_control.py` (new) — `TmuxTransport` Protocol, `SubprocessTmuxTransport`, `FakeTmuxTransport`, `CommandResult`, `Notification`, `TmuxControl`, `TmuxError`, `TmuxClosed`.
- `tmux_runtime.py` (new) — `AgentInfo`, `TmuxRuntime`.
- `observer.py` (new) — `AgentObserver`.

**Tests:** `tests/test_runtime_agent_state.py`, `tests/test_runtime_tmux_control.py`, `tests/test_runtime_tmux_runtime.py`, `tests/test_runtime_observer.py`, `tests/test_runtime_e2e.py`.

**Smoke (manual, not in CI):** `scripts/mat_tmux_smoke.py`.

---

## Phase A — Observation primitives (pure functions)

### Task 1: AgentState vocabulary + OSC 7748 marker parsing

**Files:**
- Create: `macr/runtime/__init__.py`, `macr/runtime/agent_state.py`
- Test: `tests/test_runtime_agent_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_agent_state.py`:

```python
from macr.runtime.agent_state import (
    AgentApp, AgentState, Detection, parse_marker,
)


def test_parse_marker_authoritative_detection():
    d = parse_marker("wispterm-agent;state=running;app=claude_code")
    assert d == Detection(app=AgentApp.claude_code, state=AgentState.running, confidence=100)
    assert d.visible()


def test_parse_marker_state_only_defaults_app_none():
    d = parse_marker("wispterm-agent;state=waiting_approval")
    assert d.app is AgentApp.none and d.state is AgentState.waiting_approval and d.confidence == 100


def test_parse_marker_rejects_wrong_tag_or_missing_or_unknown_state():
    assert parse_marker("other;state=running") is None
    assert parse_marker("wispterm-agent;app=claude_code") is None
    assert parse_marker("wispterm-agent;state=bogus") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent_state.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.runtime'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/runtime/__init__.py` (empty).

Create `macr/runtime/agent_state.py`:

```python
"""Agent run-state vocabulary + detection. Ported from WispTerm's
agent_detector.zig (claude_code + codex subset). Pure functions, no IO.

Three confidence tiers: OSC 7748 marker = 100 (authoritative, self-reported);
screen heuristic = 70..96 (observed). See the Multi-Agent Term design spec.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent_state.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/__init__.py macr/runtime/agent_state.py tests/test_runtime_agent_state.py
git commit -m "feat(runtime): AgentState vocabulary + OSC 7748 parse_marker (ported from agent_detector.zig)"
```

---

### Task 2: Screen heuristic `detect` + `aggregate`

**Files:**
- Modify: `macr/runtime/agent_state.py`
- Test: `tests/test_runtime_agent_state.py` (add tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runtime_agent_state.py`:

```python
from macr.runtime.agent_state import detect, aggregate


def test_detect_picks_latest_state_marker_for_known_app():
    out = "claude working...\nesc to interrupt\nDo you want to proceed?"
    d = detect("claude", out)
    assert d.app is AgentApp.claude_code and d.state is AgentState.waiting_approval
    assert 0 < d.confidence < 100


def test_detect_running_then_done_order_matters():
    assert detect("codex", "esc to interrupt\n...\nDone").state is AgentState.done
    assert detect("codex", "Done\n...\nesc to interrupt").state is AgentState.running


def test_detect_unknown_app_is_invisible():
    assert detect("vim", "just editing").visible() is False


def test_aggregate_attention_priority():
    assert aggregate([AgentState.running, AgentState.waiting_approval, AgentState.done]) is AgentState.waiting_approval
    assert aggregate([AgentState.done, AgentState.running]) is AgentState.running
    assert aggregate([]) is AgentState.none
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent_state.py -q`
Expected: FAIL with `ImportError: cannot import name 'detect'`.

- [ ] **Step 3: Add implementation**

Append to `macr/runtime/agent_state.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent_state.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/agent_state.py tests/test_runtime_agent_state.py
git commit -m "feat(runtime): screen-heuristic detect() + aggregate() (latest-marker-wins, attention rank)"
```

---

## Phase B — Control-mode transport

### Task 3: TmuxControl — guard frames, notifications, injectable transport

**Files:**
- Create: `macr/runtime/tmux_control.py`
- Test: `tests/test_runtime_tmux_control.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_tmux_control.py`:

```python
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
    # an async %output arrives before the command block, plus events after
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
    # the %output payload is preserved
    out = next(n for n in notes if n.kind == "output")
    assert out.data == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_tmux_control.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.runtime.tmux_control'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/runtime/tmux_control.py`:

```python
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
import shlex  # noqa: F401  (used by tmux_runtime; re-exported convenience)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime_tmux_control.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/tmux_control.py tests/test_runtime_tmux_control.py
git commit -m "feat(runtime): TmuxControl — control-mode guard frames + %-notifications, injectable transport"
```

---

## Phase C — Runtime, observer, end-to-end

### Task 4: TmuxRuntime — spawn / send / snapshot / list / kill

**Files:**
- Create: `macr/runtime/tmux_runtime.py`
- Test: `tests/test_runtime_tmux_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_tmux_runtime.py`:

```python
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
    # commands emitted look right
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
        "%12\t4242\tclaude\t0\t",        # alive
        "%99\t5\tbash\t0\t",             # unknown pane → skipped
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_tmux_runtime.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.runtime.tmux_runtime'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/runtime/tmux_runtime.py`:

```python
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
        res = self._c.send_command(f"capture-pane -p -t {pane} -S -{recent} -e")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime_tmux_runtime.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/tmux_runtime.py tests/test_runtime_tmux_runtime.py
git commit -m "feat(runtime): TmuxRuntime — spawn/send/snapshot/list/kill over control mode, agent_id↔pane map"
```

---

### Task 5: AgentObserver — fuse OSC 7748 + tmux facts + heuristic

**Files:**
- Create: `macr/runtime/observer.py`
- Test: `tests/test_runtime_observer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_observer.py`:

```python
from macr.runtime.agent_state import AgentApp, AgentState
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


def test_refresh_from_panes_dead_status_maps_failed_or_done():
    rt = _runtime_with_agent(extra_feeds=[_begin_end("%12\t9\tclaude\t1\t2")])
    obs = AgentObserver(rt)
    obs.refresh_from_panes()
    assert obs.state_of("w").state is AgentState.failed  # nonzero exit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_observer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.runtime.observer'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/runtime/observer.py`:

```python
"""Fuse three observation signals into a per-agent Detection:
  on_output         — OSC 7748 markers in %output (confidence 100, reported)
  refresh_from_panes— tmux pane_dead/current_command (process facts, observed)
  detect_from_snapshot — capture-pane screen heuristic (observed, 70..96)
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

    def refresh_from_panes(self) -> None:
        for info in self._rt.list_agents():
            if info.dead:
                state = AgentState.done if info.dead_status == 0 else AgentState.failed
                self._apply(info.agent_id,
                            Detection(app=_app_of(info), state=state, confidence=95))

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runtime_observer.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/observer.py tests/test_runtime_observer.py
git commit -m "feat(runtime): AgentObserver — fuse OSC 7748 + pane facts + heuristic into Detection"
```

---

### Task 6: End-to-end — one session, two observable agents (fake tmux)

**Files:**
- Test: `tests/test_runtime_e2e.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_e2e.py`:

```python
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

    # worker-1's process then exits cleanly → done
    t.feed(*_be("%12\t9\tclaude\t1\t0", "%13\t10\tcodex\t0\t"))
    obs.refresh_from_panes()
    assert obs.state_of("worker-1").state is AgentState.done
    # worker-2 still waiting_approval (conf 100 not overwritten by alive refresh)
    assert obs.state_of("worker-2").state is AgentState.waiting_approval
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runtime_e2e.py -q`
Expected: FAIL — initially because (a) the module wiring may differ, or it passes only once all prior tasks are in. If a prior task is incomplete it fails on import; otherwise this is the integration assertion.

NOTE: `refresh_from_panes` only overrides when `dead` (conf 95) — worker-2 is alive so it isn't touched; worker-1 dead status 0 → done (95 ≥ 100? no). The marker for worker-1 was `running` at conf 100; dead-done is conf 95 which is **lower**, so it would NOT override. Fix in Step 3.

- [ ] **Step 3: Make process-exit authoritative**

A clean/failed process exit is a hard fact and must beat a stale `running` marker. In `macr/runtime/observer.py`, bump dead detections to confidence 100 (process death is authoritative):

```python
    def refresh_from_panes(self) -> None:
        for info in self._rt.list_agents():
            if info.dead:
                state = AgentState.done if info.dead_status == 0 else AgentState.failed
                self._apply(info.agent_id,
                            Detection(app=_app_of(info), state=state, confidence=100))
```

(Only the `confidence=95 → 100` change.) Re-run the observer test from Task 5 too — `test_refresh_from_panes_dead_status_maps_failed_or_done` still passes (no marker set there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_runtime_e2e.py tests/test_runtime_observer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/runtime/observer.py tests/test_runtime_e2e.py
git commit -m "feat(runtime): e2e — one tmux session, two OSC-observed agents; process-exit is authoritative"
```

---

### Task 7: Real-tmux smoke script + README + full suite

**Files:**
- Create: `scripts/mat_tmux_smoke.py`
- Create: `macr/runtime/README.md`

- [ ] **Step 1: Create the manual smoke script**

Create `scripts/mat_tmux_smoke.py`:

```python
"""Manual smoke: drive a REAL tmux via control mode. Requires `tmux` on PATH.
NOT run in CI. Usage: .venv/bin/python scripts/mat_tmux_smoke.py

Caveat: on attach, tmux emits an initial guard block + notifications before our
first command. We consume that banner with one poll() before issuing commands.
"""
import time

from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_control import SubprocessTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime


def main() -> None:
    transport = SubprocessTmuxTransport(session="macr-mat-smoke")
    control = TmuxControl(transport)
    control.poll(timeout=0.5)  # drain attach banner
    rt = TmuxRuntime(control)
    obs = AgentObserver(rt)

    # The attach already created the session; spawn a plain shell as a fake "agent".
    rt._session = "macr-mat-smoke"  # use the attached session
    pane = rt.spawn_agent("smoke-1", ["bash", "--norc"], cwd=".")
    print("spawned agent smoke-1 on pane", pane)

    rt.send_input("smoke-1", "echo MAT_SMOKE_OK")
    time.sleep(0.5)
    snap = rt.snapshot("smoke-1", recent=50)
    print("snapshot:\n", snap)
    assert "MAT_SMOKE_OK" in snap, "did not observe echoed output"

    for info in rt.list_agents():
        print("agent:", info)

    transport.close()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the smoke (only if tmux is installed)**

Run: `.venv/bin/python scripts/mat_tmux_smoke.py`
Expected (on a machine with tmux): prints the spawned pane id, a snapshot containing `MAT_SMOKE_OK`, the agent list, and `SMOKE OK`.
If tmux is absent or the version differs, note it — CI does not depend on this; the fake-transport e2e (Task 6) is the gating test. Adjust the attach-banner drain / session handling per local tmux if needed.

- [ ] **Step 3: Write the package README**

Create `macr/runtime/README.md`:

```markdown
# macr/runtime — Multi-Agent Term runtime (Phase 0)

The runtime + observation layer between MACR's control plane and tmux. One
tmux pane = one agent; MACR drives them via control mode and observes state.

- `agent_state.py` — `AgentState`/`AgentApp`, `Detection`, `parse_marker` (OSC
  7748, conf 100), `detect` (screen heuristic, 70..92), `aggregate`.
- `tmux_control.py` — `TmuxTransport` (Protocol; `Subprocess`/`Fake`), `TmuxControl`
  (parses `%begin/%end/%error` guard frames + `%`-notifications).
- `tmux_runtime.py` — `TmuxRuntime`: open_session / spawn_agent / send_input /
  snapshot / list_agents / kill; maps `agent_id ↔ %pane`.
- `observer.py` — `AgentObserver`: fuses OSC markers + pane facts + heuristic.

Tested entirely with `FakeTmuxTransport` (no real tmux/CLI). Real-tmux smoke:
`scripts/mat_tmux_smoke.py` (manual). Design: `docs/superpowers/specs/2026-06-22-multi-agent-term-design.md`.

Phase 0 emits only `observed`/`reported` states — `verified` remains the
control plane's Stage D gate + tests; `approved` the human gate.
```

- [ ] **Step 4: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (existing 245 + new runtime tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/mat_tmux_smoke.py macr/runtime/README.md
git commit -m "docs(runtime): real-tmux smoke script + package README; full suite green"
```

---

## Self-Review

**Spec coverage:**
- `agent_state` vocabulary + `parse_marker` (conf 100) + `detect` (70..92) + `aggregate`: Tasks 1, 2 ✓
- `TmuxTransport` Protocol + Subprocess/Fake; `TmuxControl` guard frames + `%`-events: Task 3 ✓
- `TmuxRuntime` open/spawn/send/snapshot/list/kill + `agent_id↔%pane`, injection-safe argv, `send-keys -l`: Task 4 ✓
- `AgentObserver` three-signal fusion + confidence-override rule: Task 5 ✓
- End-to-end "one terminal, multiple observable agents" on fake transport: Task 6 ✓
- Real-tmux smoke documented + not CI-gating: Task 7 ✓
- Observed/reported only, never verified/approved: enforced by design (Task 5 docstring, README) ✓
- YAGNI (no orchestrator wiring / DAG / SQLite / hook install / native UI / remote): no such tasks ✓

**Type/interface consistency:**
- `Detection(app, state, confidence)` identical across `agent_state` (Tasks 1–2), `observer` (Task 5), all tests.
- `TmuxTransport` (`send_line`/`read_line(timeout)`/`close`) consistent: `FakeTmuxTransport` + `SubprocessTmuxTransport` (Task 3), consumed by `TmuxControl` (Task 3).
- `CommandResult(number, ok, lines)` / `Notification(kind, pane, window, data)` produced by `TmuxControl` (Task 3), consumed by `TmuxRuntime` (Task 4).
- `TmuxRuntime` public API (`open_session`/`spawn_agent`/`send_input`/`snapshot`/`list_agents`/`kill`/`agent_for_pane`) identical in Tasks 4, 5 (observer uses `agent_for_pane`/`list_agents`/`snapshot`), 6.
- `AgentInfo(agent_id, pane, pid, current_command, dead, dead_status)` identical Tasks 4, 5.
- Confidence ladder consistent: marker 100, process-exit 100 (Task 6 fix), pane alive n/a, heuristic ≤92 — override rule `>=` in `_apply` (Task 5).

**Ordering caveats (intentional):** Task 6 Step 2 documents that the e2e initially mis-orders confidence (running@100 vs dead-done@95); Step 3 fixes it to dead@100. This is deliberate red→green within the task. Task 7's smoke is non-gating (no tmux in CI).

**Placeholder scan:** No TBD/TODO; every code step is complete and runnable. `shlex` import in `tmux_control.py` is marked `# noqa: F401` (convenience re-export) — or drop it if the linter is strict, since `tmux_runtime.py` imports shlex directly.
