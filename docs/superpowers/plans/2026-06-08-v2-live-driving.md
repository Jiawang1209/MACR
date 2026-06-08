# V2 Live Driving (sub-project ②) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Launch and drive a single collab/discuss run from the web — stream agent output live and approve/reject/annotate the human gates in the browser.

**Architecture:** A background `threading.Thread` runs the existing `run_collab`/`run_discuss` orchestrators with an injected `WebView` (emits structured events) and web gate callbacks (block on a `threading.Event` until the browser responds). A `RunSession` buffers events + bridges gates; a `RunManager` holds the single active session. FastAPI exposes `POST /launch`, `GET /active`, and a `WebSocket` that replays the buffer then streams live + receives gate responses. The React SPA adds a launch form and a live-run view (reusing sub-project ①'s `StageCard`).

**Tech Stack:** Python stdlib `threading`/`queue` + FastAPI WebSocket (backend); React + TS + Vitest (frontend). Spec: `docs/superpowers/specs/2026-06-08-v2-live-driving-design.md`. Builds on sub-project ① (`macr/web/`, `frontend/`).

---

## File Structure

**Backend (`macr/web/`):**
- `session.py` (new) — `RunSession` (event buffer + subscriber + gate bridge), `RunManager` (single active session), `RunActive` exception. Pure state/bridge; knows nothing about orchestrators.
- `live.py` (new) — `WebView` (implements `DiscussionView` + a `printer` method, emits events), web gate callbacks + gate-data helpers, `start_run` (spawns the orchestrator thread). Imports session + orchestrators.
- `app.py` (modify) — add `POST /api/runs/launch`, `GET /api/runs/active`, `WebSocket /api/runs/active/ws`; module-level `RunManager` singleton.
- `macr/collab_orchestrator.py` + `macr/discussion.py` (modify) — accept an optional `run_id` so the session controls it.

**Backend tests:** `tests/test_web_session.py`, `tests/test_web_live.py`, extend `tests/test_web_app.py`.

**Frontend (`frontend/src/`):**
- `api.ts` (modify) — `launchRun`, `fetchActive`, WS event types.
- `App.tsx` (modify) — add `/launch` + `/live` routes + nav link.
- `LaunchForm.tsx` + `LaunchForm.test.tsx` (new).
- `LiveRun.tsx` + `GatePanel.tsx` + `LiveRun.test.tsx` (new).

---

## Phase A — Backend core (session + bridge)

### Task 1: RunSession — event buffer, subscriber, gate bridge

**Files:**
- Create: `macr/web/session.py`
- Test: `tests/test_web_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_session.py`:

```python
import threading

from macr.web.session import RunSession


def test_emit_buffers_events_and_tracks_status():
    s = RunSession(run_id="R1", command="collab")
    assert s.status == "running"
    s.emit({"type": "note", "text": "hi"})
    s.emit({"type": "status", "status": "awaiting_gate"})
    assert [e["type"] for e in s.events] == ["note", "status"]
    assert s.status == "awaiting_gate"


def test_subscribe_returns_snapshot_and_streams_new_events():
    s = RunSession(run_id="R1", command="collab")
    s.emit({"type": "note", "text": "before"})
    received = []
    snapshot = s.subscribe(received.append)
    assert [e["text"] for e in snapshot] == ["before"]
    s.emit({"type": "note", "text": "after"})
    assert received == [{"type": "note", "text": "after"}]
    s.unsubscribe(received.append)  # no-op for a different ref; see next test


def test_unsubscribe_stops_streaming():
    s = RunSession(run_id="R1", command="collab")
    received = []
    push = received.append
    s.subscribe(push)
    s.emit({"type": "note", "text": "a"})
    s.unsubscribe(push)
    s.emit({"type": "note", "text": "b"})
    assert [e["text"] for e in received] == ["a"]


def test_gate_bridge_blocks_until_response():
    s = RunSession(run_id="R1", command="discuss")
    result = {}

    def run_thread():
        fb = s.request_gate("consensus", {"summary": "plan"})
        result["decision"] = fb.decision
        result["feedback"] = fb.feedback

    t = threading.Thread(target=run_thread)
    t.start()
    # wait until the run thread is awaiting the gate
    assert s.wait_for_gate(timeout=2.0)
    assert s.status == "awaiting_gate"
    assert any(e["type"] == "gate_request" and e["gate"] == "consensus" for e in s.events)
    s.respond_gate("approve", "looks good")
    t.join(timeout=2.0)
    assert result == {"decision": "approve", "feedback": "looks good"}
    assert s.status == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_session.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.web.session'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/web/session.py`:

```python
from __future__ import annotations

import threading
from typing import Callable

from macr.schemas import HumanFeedback
from macr.utils import now_iso


class RunActive(Exception):
    """A live run is already active; only one is allowed at a time."""


class RunSession:
    """One live run: an append-only event buffer, a single live subscriber, and a
    synchronous human-gate bridge between the run thread and the WebSocket handler.
    """

    def __init__(self, run_id: str, command: str):
        self.run_id = run_id
        self.command = command
        self.status = "running"  # running | awaiting_gate | done | error
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._subscriber: Callable[[dict], None] | None = None
        self._gate_event = threading.Event()
        self._gate_pending = threading.Event()
        self._gate_response: HumanFeedback | None = None

    def emit(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)
            if event.get("type") == "status":
                self.status = event["status"]
            sub = self._subscriber
        if sub is not None:
            sub(event)

    def subscribe(self, push: Callable[[dict], None]) -> list[dict]:
        """Attach the live subscriber and atomically return the buffer snapshot."""
        with self._lock:
            self._subscriber = push
            return list(self.events)

    def unsubscribe(self, push: Callable[[dict], None]) -> None:
        with self._lock:
            if self._subscriber is push:
                self._subscriber = None

    # --- human-gate bridge (run thread side) ---
    def request_gate(self, gate: str, data: dict) -> HumanFeedback:
        """Called from the run thread. Emit a gate request, block until responded."""
        self._gate_event.clear()
        self._gate_response = None
        self.emit({"type": "status", "status": "awaiting_gate"})
        self.emit({"type": "gate_request", "gate": gate, "data": data})
        self._gate_pending.set()
        self._gate_event.wait()
        self._gate_pending.clear()
        self.emit({"type": "status", "status": "running"})
        return self._gate_response  # set by respond_gate before _gate_event.set()

    def wait_for_gate(self, timeout: float | None = None) -> bool:
        """Test/helper: block until the run thread is awaiting a gate."""
        return self._gate_pending.wait(timeout)

    # --- human-gate bridge (WebSocket handler side) ---
    def respond_gate(self, decision: str, feedback: str = "") -> None:
        self._gate_response = HumanFeedback(decision=decision, feedback=feedback, timestamp=now_iso())
        self._gate_event.set()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_session.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/session.py tests/test_web_session.py
git commit -m "feat(web): RunSession — event buffer, live subscriber, human-gate bridge"
```

---

### Task 2: RunManager — single active session

**Files:**
- Modify: `macr/web/session.py` (add `RunManager`)
- Test: `tests/test_web_session.py` (add tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_session.py`:

```python
from macr.web.session import RunActive, RunManager
import pytest


def test_manager_launch_starts_session_via_injected_runner():
    started = {}

    def fake_runner(session, **kwargs):
        started["run_id"] = session.run_id
        started["kwargs"] = kwargs

    mgr = RunManager(runner=fake_runner)
    sess = mgr.launch(command="collab", task="do it", repo="/r", test_cmd=["true"], options={})
    assert mgr.active is sess
    assert started["run_id"] == sess.run_id
    assert started["kwargs"]["command"] == "collab"
    assert started["kwargs"]["task"] == "do it"


def test_manager_rejects_second_launch_while_active():
    mgr = RunManager(runner=lambda session, **kw: None)
    mgr.launch(command="collab", task="t", repo="/r", test_cmd=["true"], options={})
    with pytest.raises(RunActive):
        mgr.launch(command="discuss", task="t2", repo="/r", test_cmd=["true"], options={})


def test_manager_allows_new_launch_after_active_finishes():
    mgr = RunManager(runner=lambda session, **kw: None)
    s1 = mgr.launch(command="collab", task="t", repo="/r", test_cmd=["true"], options={})
    s1.emit({"type": "status", "status": "done"})
    s2 = mgr.launch(command="collab", task="t2", repo="/r", test_cmd=["true"], options={})
    assert mgr.active is s2 and s2 is not s1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_session.py -q`
Expected: FAIL with `ImportError: cannot import name 'RunManager'`.

- [ ] **Step 3: Add the implementation**

Append to `macr/web/session.py`:

```python
class RunManager:
    """Holds the single active RunSession. `runner(session, **kwargs)` starts the
    background run (injected for tests; defaults to the real thread runner).
    """

    def __init__(self, runner: Callable[..., None] | None = None):
        self._runner = runner
        self._active: RunSession | None = None
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def active(self) -> RunSession | None:
        return self._active

    def launch(self, *, command: str, task: str, repo: str, test_cmd, options: dict) -> RunSession:
        with self._lock:
            if self._active is not None and self._active.status in ("running", "awaiting_gate"):
                raise RunActive("a live run is already active")
            self._counter += 1
            run_id = f"live-{self._counter}"  # replaced by the real runner with a real run_id
            session = RunSession(run_id=run_id, command=command)
            self._active = session
        runner = self._runner
        if runner is None:
            from macr.web.live import start_run as runner  # default real runner
        runner(session, command=command, task=task, repo=repo, test_cmd=test_cmd, options=options)
        return session

    def respond_gate(self, decision: str, feedback: str = "") -> None:
        if self._active is not None:
            self._active.respond_gate(decision, feedback)
```

NOTE: the placeholder `run_id = f"live-{counter}"` is overwritten by the real runner (Task 5), which generates a real `next_run_id` and sets `session.run_id` before starting the orchestrator. The injected test runners here don't care about run_id.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_session.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/session.py tests/test_web_session.py
git commit -m "feat(web): RunManager — single active session with injectable runner"
```

---

### Task 3: Optional run_id on the orchestrators

**Files:**
- Modify: `macr/collab_orchestrator.py` (the `run_collab` signature + run_id line)
- Modify: `macr/discussion.py` (the `run_discuss` signature + run_id line)
- Test: `tests/test_collab_orchestrator.py` (add one), `tests/test_discussion.py` (add one)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collab_orchestrator.py`:

```python
def test_run_collab_accepts_injected_run_id(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    from macr.collab_orchestrator import run_collab
    state = run_collab(
        "do the task", repo=repo, test_cmd=["true"],
        claude_backend=FakeAgentBackend({"planner": [_plan()], "reviewer": [_review("approve")]}),
        codex_backend=FakeAgentBackend({"executor": [_exec(1)]}, on_run=_editor),
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        human_gate=_approve, printer=lambda *_: None, run_id="CUSTOM_ID",
    )
    assert state.run_id == "CUSTOM_ID"
    assert (tmp_path / "runs" / "CUSTOM_ID" / "state.json").exists()
```

Append to `tests/test_discussion.py`:

```python
def test_run_discuss_accepts_injected_run_id(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    from macr.discussion import run_discuss
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")], "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()], "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")],
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    state = run_discuss(
        "topic", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=SilentView(), run_id="CUSTOM_ID2",
    )
    assert state.run_id == "CUSTOM_ID2"
    assert (tmp_path / "runs" / "CUSTOM_ID2" / "state.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_collab_orchestrator.py::test_run_collab_accepts_injected_run_id tests/test_discussion.py::test_run_discuss_accepts_injected_run_id -q`
Expected: FAIL with `TypeError: run_collab() got an unexpected keyword argument 'run_id'` (and same for run_discuss).

- [ ] **Step 3: Add the optional parameter to both orchestrators**

In `macr/collab_orchestrator.py`, find the `run_collab` signature. It currently ends with:
```python
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
```
Add a `run_id` parameter:
```python
    today: str | None = None,
    timeout: int = 1800,
    run_id: str | None = None,
) -> SharedState:
```
Then find the line `run_id = next_run_id(runs_dir, today=today)` and change it to:
```python
    run_id = run_id or next_run_id(runs_dir, today=today)
```

In `macr/discussion.py`, find the `run_discuss` signature ending:
```python
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
```
Add the parameter:
```python
    today: str | None = None,
    timeout: int = 1800,
    run_id: str | None = None,
) -> SharedState:
```
Then change `run_id = next_run_id(runs_dir, today=today)` to:
```python
    run_id = run_id or next_run_id(runs_dir, today=today)
```

- [ ] **Step 4: Run the tests + the full orchestrator suites**

Run: `.venv/bin/python -m pytest tests/test_collab_orchestrator.py tests/test_discussion.py -q`
Expected: PASS (all, including the 2 new).

- [ ] **Step 5: Commit**

```bash
git add macr/collab_orchestrator.py macr/discussion.py tests/test_collab_orchestrator.py tests/test_discussion.py
git commit -m "feat: accept optional run_id in run_collab/run_discuss (web session controls the id)"
```

---

### Task 4: WebView — DiscussionView + printer that emit events

**Files:**
- Create: `macr/web/live.py` (the `WebView` class only; gates + start_run added in Task 5)
- Test: `tests/test_web_live.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_live.py`:

```python
from macr.web.live import WebView
from macr.web.session import RunSession


def _events_of_type(session, t):
    return [e for e in session.events if e["type"] == t]


def test_webview_plan_emits_stage_event():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.plan("claude", {"summary": "the plan", "steps": ["a", "b"]})
    stages = _events_of_type(s, "stage")
    assert len(stages) == 1
    st = stages[0]["stage"]
    assert st["kind"] == "plan" and st["agent"] == "claude"
    assert st["body"]["summary"] == "the plan" and st["body"]["steps"] == ["a", "b"]


def test_webview_consensus_and_evaluation_and_note():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.consensus({"summary": "agreed", "steps": ["x"], "rationale": "r"})
    v.evaluation(0, "PASS")
    v.note("hello")
    kinds = [e["stage"]["kind"] for e in _events_of_type(s, "stage")]
    assert "consensus" in kinds and "evaluator" in kinds
    assert _events_of_type(s, "note")[0]["text"] == "hello"


def test_webview_printer_emits_note():
    s = RunSession(run_id="R1", command="collab")
    v = WebView(s)
    v.printer("[tests #1] passed=True")
    assert _events_of_type(s, "note")[0]["text"] == "[tests #1] passed=True"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_live.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.web.live'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/web/live.py`:

```python
from __future__ import annotations

from macr.web.session import RunSession


class WebView:
    """Implements the DiscussionView protocol (used by run_discuss) and provides a
    `printer(text)` method (used by run_collab). Every callback emits a structured
    event onto the session's bus: rich `stage` events for discuss, `note` lines for
    collab's printer.
    """

    def __init__(self, session: RunSession):
        self._s = session

    # DiscussionView context-manager protocol (run_discuss does `with view:`)
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _stage(self, kind: str, label: str, *, agent: str | None = None,
               status: str | None = None, body: dict | None = None) -> None:
        self._s.emit({"type": "stage", "stage": {
            "kind": kind, "label": label, "agent": agent, "status": status, "body": body or {}}})

    def plan(self, agent: str, content: dict) -> None:
        self._stage("plan", f"Plan ({agent})", agent=agent,
                    body={"summary": content.get("summary", ""), "steps": content.get("steps", [])})

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self._stage("turn", f"Turn r{round_no} ({agent})", agent=agent,
                    body={"response": content.get("response", ""), "concerns": content.get("concerns", []),
                          "revised_steps": content.get("revised_steps", [])})

    def interjection(self, round_no: int, text: str) -> None:
        self._stage("turn", f"Human interjection r{round_no}", agent="human", body={"text": text})

    def consensus(self, content: dict) -> None:
        self._stage("consensus", "Consensus",
                    body={"summary": content.get("summary", ""), "steps": content.get("steps", []),
                          "rationale": content.get("rationale", "")})

    def review(self, attempt: int, content: dict) -> None:
        self._stage("plan_review", f"Plan Review #{attempt}", agent="codex",
                    status=content.get("decision"),
                    body={"summary": content.get("summary", ""), "findings": content.get("findings", [])})

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self._stage("evaluator", f"Evaluator #{attempt}", status=val)

    def status(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})

    def note(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})

    def printer(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_live.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/live.py tests/test_web_live.py
git commit -m "feat(web): WebView — DiscussionView + printer emitting stage/note events"
```

---

### Task 5: Web gates + start_run (end-to-end with FakeAgentBackend)

**Files:**
- Modify: `macr/web/live.py` (add gate helpers + `start_run`)
- Test: `tests/test_web_live.py` (add an end-to-end test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_live.py`:

```python
import subprocess
import threading
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.web.live import start_run


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def test_start_run_collab_end_to_end_with_fakes(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    def _editor(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")

    claude = FakeAgentBackend({"planner": [{"summary": "p", "steps": ["s"]}],
                               "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]})
    codex = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)

    s = RunSession(run_id="LIVE1", command="collab")
    thread = start_run(
        s, command="collab", task="do it", repo=str(repo), test_cmd=["true"],
        options={"runs_dir": tmp_path / "runs", "worktrees_dir": tmp_path / "wts",
                 "claude_backend": claude, "codex_backend": codex},
    )
    # collab has one final gate — wait for it, then approve
    assert s.wait_for_gate(timeout=5.0)
    assert any(e["type"] == "gate_request" and e["gate"] == "final" for e in s.events)
    s.respond_gate("approve", "")
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert s.status == "done"
    done = [e for e in s.events if e["type"] == "done"]
    assert done and done[0]["decision"] == "approve" and done[0]["run_id"] == "LIVE1"
    assert (tmp_path / "runs" / "LIVE1" / "state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_live.py::test_start_run_collab_end_to_end_with_fakes -q`
Expected: FAIL with `ImportError: cannot import name 'start_run'`.

- [ ] **Step 3: Add gates + start_run to `macr/web/live.py`**

Append to `macr/web/live.py`:

```python
import threading
from pathlib import Path

from macr.schemas import HumanFeedback


def _final_gate_data(state) -> dict:
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    return {"worktree": state.worktree_path, "diff": diff,
            "tests": {"passed": tr.get("passed"), "exit_code": tr.get("exit_code")}}


def _consensus_gate_data(state) -> dict:
    c = state.consensus or {}
    review = state.reviews[-1] if state.reviews else {}
    return {"summary": c.get("summary", ""), "steps": c.get("steps", []),
            "open_questions": c.get("open_questions", []),
            "plan_review_decision": review.get("decision")}


def _make_gate(session: RunSession, gate: str, data_fn):
    def gate_fn(state, *, printer=None) -> HumanFeedback:
        return session.request_gate(gate, data_fn(state))
    return gate_fn


def start_run(session: RunSession, *, command: str, task: str, repo: str, test_cmd,
              options: dict) -> threading.Thread:
    """Spawn the orchestrator in a background thread with a WebView + web gates.

    `options` carries runs_dir / worktrees_dir / backends / numeric limits. Tests pass
    FakeAgentBackend(s); production passes real CLI backends (built by the caller).
    """
    runs_dir = Path(options.get("runs_dir", ".macr/runs"))
    worktrees_dir = Path(options.get("worktrees_dir", ".macr/worktrees"))

    def target() -> None:
        view = WebView(session)
        try:
            if command == "collab":
                from macr.collab_orchestrator import run_collab
                state = run_collab(
                    task, repo=Path(repo), test_cmd=test_cmd,
                    claude_backend=options["claude_backend"], codex_backend=options["codex_backend"],
                    runs_dir=runs_dir, worktrees_dir=worktrees_dir,
                    max_revisions=options.get("max_revisions", 2),
                    human_gate=_make_gate(session, "final", _final_gate_data),
                    printer=view.printer, run_id=session.run_id,
                    timeout=options.get("timeout", 1800))
            else:
                from macr.discussion import run_discuss
                from macr.discussion_control import auto_discussion_control
                state = run_discuss(
                    task, repo=Path(repo), test_cmd=test_cmd,
                    claude_backend=options["claude_backend"], codex_backend=options["codex_backend"],
                    impl_codex_backend=options["impl_codex_backend"],
                    runs_dir=runs_dir, worktrees_dir=worktrees_dir,
                    max_rounds=options.get("max_rounds", 3),
                    max_revisions=options.get("max_revisions", 2),
                    max_plan_revisions=options.get("max_plan_revisions", 1),
                    consensus_gate=_make_gate(session, "consensus", _consensus_gate_data),
                    human_gate=_make_gate(session, "final", _final_gate_data),
                    discussion_control=auto_discussion_control, view=view,
                    run_id=session.run_id, timeout=options.get("timeout", 1800))
            decision = state.human_feedback.decision if state.human_feedback else None
            session.emit({"type": "status", "status": "done"})
            session.emit({"type": "done", "run_id": session.run_id, "decision": decision})
        except Exception as exc:  # noqa: BLE001 — surface any failure to the client
            session.emit({"type": "status", "status": "error"})
            session.emit({"type": "error", "message": str(exc)})

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_live.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire the real-backends default into RunManager**

The production `start_run` needs real backends. The default runner path in `RunManager.launch` (Task 2) calls `macr.web.live.start_run`, but real launches must build CLI backends + a real run_id. Add a production entry `start_live_run` to `macr/web/live.py` that the manager uses:

```python
def start_live_run(session: RunSession, *, command: str, task: str, repo: str, test_cmd,
                   options: dict) -> threading.Thread:
    """RunManager default runner: assigns a real run_id and builds real CLI backends."""
    from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
    from macr.utils import next_run_id

    runs_dir = Path(options.get("runs_dir", ".macr/runs")).resolve()
    session.run_id = next_run_id(runs_dir)
    enable = not options.get("no_subagents", False)
    timeout = options.get("timeout", 1800)
    opts = dict(options)
    opts["runs_dir"] = runs_dir
    opts["worktrees_dir"] = Path(options.get("worktrees_dir", ".macr/worktrees")).resolve()
    opts["claude_backend"] = ClaudeCliBackend(timeout=timeout, enable_subagents=enable)
    if command == "collab":
        opts["codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable)
    else:
        opts["codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable, sandbox="read-only")
        opts["impl_codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable,
                                                     sandbox="workspace-write")
    return start_run(session, command=command, task=task, repo=repo, test_cmd=test_cmd, options=opts)
```

Then update `macr/web/session.py` `RunManager.launch` default import from `start_run` to `start_live_run`:
Change the line `from macr.web.live import start_run as runner` to:
```python
            from macr.web.live import start_live_run as runner
```

- [ ] **Step 6: Run the web suite + commit**

Run: `.venv/bin/python -m pytest tests/test_web_live.py tests/test_web_session.py -q`
Expected: PASS.

```bash
git add macr/web/live.py macr/web/session.py tests/test_web_live.py
git commit -m "feat(web): web gates + start_run threading orchestrator (e2e verified with FakeAgentBackend)"
```

---

## Phase B — API (REST + WebSocket)

### Task 6: launch + active endpoints

**Files:**
- Modify: `macr/web/app.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_app.py`:

```python
from macr.web.session import RunManager


def test_launch_starts_run_and_active_reports_it(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: session.emit({"type": "note", "text": "started"}))
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    repo = tmp_path / "repo"; repo.mkdir()
    r = c.post("/api/runs/launch", json={"command": "collab", "task": "do it",
                                         "repo": str(repo), "test_cmd": "true"})
    assert r.status_code == 200 and r.json()["run_id"]
    active = c.get("/api/runs/active")
    assert active.status_code == 200 and active.json()["command"] == "collab"


def test_launch_rejects_concurrent_with_409(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: None)
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    repo = tmp_path / "repo"; repo.mkdir()
    body = {"command": "collab", "task": "t", "repo": str(repo), "test_cmd": "true"}
    assert c.post("/api/runs/launch", json=body).status_code == 200
    assert c.post("/api/runs/launch", json=body).status_code == 409


def test_launch_validates_inputs_with_400(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: None)
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    # missing repo dir
    r = c.post("/api/runs/launch", json={"command": "collab", "task": "t",
                                         "repo": str(tmp_path / "nope"), "test_cmd": "true"})
    assert r.status_code == 400
    # blank task
    repo = tmp_path / "repo"; repo.mkdir()
    r2 = c.post("/api/runs/launch", json={"command": "collab", "task": "  ",
                                          "repo": str(repo), "test_cmd": "true"})
    assert r2.status_code == 400


def test_active_returns_204_when_idle(tmp_path):
    app = create_app(runs_dir=tmp_path, manager=RunManager(runner=lambda s, **k: None))
    assert TestClient(app).get("/api/runs/active").status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: FAIL — `create_app()` has no `manager` kwarg / no `/api/runs/launch` route.

- [ ] **Step 3: Update `macr/web/app.py`**

Add imports near the top (with the other imports):
```python
import shlex

from pydantic import BaseModel

from macr.web.session import RunActive, RunManager
```

Add a request model above `create_app`:
```python
class LaunchRequest(BaseModel):
    command: str
    task: str
    repo: str
    test_cmd: str
    options: dict = {}
```

Change the signature `def create_app(runs_dir: Path, spa_dist: Path | None = None) -> FastAPI:` to:
```python
def create_app(runs_dir: Path, spa_dist: Path | None = None,
               manager: RunManager | None = None) -> FastAPI:
```

Immediately after `app = FastAPI(title="MACR Run Viewer")`, add:
```python
    run_manager = manager if manager is not None else RunManager()
    app.state.run_manager = run_manager
```

Add these routes (place them after the existing `/api/runs/...` GET routes, before the static mount block):
```python
    @app.post("/api/runs/launch")
    def launch(req: LaunchRequest):
        if req.command not in ("collab", "discuss"):
            raise HTTPException(status_code=400, detail=f"unknown command: {req.command}")
        if not req.task.strip():
            raise HTTPException(status_code=400, detail="task must not be blank")
        if not Path(req.repo).is_dir():
            raise HTTPException(status_code=400, detail=f"repo is not a directory: {req.repo}")
        test_cmd = shlex.split(req.test_cmd)
        if not test_cmd:
            raise HTTPException(status_code=400, detail="test_cmd must not be empty")
        try:
            session = run_manager.launch(command=req.command, task=req.task, repo=req.repo,
                                         test_cmd=test_cmd, options=req.options)
        except RunActive:
            raise HTTPException(status_code=409, detail="a live run is already active")
        return {"run_id": session.run_id, "command": session.command}

    @app.get("/api/runs/active")
    def active():
        s = run_manager.active
        if s is None:
            return Response(status_code=204)
        return {"run_id": s.run_id, "command": s.command, "status": s.status}
```

Add `Response` to the fastapi imports: change `from fastapi import FastAPI, HTTPException` to:
```python
from fastapi import FastAPI, HTTPException, Response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: PASS (existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add macr/web/app.py tests/test_web_app.py
git commit -m "feat(web): POST /api/runs/launch + GET /api/runs/active (409 concurrent, 400 invalid)"
```

---

### Task 7: WebSocket endpoint — replay buffer, stream, receive gate responses

**Files:**
- Modify: `macr/web/app.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_app.py`:

```python
import subprocess
from pathlib import Path as _Path

from macr.agents.base import FakeAgentBackend
from macr.web.live import start_run


def _init_repo2(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "i"],
                   cwd=path, check=True)


def test_websocket_streams_stages_gate_and_done(tmp_path):
    repo = tmp_path / "repo"
    _init_repo2(repo)

    def _editor(role, state):
        if role.name == "executor" and state.worktree_path:
            (_Path(state.worktree_path) / "a.txt").write_text("edited\n")

    def runner(session, **kw):
        claude = FakeAgentBackend({"planner": [{"summary": "p", "steps": ["s"]}],
                                   "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]})
        codex = FakeAgentBackend({"executor": [{"artifact": "d", "notes": "", "evidence": []}]}, on_run=_editor)
        return start_run(session, command="collab", task="t", repo=str(repo), test_cmd=["true"],
                         options={"runs_dir": tmp_path / "runs", "worktrees_dir": tmp_path / "wts",
                                  "claude_backend": claude, "codex_backend": codex})

    mgr = RunManager(runner=runner)
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    c.post("/api/runs/launch", json={"command": "collab", "task": "t", "repo": str(repo), "test_cmd": "true"})

    decision = None
    with c.websocket_connect("/api/runs/active/ws") as ws:
        seen_gate = False
        for _ in range(200):
            ev = ws.receive_json()
            if ev["type"] == "gate_request" and not seen_gate:
                seen_gate = True
                ws.send_json({"decision": "approve", "feedback": ""})
            if ev["type"] == "done":
                decision = ev["decision"]
                break
    assert seen_gate is True
    assert decision == "approve"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_app.py::test_websocket_streams_stages_gate_and_done -q`
Expected: FAIL — no `/api/runs/active/ws` route (connection rejected).

- [ ] **Step 3: Add the WebSocket route to `macr/web/app.py`**

Add imports: change the fastapi import line to include WebSocket bits:
```python
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
```
Add at the top with other imports:
```python
import asyncio
```

Add this route (after the `active()` route, before the static mount):
```python
    @app.websocket("/api/runs/active/ws")
    async def active_ws(websocket: WebSocket):
        await websocket.accept()
        session = run_manager.active
        if session is None:
            await websocket.close()
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def push(event: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        snapshot = session.subscribe(push)

        async def receive_responses() -> None:
            try:
                while True:
                    msg = await websocket.receive_json()
                    session.respond_gate(msg.get("decision", "reject"), msg.get("feedback", ""))
            except WebSocketDisconnect:
                pass

        recv_task = asyncio.create_task(receive_responses())
        try:
            for ev in snapshot:
                await websocket.send_json(ev)
                if ev["type"] == "done":
                    return
            while True:
                ev = await queue.get()
                await websocket.send_json(ev)
                if ev["type"] in ("done", "error"):
                    return
        except WebSocketDisconnect:
            pass
        finally:
            recv_task.cancel()
            session.unsubscribe(push)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_app.py::test_websocket_streams_stages_gate_and_done -q`
Expected: PASS. If it hangs, the gate response isn't reaching the run thread — verify `receive_responses` calls `session.respond_gate`.

- [ ] **Step 5: Run the full backend suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

```bash
git add macr/web/app.py tests/test_web_app.py
git commit -m "feat(web): WebSocket /api/runs/active/ws — replay buffer, stream events, receive gate responses"
```

---

## Phase C — Frontend

### Task 8: API client additions + routes + nav

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`

- [ ] **Step 1: Add to `frontend/src/api.ts`** (append):

```typescript
export interface LiveEvent {
  type: "stage" | "note" | "gate_request" | "status" | "done" | "error";
  stage?: Stage;
  text?: string;
  gate?: "consensus" | "final";
  data?: Record<string, unknown>;
  status?: string;
  run_id?: string;
  decision?: string | null;
  message?: string;
}

export interface LaunchBody {
  command: "collab" | "discuss";
  task: string;
  repo: string;
  test_cmd: string;
  options?: Record<string, unknown>;
}

export async function launchRun(body: LaunchBody): Promise<{ run_id: string; command: string }> {
  const res = await fetch("/api/runs/launch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
  return res.json();
}

export function activeWsUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/api/runs/active/ws`;
}
```

- [ ] **Step 2: Update `frontend/src/App.tsx`** to add routes + nav. Replace the file with:

```tsx
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";
import { LaunchForm } from "./LaunchForm";
import { LiveRun } from "./LiveRun";

export function App() {
  return (
    <BrowserRouter>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd", display: "flex", gap: 16 }}>
        <Link to="/" style={{ fontWeight: 600, textDecoration: "none" }}>MACR Run Viewer</Link>
        <Link to="/launch" style={{ textDecoration: "none" }}>+ New run</Link>
      </header>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/launch" element={<LaunchForm />} />
          <Route path="/live" element={<LiveRun />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
```

NOTE: `LaunchForm` and `LiveRun` are created in the next two tasks. A `tsc -b`/build here would fail on the missing modules — that is expected; the build is verified in Task 11.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts frontend/src/App.tsx
git commit -m "feat(frontend): launch API client + live-event types + /launch & /live routes"
```

---

### Task 9: LaunchForm component + test

**Files:**
- Create: `frontend/src/LaunchForm.tsx`, `frontend/src/LaunchForm.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/LaunchForm.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LaunchForm } from "./LaunchForm";

test("submits a launch request with the entered fields", async () => {
  const calls: any[] = [];
  globalThis.fetch = ((url: string, init: any) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ run_id: "R1", command: "collab" }) });
  }) as unknown as typeof fetch;

  render(<MemoryRouter><LaunchForm /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/task/i), { target: { value: "add a function" } });
  fireEvent.change(screen.getByLabelText(/repo/i), { target: { value: "/tmp/r" } });
  fireEvent.change(screen.getByLabelText(/test command/i), { target: { value: "pytest -q" } });
  fireEvent.click(screen.getByRole("button", { name: /launch/i }));

  await waitFor(() => expect(calls.length).toBe(1));
  expect(calls[0].url).toBe("/api/runs/launch");
  expect(calls[0].body).toMatchObject({ command: "collab", task: "add a function",
    repo: "/tmp/r", test_cmd: "pytest -q" });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/LaunchForm.test.tsx`
Expected: FAIL — cannot resolve `./LaunchForm`.

- [ ] **Step 3: Create `frontend/src/LaunchForm.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { launchRun } from "./api";

export function LaunchForm() {
  const nav = useNavigate();
  const [command, setCommand] = useState<"collab" | "discuss">("collab");
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState("");
  const [testCmd, setTestCmd] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await launchRun({ command, task, repo, test_cmd: testCmd });
      nav("/live");
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 12, maxWidth: 560 }}>
      <label> Command
        <select value={command} onChange={(e) => setCommand(e.target.value as "collab" | "discuss")}>
          <option value="collab">collab</option>
          <option value="discuss">discuss</option>
        </select>
      </label>
      <label> Task
        <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} />
      </label>
      <label> Repo
        <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="/path/to/repo" />
      </label>
      <label> Test command
        <input value={testCmd} onChange={(e) => setTestCmd(e.target.value)} placeholder="pytest -q" />
      </label>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <button type="submit">Launch</button>
    </form>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/LaunchForm.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/LaunchForm.tsx frontend/src/LaunchForm.test.tsx
git commit -m "feat(frontend): LaunchForm — start a collab/discuss run"
```

---

### Task 10: LiveRun + GatePanel + test

**Files:**
- Create: `frontend/src/GatePanel.tsx`, `frontend/src/LiveRun.tsx`, `frontend/src/LiveRun.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/LiveRun.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LiveRun } from "./LiveRun";

// Minimal mock WebSocket capturing sends and exposing a way to push server events.
class MockWS {
  static last: MockWS | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  constructor(_url: string) { MockWS.last = this; }
  send(data: string) { this.sent.push(data); }
  close() {}
  push(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
}

test("renders streamed stages, shows gate panel, sends response", async () => {
  (globalThis as any).WebSocket = MockWS as unknown as typeof WebSocket;
  render(<MemoryRouter><LiveRun /></MemoryRouter>);
  const ws = MockWS.last!;

  act(() => ws.push({ type: "stage", stage: { kind: "plan", label: "Planner", agent: "claude", status: null, body: {} } }));
  await waitFor(() => expect(screen.getByText("Planner")).toBeInTheDocument());

  act(() => ws.push({ type: "gate_request", gate: "final", data: { tests: { passed: true } } }));
  await waitFor(() => expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: /approve/i }));
  expect(JSON.parse(ws.sent[0])).toMatchObject({ decision: "approve" });

  act(() => ws.push({ type: "done", run_id: "R1", decision: "approve" }));
  await waitFor(() => expect(screen.getByText(/R1/)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/LiveRun.test.tsx`
Expected: FAIL — cannot resolve `./LiveRun`.

- [ ] **Step 3: Create `frontend/src/GatePanel.tsx`**

```tsx
import { useState } from "react";

export function GatePanel({ gate, onRespond }: {
  gate: "consensus" | "final";
  onRespond: (decision: "approve" | "reject", feedback: string) => void;
}) {
  const [feedback, setFeedback] = useState("");
  return (
    <div style={{ border: "2px solid #88a", borderRadius: 6, padding: 12, margin: "12px 0" }}>
      <strong>Human gate: {gate}</strong>
      <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)}
                placeholder="optional feedback / annotation" rows={2} style={{ display: "block", width: "100%", margin: "8px 0" }} />
      <button onClick={() => onRespond("approve", feedback)}>Approve</button>{" "}
      <button onClick={() => onRespond("reject", feedback)}>Reject</button>
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/LiveRun.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { activeWsUrl, type LiveEvent, type Stage } from "./api";
import { StageCard } from "./StageCard";
import { GatePanel } from "./GatePanel";

export function LiveRun() {
  const [stages, setStages] = useState<Stage[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [gate, setGate] = useState<"consensus" | "final" | null>(null);
  const [done, setDone] = useState<{ run_id: string; decision: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(activeWsUrl());
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev: LiveEvent = JSON.parse(e.data);
      if (ev.type === "stage" && ev.stage) setStages((s) => [...s, ev.stage!]);
      else if (ev.type === "note" && ev.text) setNotes((n) => [...n, ev.text!]);
      else if (ev.type === "gate_request") setGate(ev.gate ?? "final");
      else if (ev.type === "status" && ev.status === "running") setGate(null);
      else if (ev.type === "done") setDone({ run_id: ev.run_id!, decision: ev.decision ?? null });
      else if (ev.type === "error") setError(ev.message ?? "error");
    };
    return () => ws.close();
  }, []);

  function respond(decision: "approve" | "reject", feedback: string) {
    wsRef.current?.send(JSON.stringify({ decision, feedback }));
    setGate(null);
  }

  return (
    <div>
      <h2>Live run</h2>
      {error && <p style={{ color: "crimson" }}>Error: {error}</p>}
      {gate && <GatePanel gate={gate} onRespond={respond} />}
      {done && (
        <p>Done — decision: <strong>{done.decision}</strong>{" · "}
          <Link to={`/runs/${done.run_id}`}>view saved run</Link></p>
      )}
      <div>{stages.map((s, i) => <StageCard key={i} stage={s} />)}</div>
      {notes.length > 0 && (
        <pre style={{ background: "#f6f6f6", padding: 8, fontSize: 12 }}>{notes.join("\n")}</pre>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/LiveRun.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 6: Run the full frontend suite + commit**

Run: `cd frontend && npm test`
Expected: all pass (RunList 2 + RunDetail 1 + LaunchForm 1 + LiveRun 1 = 5).

```bash
git add frontend/src/GatePanel.tsx frontend/src/LiveRun.tsx frontend/src/LiveRun.test.tsx
git commit -m "feat(frontend): LiveRun streaming timeline + GatePanel (approve/reject/feedback over WS)"
```

---

### Task 11: Build + end-to-end smoke

**Files:** none new (verification + README update)

- [ ] **Step 1: Typecheck + build the SPA**

Run: `cd frontend && npm run build`
Expected: `tsc -b` passes (all components exist now) and Vite writes `frontend/dist/`.

- [ ] **Step 2: Full frontend test suite**

Run: `cd frontend && npm test`
Expected: all pass (5 tests).

- [ ] **Step 3: Full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 4: End-to-end smoke with a fake-backed launch (no real CLIs).**

This confirms launch → WS → gate → done over real HTTP. Create a throwaway script:

```bash
cat > /tmp/macr_live_smoke.py <<'PY'
import subprocess, threading, time
from pathlib import Path
from fastapi.testclient import TestClient
from macr.agents.base import FakeAgentBackend
from macr.web.app import create_app
from macr.web.session import RunManager
from macr.web.live import start_run

tmp = Path("/tmp/macr-live-smoke"); 
import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
repo = tmp / "repo"; repo.mkdir()
subprocess.run(["git","init","-q"], cwd=repo, check=True)
(repo/"a.txt").write_text("hi\n")
subprocess.run(["git","add","-A"], cwd=repo, check=True)
subprocess.run(["git","-c","user.email=t@t","-c","user.name=t","commit","-q","-m","i"], cwd=repo, check=True)

def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path)/"a.txt").write_text("edited\n")

def runner(session, **kw):
    claude = FakeAgentBackend({"planner":[{"summary":"p","steps":["s"]}],
                              "reviewer":[{"summary":"ok","findings":[],"decision":"approve"}]})
    codex = FakeAgentBackend({"executor":[{"artifact":"d","notes":"","evidence":[]}]}, on_run=_editor)
    return start_run(session, command="collab", task="t", repo=str(repo), test_cmd=["true"],
                     options={"runs_dir": tmp/"runs", "worktrees_dir": tmp/"wts",
                              "claude_backend": claude, "codex_backend": codex})

app = create_app(runs_dir=tmp/"runs", manager=RunManager(runner=runner))
c = TestClient(app)
print("launch:", c.post("/api/runs/launch", json={"command":"collab","task":"t","repo":str(repo),"test_cmd":"true"}).json())
decision = None
with c.websocket_connect("/api/runs/active/ws") as ws:
    for _ in range(200):
        ev = ws.receive_json()
        if ev["type"] == "gate_request":
            ws.send_json({"decision":"approve","feedback":""})
        if ev["type"] == "done":
            decision = ev["decision"]; break
print("final decision:", decision)
assert decision == "approve"
print("SMOKE OK")
PY
.venv/bin/python /tmp/macr_live_smoke.py
```
Expected: prints `launch: {...}`, `final decision: approve`, `SMOKE OK`.

- [ ] **Step 5: Update `macr/web/README.md`** — append a "Live driving" section:

```markdown

## Live driving (sub-project 2)

`+ New run` in the UI (`/launch`) starts a collab/discuss run; `/live` streams its
progress over a WebSocket and prompts for the human gates (approve / reject / annotate)
in the browser. One live run at a time. Requires the `claude` + `codex` CLIs on PATH.
```

- [ ] **Step 6: Commit**

```bash
git add macr/web/README.md
git commit -m "docs(web): live-driving usage; verified launch→stream→gate→done end-to-end"
```

---

## Self-Review

**Spec coverage:**
- Single active run, collab+discuss, gates approve/reject/feedback, rounds auto-advance: Tasks 2 (single active), 5 (`auto_discussion_control`), 5/7 (gates) ✓
- Thread runner with injected WebView + gate bridge (approach A): Tasks 1, 4, 5 ✓
- Event protocol (stage/note/gate_request/status/done/error): Tasks 4 (stage/note), 1 (status/gate_request), 5 (done/error) ✓
- Endpoints launch(409/400)/active/ws: Tasks 6, 7 ✓
- WebView reuses ① Stage shape; LiveRun reuses StageCard: Tasks 4, 10 ✓
- run_id controlled by session, link to ① viewer: Tasks 3, 5 (`session.run_id`), 10 (`/runs/:id` link) ✓
- Reconnect replays buffer: Task 7 (`snapshot` sent first) ✓
- Error → error event, session preserved: Task 5 (try/except emits error) ✓
- TDD backend + light frontend: every task ✓
- YAGNI (no concurrency/hard-cancel/interjection/auth/run-API): no such tasks ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. The two "build would fail until later task" notes (Task 8) are intentional ordering guidance.

**Type consistency:** `RunSession`/`RunManager`/`RunActive` signatures consistent across Tasks 1–2, 5–7. `start_run(session, *, command, task, repo, test_cmd, options)` identical in Tasks 5, 6 (runner), 7. `emit` event shapes (`{"type":"stage","stage":{...}}`, `{"type":"note","text":...}`, `{"type":"gate_request","gate":...,"data":...}`, `{"type":"done","run_id":...,"decision":...}`) identical between backend (Tasks 1/4/5) and frontend `LiveEvent` (Task 8) + `LiveRun` (Task 10). `create_app(runs_dir, spa_dist=None, manager=None)` consistent Tasks 6/7. Gate response shape `{decision, feedback}` identical in Task 1 (`respond_gate`), 7 (receive), 10 (send).
