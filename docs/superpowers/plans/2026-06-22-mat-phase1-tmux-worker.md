# Multi-Agent Term — Phase 1: Worker → tmux (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Make the orchestrator's Worker (executor) run in a tmux pane via a new `TmuxExecutorBackend` that satisfies the existing `AgentBackend` protocol — observable live, structured output preserved — without changing the orchestrator's logic.

**Architecture:** `TmuxExecutorBackend.run_role` spawns `codex exec … --json` (same argv as `CodexCliBackend`) in a tmux pane via Phase 0's `TmuxRuntime`, polls `TmuxControl` → feeds `AgentObserver` (live state to an obs-sink), waits for `pane_dead`, then `snapshot`s the pane and parses the output with the existing `parse_codex_stream`/`extract_json_object`/`validate_with_retry` into an `ExecutorOutput` `Message`. Injected into `run_collab`/`run_discuss` via a new optional `worker_backend` param + a `--worker-runtime {cli,tmux}` CLI flag (default `cli`, unchanged).

**Tech Stack:** Python stdlib + Phase 0 `macr/runtime/`. Spec: `docs/superpowers/specs/2026-06-22-mat-phase1-tmux-worker-design.md`. Tested with `FakeTmuxTransport` (no real tmux/codex).

---

## File Structure
- `macr/runtime/observer.py` (modify) — `refresh_from_panes(infos=None)` accepts pre-fetched infos.
- `macr/runtime/tmux_executor.py` (new) — `TmuxExecutorBackend`.
- `macr/collab_orchestrator.py` (modify) — `run_collab(..., worker_backend=None)`; `_implementation_loop` uses `worker_backend or codex_backend`.
- `macr/discussion.py` (modify) — `run_discuss(..., worker_backend=None)` threaded into its impl loop.
- `macr/cli.py` (modify) — `--worker-runtime {cli,tmux}` for collab+discuss.
- Tests: `tests/test_runtime_tmux_executor.py`, extend `tests/test_runtime_observer.py`; integration in `tests/test_collab_orchestrator.py`.
- `scripts/mat_tmux_smoke.py` (extend) + `CHANGELOG.md`.

---

## Task 1: observer.refresh_from_panes accepts pre-fetched infos

**Files:** modify `macr/runtime/observer.py`; test `tests/test_runtime_observer.py`.

- [ ] **Step 1: failing test** — append:

```python
def test_refresh_from_panes_accepts_prefetched_infos():
    from macr.runtime.tmux_runtime import AgentInfo
    rt = _runtime_with_agent()
    obs = AgentObserver(rt)
    obs.refresh_from_panes([AgentInfo(agent_id="w", pane="%12", dead=True, dead_status=0)])
    assert obs.state_of("w").state is AgentState.done
```

- [ ] **Step 2: run red** — `PYTHONPATH=. python3 -m pytest tests/test_runtime_observer.py -q` → FAIL (`refresh_from_panes() takes 1 positional arg`).
- [ ] **Step 3: impl** — change signature:

```python
    def refresh_from_panes(self, infos=None) -> None:
        for info in (infos if infos is not None else self._rt.list_agents()):
            if info.dead:
                state = AgentState.done if info.dead_status == 0 else AgentState.failed
                self._apply(info.agent_id, Detection(app=_app_of(info), state=state, confidence=100))
```

- [ ] **Step 4: run green** — observer suite passes.
- [ ] **Step 5: commit** — `feat(runtime): observer.refresh_from_panes accepts pre-fetched pane infos`

---

## Task 2: TmuxExecutorBackend — spawn, observe, parse → ExecutorOutput

**Files:** create `macr/runtime/tmux_executor.py`; test `tests/test_runtime_tmux_executor.py`.

- [ ] **Step 1: failing test** — create `tests/test_runtime_tmux_executor.py`:

```python
import json

from macr.collab_roles import EXECUTOR_C
from macr.runtime.agent_state import AgentState
from macr.runtime.tmux_control import FakeTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime
from macr.runtime.tmux_executor import TmuxExecutorBackend
from macr.schemas import SharedState


def _be(*lines):
    return ["%begin 1 1 1", *lines, "%end 1 1 1"]


def _codex_json_line(obj):
    # codex --json stream: one event carrying the final message text
    return json.dumps({"msg": {"type": "agent_message", "message": json.dumps(obj)}})


def _state(tmp_path):
    s = SharedState(run_id="R1", task="do it")
    s.worktree_path = str(tmp_path)
    return s


def test_run_role_spawns_observes_and_returns_executor_output(tmp_path):
    t = FakeTmuxTransport()
    exec_obj = {"artifact": "added hello()", "notes": "ok", "evidence": []}
    out_line = _codex_json_line(exec_obj)
    # spawn → %pane
    t.feed(*_be("%12"))
    # iter 1: list-panes alive, with an interleaved OSC running marker as %output BEFORE the block
    t.feed("%output %12 \x1b]7748;wispterm-agent;state=running;app=codex\x07")
    t.feed(*_be("%12\t9\tcodex\t0\t"))
    # iter 2: list-panes dead status 0
    t.feed(*_be("%12\t9\tcodex\t1\t0"))
    # snapshot (capture-pane) returns the codex json line
    t.feed(*_be(out_line))

    obs_events = []
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0, obs_sink=obs_events.append)
    msg = be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")

    assert msg.content["artifact"] == "added hello()"
    # spawn used codex exec --json in the worktree
    assert any(s.startswith("split-window") and "codex exec" in s and "--json" in s for s in t.sent)
    # observed running at some point
    assert any(e["state"] == AgentState.running.value for e in obs_events)
    assert any(e["state"] == AgentState.done.value for e in obs_events)
```

- [ ] **Step 2: run red** — FAIL (`No module named 'macr.runtime.tmux_executor'`).
- [ ] **Step 3: impl** — create `macr/runtime/tmux_executor.py`:

```python
"""AgentBackend that runs the Worker (executor) inside a tmux pane and observes
it live, preserving the structured ExecutorOutput contract. Drop-in for the
codex backend in the orchestrator's implementation loop. See the Phase 1 spec."""
from __future__ import annotations

import time
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import extract_json_object, message_from_content, validate_with_retry
from macr.agents.cli_backend import _base_prompt
from macr.agents.trace import parse_codex_stream, stream_error
from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_runtime import TmuxRuntime
from macr.schemas import Message


class TmuxExecutorBackend:
    name = "tmux_executor"

    def __init__(self, runtime: TmuxRuntime, *, observer: AgentObserver | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 model: str | None = None, enable_subagents: bool = True,
                 timeout: int = 1800, poll_interval: float = 0.2,
                 capture_recent: int = 5000,
                 obs_sink: Callable[[dict], None] | None = None,
                 time_fn: Callable[[], float] = time.monotonic,
                 sleep_fn: Callable[[float], None] = time.sleep):
        self._rt = runtime
        self._obs = observer or AgentObserver(runtime)
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.model = model
        self.enable_subagents = enable_subagents
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.capture_recent = capture_recent
        self._obs_sink = obs_sink
        self._time = time_fn
        self._sleep = sleep_fn
        self._seq = 0

    def _argv(self, prompt: str, cwd: str) -> list[str]:
        argv = [self.codex_bin, "exec", prompt, "--cd", cwd, "--sandbox", self.sandbox, "--json"]
        if not self.enable_subagents:
            argv += ["-c", "features.multi_agent=false"]
        if self.model:
            argv += ["--model", self.model]
        return argv

    def _emit(self, agent_id: str, attempt: int) -> None:
        if self._obs_sink is None:
            return
        d = self._obs.state_of(agent_id)
        self._obs_sink({"agent_id": agent_id, "attempt": attempt,
                        "app": d.app.value, "state": d.state.value, "confidence": d.confidence})

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."
        self._seq += 1
        agent_id = f"{role.name}-{run_id}-{self._seq}"
        ctrl = self._rt._c  # TmuxControl
        pane = self._rt.spawn_agent(agent_id, self._argv(prompt, cwd), cwd)

        deadline = self._time() + self.timeout
        info = None
        while True:
            infos = {i.agent_id: i for i in self._rt.list_agents()}
            for n in ctrl.poll():
                if n.kind == "output" and n.pane == pane:
                    self._obs.on_output(pane, n.data)
                    self._emit(agent_id, self._seq)
            info = infos.get(agent_id)
            if info is not None and info.dead:
                self._obs.refresh_from_panes(list(infos.values()))
                self._emit(agent_id, self._seq)
                break
            if self._time() > deadline:
                self._rt.kill(agent_id)
                raise AgentError(f"tmux worker '{agent_id}' timed out after {self.timeout}s")
            self._sleep(self.poll_interval)

        out = self._rt.snapshot(agent_id, recent=self.capture_recent)
        lines = out.splitlines()
        if info.dead_status not in (0, None):
            detail = stream_error(lines, source="codex") or f"exit {info.dead_status}"
            raise AgentError(f"codex worker exited {info.dead_status}: {detail}")
        final_text, subs = parse_codex_stream(lines)
        content = validate_with_retry(role, lambda extra: extract_json_object(final_text))
        if trace is not None:
            try:
                trace.capture(lines, subs)
            except OSError:
                pass
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
```

- [ ] **Step 4: run green** — `PYTHONPATH=. python3 -m pytest tests/test_runtime_tmux_executor.py -q`.
- [ ] **Step 5: commit** — `feat(runtime): TmuxExecutorBackend — run Worker in tmux pane, observe live, parse ExecutorOutput`

---

## Task 3: error + timeout handling

**Files:** test `tests/test_runtime_tmux_executor.py` (add).

- [ ] **Step 1: failing tests** — append:

```python
import pytest
from macr.agent import AgentError


def test_nonzero_exit_raises_agent_error(tmp_path):
    t = FakeTmuxTransport()
    t.feed(*_be("%12"))                          # spawn
    t.feed(*_be("%12\t9\tcodex\t1\t3"))          # dead, status 3
    t.feed(*_be("Error: boom"))                  # snapshot output
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0)
    with pytest.raises(AgentError) as ei:
        be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")
    assert "exited 3" in str(ei.value)


def test_timeout_kills_and_raises(tmp_path):
    t = FakeTmuxTransport()
    t.feed(*_be("%12"))                           # spawn
    t.feed(*_be("%12\t9\tcodex\t0\t"))            # iter1 alive
    t.feed(*_be())                                # kill-pane response
    clock = iter([0.0, 5.0, 5.0])                 # start, check>deadline
    rt = TmuxRuntime(TmuxControl(t))
    be = TmuxExecutorBackend(rt, poll_interval=0, timeout=1,
                             time_fn=lambda: next(clock))
    with pytest.raises(AgentError) as ei:
        be.run_role(EXECUTOR_C, _state(tmp_path), run_id="R1", task_id="R1")
    assert "timed out" in str(ei.value)
    assert any(s.startswith("kill-pane") for s in t.sent)
```

- [ ] **Step 2: run red** then **Step 3** (already handled by Task 2 impl; if `time_fn` ordering needs a tweak, adjust so `deadline` is computed once at entry and checked after the liveness check).
- [ ] **Step 4: run green**.
- [ ] **Step 5: commit** — `test(runtime): TmuxExecutorBackend nonzero-exit + timeout paths`

---

## Task 4: orchestrator injection (worker_backend) + integration

**Files:** modify `macr/collab_orchestrator.py`, `macr/discussion.py`; test `tests/test_collab_orchestrator.py`.

- [ ] **Step 1: failing test** — add an integration test injecting a stub `worker_backend` (any `AgentBackend`, e.g. a `FakeAgentBackend` scripted for "executor") into `run_collab`, asserting it is used instead of `codex_backend`:

```python
def test_run_collab_uses_injected_worker_backend(tmp_path):
    repo = tmp_path / "repo"; _init_repo(repo)
    used = {"worker": False}
    class Spy(FakeAgentBackend):
        def run_role(self, role, state, **kw):
            used["worker"] = True
            return super().run_role(role, state, **kw)
    worker = Spy({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    state = run_collab(
        "do it", repo=repo, test_cmd=["true"],
        claude_backend=FakeAgentBackend({"planner": [_plan()], "reviewer": [_review("approve")]}),
        codex_backend=FakeAgentBackend({}),  # should NOT be called for executor
        worker_backend=worker,
        runs_dir=tmp_path/"runs", worktrees_dir=tmp_path/"wts",
        human_gate=_approve, printer=lambda *_: None)
    assert used["worker"] is True
```

- [ ] **Step 2: run red** — `TypeError: run_collab() got an unexpected keyword argument 'worker_backend'`.
- [ ] **Step 3: impl** — add `worker_backend: AgentBackend | None = None` to `run_collab`/`run_discuss`; pass into `_implementation_loop`; inside, use `worker = worker_backend or codex_backend` for the executor `run_role`. Leave everything else untouched.
- [ ] **Step 4: run green** — full collab + discuss suites pass (default path unchanged).
- [ ] **Step 5: commit** — `feat: optional worker_backend injection in run_collab/run_discuss (default unchanged)`

---

## Task 5: CLI flag + smoke + README + CHANGELOG

**Files:** modify `macr/cli.py`, `scripts/mat_tmux_smoke.py`, `CHANGELOG.md`.

- [ ] **Step 1: failing test** — assert `macr collab --worker-runtime tmux …` constructs a `TmuxExecutorBackend` (inject a fake builder / assert via a `--dry-run` or a seam). Keep it light: a unit test on a small `build_worker_backend(runtime_kind, ...)` helper returning the right type.
- [ ] **Step 2–4: impl + green** — add `--worker-runtime {cli,tmux}` (default `cli`) to collab+discuss parsers; when `tmux`, build `TmuxExecutorBackend(TmuxRuntime(TmuxControl(SubprocessTmuxTransport(...))), sandbox="workspace-write", …)` and pass as `worker_backend`. `cli` → leave `None` (unchanged).
- [ ] **Step 5: real-tmux smoke** — extend `scripts/mat_tmux_smoke.py` (or add `mat_worker_smoke.py`) to run a tiny `bash -c 'printf "%s" "{json}"'` as the pane "codex" and assert the backend parses it. Manual, non-CI.
- [ ] **Step 6: CHANGELOG + commit** — add Phase 1 entry with commit hashes; `feat(cli): --worker-runtime tmux runs the Worker in a tmux pane`.

---

## Self-Review
- Spec coverage: TmuxExecutorBackend (T2), errors/timeout (T3), injection point (T4), CLI flag + smoke (T5), observer tweak (T1) ✓
- Contract preserved: returns `ExecutorOutput` `Message` via existing `validate_with_retry`/`message_from_content`; orchestrator/gates/worktree untouched ✓
- Injectable/testable: `FakeTmuxTransport` + `time_fn`/`sleep_fn`/`obs_sink`; no real tmux/codex in CI ✓
- Default unchanged: `--worker-runtime cli` keeps `CodexCliBackend`; existing tests green ✓
- Fact-source/verification boundary: pane exit = observed/done only; `verified` still from diff+tests+review+deterministic gate ✓
