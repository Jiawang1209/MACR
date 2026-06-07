# MACR Stage C2 — rich Two-Pane Live View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `macr discuss --tui`: render the C1 discussion as a `rich` two-pane live view (Claude left, Codex right, bottom status/human panel), via a `DiscussionView` abstraction whose default `ConsoleView` preserves C1's exact single-terminal behavior.

**Architecture:** Introduce `macr/discussion_view.py` with a `DiscussionView` Protocol + `ConsoleView` (default, = C1 prints) / `SilentView` / `FakeView` / `TwoPaneView` (rich). Refactor `run_discuss` to call structured `view.plan/turn/interjection/status/consensus/note` instead of a flat `printer`, and pass `printer=view.status` to the unchanged `_implementation_loop`. CLI gains `--tui`; the TUI view supplies control/gate callables that pause/resume `rich.Live` around input. Non-tty auto-falls-back to console.

**Tech Stack:** Python 3.11+, Pydantic v2, **rich** (new dependency), pytest. **Isolation:** `.venv/bin/...` only. Commits: plain, NO Co-Authored-By / AI attribution. One git command at a time.

**Spec:** `docs/superpowers/specs/2026-06-07-macr-stage-c2-two-pane-tui-design.md`.

**Current interfaces (verified):**
- `macr/discussion.py`: `run_discuss(..., printer: Callable = print, ...)`; has module-level `_print_plan`/`_print_turn`; calls `discussion_control(state, round_no, printer=printer)`, `consensus_gate(state, printer=printer)`, `human_gate(state, printer=printer)`, and `_implementation_loop(..., printer=printer)`.
- `macr/discussion_control.py`: `interactive_discussion_control(state, round_no, *, input_fn=input, printer=print)`, `auto_discussion_control`, `ControlDecision`.
- `macr/human_gate.py`: `consensus_human_gate(state, *, input_fn=input, printer=print, timestamp=None)`, `collab_human_gate`.
- `macr/cli.py`: `_discuss_command(args, *, claude_backend, codex_backend, impl_codex_backend, discussion_control, consensus_gate, human_gate)`; `main(..., view=...)` does not exist yet; the `discuss` subparser is in `_parse_args`.

**Conventions:** TDD per task. 142 tests currently pass; keep them green.

---

### Task 1: Add `rich` dependency

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Add `rich` to `[project] dependencies` in `pyproject.toml`.** The dependencies list currently is `["pydantic>=2.6", "anthropic>=0.40"]`. Change it to:
```toml
dependencies = [
    "pydantic>=2.6",
    "anthropic>=0.40",
    "rich>=13.0",
]
```

- [ ] **Step 2: Install into the project venv** (network; may take ~30s):
```bash
cd /Users/liuyue/Desktop/Github_repos/MACR
.venv/bin/pip install -e ".[dev]"
```
Then verify: `.venv/bin/python -c "import rich; print('rich', rich.__version__)"` → prints a version.

- [ ] **Step 3: Full suite still green** — `.venv/bin/pytest -q` (expect 142 passed).

- [ ] **Step 4: Commit**
```bash
git add pyproject.toml
git commit -m "build: add rich dependency for the two-pane TUI view"
```

---

### Task 2: `discussion_view.py` — DiscussionView + ConsoleView/SilentView/FakeView

**Files:** Create `macr/discussion_view.py`, `tests/test_discussion_view.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_discussion_view.py`:
```python
from macr.discussion_view import ConsoleView, FakeView, SilentView


def _plan():
    return {"summary": "do the thing", "steps": ["step-one", "step-two"]}


def _turn():
    return {"response": "I disagree", "agreements": ["a"], "concerns": ["risky"], "revised_steps": ["r1"]}


def test_console_view_plan_outputs_agent_and_steps():
    out = []
    v = ConsoleView(out=out.append)
    v.plan("claude", _plan())
    joined = "\n".join(out)
    assert "claude" in joined and "do the thing" in joined and "step-one" in joined


def test_console_view_turn_and_interjection_and_consensus():
    out = []
    v = ConsoleView(out=out.append)
    v.turn("codex", 2, _turn())
    v.interjection(2, "please add rollback")
    v.consensus({"summary": "agreed plan"})
    joined = "\n".join(out)
    assert "codex" in joined and "I disagree" in joined and "risky" in joined
    assert "rollback" in joined
    assert "agreed plan" in joined


def test_silent_view_is_noop():
    v = SilentView()
    v.plan("claude", _plan())
    v.turn("codex", 1, _turn())
    v.note("x")
    v.status("y")  # must not raise


def test_fake_view_records_events_in_order():
    v = FakeView()
    v.plan("claude", _plan())
    v.turn("codex", 1, _turn())
    v.interjection(1, "hi")
    v.consensus({"summary": "c"})
    kinds = [e[0] for e in v.events]
    assert kinds == ["plan", "turn", "interjection", "consensus"]
    assert v.events[0][1] == "claude"
    assert v.events[1][1] == "codex" and v.events[1][2] == 1


def test_views_are_context_managers():
    for v in (ConsoleView(out=lambda *_: None), SilentView(), FakeView()):
        with v as entered:
            assert entered is v
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discussion_view.py -v`.

- [ ] **Step 3: Implement `macr/discussion_view.py`** (only the three simple views here; `TwoPaneView` is Task 3):
```python
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class DiscussionView(Protocol):
    def plan(self, agent: str, content: dict) -> None: ...
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...
    def interjection(self, round_no: int, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def consensus(self, content: dict) -> None: ...
    def note(self, text: str) -> None: ...


class ConsoleView:
    """Default view: single-terminal turn-by-turn printing (identical to Stage C1)."""

    def __init__(self, out: Callable[[str], None] = print):
        self._out = out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None:
        self._out(f"\n━━━ {agent} · 第 0 轮(计划)━━━")
        self._out(content.get("summary", ""))
        for s in content.get("steps", []):
            self._out(f"  - {s}")

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self._out(f"\n━━━ {agent} · 第 {round_no} 轮 ━━━")
        if content.get("concerns"):
            self._out("[concerns] " + "; ".join(content["concerns"]))
        self._out("[response] " + content.get("response", ""))
        if content.get("revised_steps"):
            self._out("[revised steps] " + "; ".join(content["revised_steps"]))

    def interjection(self, round_no: int, text: str) -> None:
        self._out(f"\n━━━ 你(human)· 第 {round_no} 轮后插话 ━━━\n{text}")

    def status(self, text: str) -> None:
        self._out(text)

    def consensus(self, content: dict) -> None:
        self._out(f"\n━━━ 共识 / Consensus ━━━\n{content.get('summary', '')}")

    def note(self, text: str) -> None:
        self._out(text)


class SilentView:
    """No-op view (tests / non-interactive)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None: ...
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...
    def interjection(self, round_no: int, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def consensus(self, content: dict) -> None: ...
    def note(self, text: str) -> None: ...


class FakeView:
    """Records every display event for assertions."""

    def __init__(self):
        self.events: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None:
        self.events.append(("plan", agent, content))

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self.events.append(("turn", agent, round_no, content))

    def interjection(self, round_no: int, text: str) -> None:
        self.events.append(("interjection", round_no, text))

    def status(self, text: str) -> None:
        self.events.append(("status", text))

    def consensus(self, content: dict) -> None:
        self.events.append(("consensus", content))

    def note(self, text: str) -> None:
        self.events.append(("note", text))
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_discussion_view.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/discussion_view.py tests/test_discussion_view.py
git commit -m "feat: add DiscussionView interface with console, silent, and fake views"
```

---

### Task 3: `TwoPaneView` — rich two-pane renderer

**Files:** Modify `macr/discussion_view.py` (append `TwoPaneView`); Modify `tests/test_discussion_view.py` (append tests).

- [ ] **Step 1: Append failing tests to `tests/test_discussion_view.py`:**
```python
def test_two_pane_routes_to_buffers():
    from macr.discussion_view import TwoPaneView
    v = TwoPaneView(enabled=False)  # no Live; buffers only
    v.plan("claude", {"summary": "csum", "steps": ["cs1"]})
    v.plan("codex", {"summary": "xsum", "steps": ["xs1"]})
    v.turn("claude", 1, {"response": "cresp", "concerns": [], "revised_steps": []})
    v.interjection(1, "human-says")
    v.status("tests passed=True")
    assert any("csum" in l for l in v.claude_lines)
    assert any("xsum" in l for l in v.codex_lines)
    assert any("cresp" in l for l in v.claude_lines)
    assert any("human-says" in l for l in v.status_lines)
    assert any("passed=True" in l for l in v.status_lines)


def test_two_pane_render_contains_text():
    from rich.console import Console
    from macr.discussion_view import TwoPaneView
    v = TwoPaneView(enabled=False)
    v.plan("claude", {"summary": "HELLO-CLAUDE", "steps": []})
    v.plan("codex", {"summary": "HELLO-CODEX", "steps": []})
    rec = Console(record=True, width=120)
    rec.print(v._render())
    text = rec.export_text()
    assert "Claude" in text and "Codex" in text
    assert "HELLO-CLAUDE" in text and "HELLO-CODEX" in text


def test_two_pane_non_tty_does_not_start_live():
    from macr.discussion_view import TwoPaneView
    v = TwoPaneView(enabled=False)
    with v:
        v.note("x")  # must not raise, no Live
    assert v._live is None


def test_two_pane_control_delegates(monkeypatch):
    from macr.discussion_view import TwoPaneView
    from macr.schemas import SharedState
    v = TwoPaneView(enabled=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "c")
    d = v.control(SharedState(run_id="R1", user_query="q", topic="z"), 1)
    assert d.action == "continue"
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discussion_view.py -k two_pane -v`.

- [ ] **Step 3: Append `TwoPaneView` to `macr/discussion_view.py`** (add the import line for the gate/control functions at the END of the file's imports area is unnecessary — import them lazily inside methods to avoid any import-order concerns):
```python
class TwoPaneView:
    """rich two-pane live view: Claude (left) / Codex (right) + bottom status panel.

    Falls back to buffer-only (no Live) when `enabled` is False or stdout is not a TTY.
    Provides control/gate methods that pause the Live around interactive input.
    """

    def __init__(self, *, console=None, enabled: bool | None = None, topic: str = ""):
        from rich.console import Console

        self.console = console or Console()
        self.enabled = self.console.is_terminal if enabled is None else enabled
        self.topic = topic
        self.claude_lines: list[str] = []
        self.codex_lines: list[str] = []
        self.status_lines: list[str] = []
        self._live = None

    # --- lifecycle ---
    def __enter__(self):
        if self.enabled:
            from rich.live import Live

            self._live = Live(self._render(), console=self.console, refresh_per_second=8, screen=False)
            self._live.__enter__()
        return self

    def __exit__(self, *exc):
        if self._live is not None:
            self._live.__exit__(*exc)
            self._live = None
        return False

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _render(self):
        from rich.layout import Layout
        from rich.panel import Panel

        layout = Layout()
        layout.split_column(
            Layout(Panel(self.topic or "MACR discuss"), size=3, name="header"),
            Layout(name="body"),
            Layout(Panel("\n".join(self.status_lines[-12:]), title="你 / 状态"), size=10, name="status"),
        )
        layout["body"].split_row(
            Layout(Panel("\n".join(self.claude_lines[-60:]), title="Claude")),
            Layout(Panel("\n".join(self.codex_lines[-60:]), title="Codex")),
        )
        return layout

    def _pane(self, agent: str) -> list[str]:
        return self.claude_lines if agent == "claude" else self.codex_lines

    # --- display ---
    def plan(self, agent: str, content: dict) -> None:
        pane = self._pane(agent)
        pane.append(f"[第0轮 计划] {content.get('summary', '')}")
        pane.extend(f"  - {s}" for s in content.get("steps", []))
        self._refresh()

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        pane = self._pane(agent)
        pane.append(f"[第{round_no}轮]")
        if content.get("concerns"):
            pane.append("concerns: " + "; ".join(content["concerns"]))
        pane.append("response: " + content.get("response", ""))
        if content.get("revised_steps"):
            pane.append("revised: " + "; ".join(content["revised_steps"]))
        self._refresh()

    def interjection(self, round_no: int, text: str) -> None:
        self.status_lines.append(f"你(第{round_no}轮后): {text}")
        self._refresh()

    def status(self, text: str) -> None:
        self.status_lines.append(text)
        self._refresh()

    def consensus(self, content: dict) -> None:
        self.status_lines.append("共识 / Consensus: " + content.get("summary", ""))
        self._refresh()

    def note(self, text: str) -> None:
        self.status_lines.append(text)
        self._refresh()

    # --- control + gates (pause Live around input) ---
    def _paused(self, fn):
        if self._live is not None:
            self._live.stop()
        try:
            return fn()
        finally:
            if self._live is not None:
                self._live.start()

    def control(self, state, round_no, *, printer=None):
        from macr.discussion_control import interactive_discussion_control

        return self._paused(lambda: interactive_discussion_control(state, round_no))

    def consensus_gate(self, state, *, printer=None):
        from macr.human_gate import consensus_human_gate

        return self._paused(lambda: consensus_human_gate(state))

    def final_gate(self, state, *, printer=None):
        from macr.human_gate import collab_human_gate

        return self._paused(lambda: collab_human_gate(state))
```

- [ ] **Step 4: Run, expect PASS** — `.venv/bin/pytest tests/test_discussion_view.py -v` (5 from Task 2 + 4 new = 9 passed).

- [ ] **Step 5: Commit**
```bash
git add macr/discussion_view.py tests/test_discussion_view.py
git commit -m "feat: add rich TwoPaneView with buffer fallback and live control"
```

---

### Task 4: Refactor `run_discuss` to use `view` instead of `printer`

**Files:** Modify `macr/discussion.py`; Modify `tests/test_discussion.py`.

- [ ] **Step 1: Update `tests/test_discussion.py`'s `_build` helper** — the `run_discuss` call currently passes `printer=lambda *_: None`. Change ONLY that argument to `view=SilentView()`, and add the import. At the top of the file add:
```python
from macr.discussion_view import FakeView, SilentView
```
and in `_build(...)`, replace `printer=lambda *_: None,` with `view=SilentView(),`. Then APPEND one new test asserting structured events:
```python
def test_view_receives_structured_events(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({"discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")]})
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    view = FakeView()
    actions = iter([ControlDecision("continue"), ControlDecision("end")])
    from macr.discussion import run_discuss
    run_discuss(
        "topic", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, max_revisions=2,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: next(actions),
        view=view, today="20260607",
    )
    kinds = [e[0] for e in view.events]
    # two plans, then a turn for each agent, then consensus appears
    assert kinds[:2] == ["plan", "plan"]
    assert ("plan", "claude", view.events[0][2]) == view.events[0]
    assert any(e[0] == "turn" for e in view.events)
    assert any(e[0] == "consensus" for e in view.events)
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discussion.py -v` (the `view=` kwarg doesn't exist yet → TypeError).

- [ ] **Step 3: Edit `macr/discussion.py`:**

(i) Update imports — add at the top (after the existing imports):
```python
from macr.discussion_view import ConsoleView, DiscussionView
```

(ii) DELETE the module-level `_print_plan` and `_print_turn` functions (they now live in `ConsoleView`).

(iii) In `run_discuss`, replace the `printer: Callable[..., None] = print,` parameter with:
```python
    view: DiscussionView | None = None,
```
and immediately after the signature (first line of the body) add:
```python
    view = view or ConsoleView()
```

(iv) Replace the display/printer calls inside `run_discuss` as follows:
- `_print_plan(printer, agent, msg.content)` → `view.plan(agent, msg.content)`
- `_print_turn(printer, agent, round_no, msg.content)` → `view.turn(agent, round_no, msg.content)`
- `decision = discussion_control(state, round_no, printer=printer)` → `decision = discussion_control(state, round_no, printer=view.note)`
- the interjection line `printer(f"\n━━━ 你(human)· 第 {round_no} 轮后插话 ━━━\n{decision.interjection}")` → `view.interjection(round_no, decision.interjection)`
- `printer(f"[discussion blocked] {exc}")` → `view.note(f"[discussion blocked] {exc}")`
- `printer(f"\n━━━ 共识 / Consensus ━━━\n{c.get('summary','')}")` → `view.consensus(c)`
- `printer(f"[consensus blocked] {exc}")` → `view.note(f"[consensus blocked] {exc}")`
- `fb1 = consensus_gate(state, printer=printer)` → `fb1 = consensus_gate(state, printer=view.note)`
- `printer(f"[human·consensus] {fb1.decision}")` → `view.note(f"[human·consensus] {fb1.decision}")`
- `_implementation_loop(..., printer=printer)` → `_implementation_loop(..., printer=view.status)`
- `fb2 = human_gate(state, printer=printer)` → `fb2 = human_gate(state, printer=view.note)`
- `printer(f"[human·final] {fb2.decision}")` → `view.note(f"[human·final] {fb2.decision}")`

(Leave all non-display logic — records, file writes, gates' decisions, worktree cleanup — exactly as is.)

- [ ] **Step 4: Run, expect PASS** — `.venv/bin/pytest tests/test_discussion.py -v` (the prior 7 tests, now using `view=SilentView()`, plus the new event test → 8 passed).

- [ ] **Step 5: Commit**
```bash
git add macr/discussion.py tests/test_discussion.py
git commit -m "refactor: drive run_discuss display through DiscussionView"
```

---

### Task 5: CLI `--tui` wiring + `view` injectable

**Files:** Modify `macr/cli.py`; Modify `tests/test_cli_discuss.py`.

- [ ] **Step 1: Append failing tests to `tests/test_cli_discuss.py`** (reuse the file's existing `_init_repo`, `_claude`, `_codex_discuss`, `_codex_impl` helpers and imports):
```python
from macr.discussion_view import FakeView


def test_discuss_tui_flag_falls_back_non_tty(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    # non-tty environment (pytest) -> TwoPaneView disabled, falls back; flow still works
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1", "--tui"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0


def test_discuss_accepts_injected_view(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    view = FakeView()
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        view=view,
    )
    assert rc == 0
    assert any(e[0] == "plan" for e in view.events)
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_discuss.py -k "tui or injected_view" -v` (`--tui` unknown / `view=` kwarg unknown).

- [ ] **Step 3: Modify `macr/cli.py`:**

(i) Add `--tui` to the `discuss` subparser in `_parse_args` (after `--no-subagents`):
```python
    discuss_p.add_argument("--tui", action="store_true", help="rich two-pane live view (needs a real terminal)")
```

(ii) Replace the `_discuss_command` signature and the run block to accept/build a `view` and wire control/gates. Replace the whole `_discuss_command` function with:
```python
def _discuss_command(args, *, claude_backend, codex_backend, impl_codex_backend,
                     discussion_control, consensus_gate, human_gate, view) -> int:
    from macr.discussion import run_discuss
    from macr.discussion_control import auto_discussion_control, interactive_discussion_control
    from macr.discussion_view import ConsoleView, TwoPaneView

    if claude_backend is None or codex_backend is None or impl_codex_backend is None:
        missing = [b for b in ("claude", "codex") if shutil.which(b) is None]
        if missing:
            print(f"error: required CLI not found on PATH: {', '.join(missing)}", file=sys.stderr)
            return 2
        from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend

        enable = not getattr(args, "no_subagents", False)
        if claude_backend is None:
            claude_backend = ClaudeCliBackend(model=args.claude_model, timeout=args.timeout, enable_subagents=enable)
        if codex_backend is None:
            codex_backend = CodexCliBackend(model=args.codex_model, timeout=args.timeout,
                                            enable_subagents=enable, sandbox="read-only")
        if impl_codex_backend is None:
            impl_codex_backend = CodexCliBackend(model=args.codex_model, timeout=args.timeout,
                                                 enable_subagents=enable, sandbox="workspace-write")

    # choose a view
    if view is None:
        if getattr(args, "tui", False) and sys.stdout.isatty():
            view = TwoPaneView(topic=args.task)
        else:
            view = ConsoleView()

    # if the view is an enabled TwoPaneView, let it own control/gates (it pauses Live for input)
    tui_active = isinstance(view, TwoPaneView) and view.enabled
    if discussion_control is None:
        discussion_control = view.control if tui_active else (
            auto_discussion_control if getattr(args, "auto", False) else interactive_discussion_control)
    if consensus_gate is None:
        from macr.human_gate import consensus_human_gate
        consensus_gate = view.consensus_gate if tui_active else consensus_human_gate
    if human_gate is None:
        human_gate = view.final_gate if tui_active else collab_human_gate

    try:
        with view:
            state = run_discuss(
                args.task,
                repo=Path(args.repo).resolve(),
                test_cmd=shlex.split(args.test_cmd),
                claude_backend=claude_backend, codex_backend=codex_backend, impl_codex_backend=impl_codex_backend,
                runs_dir=Path(".macr/runs").resolve(), worktrees_dir=Path(".macr/worktrees").resolve(),
                max_rounds=args.max_rounds, max_revisions=args.max_revisions,
                discussion_control=discussion_control, consensus_gate=consensus_gate, human_gate=human_gate,
                view=view, timeout=args.timeout,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1
```

(iii) Update `main` to accept and pass `view`, and to pass through `None` defaults so `_discuss_command` resolves them (do NOT pre-fill `consensus_gate`/`human_gate` with defaults for the discuss path — let `_discuss_command` decide TUI-vs-console). Replace the `discuss` branch and signature of `main`:
```python
def main(argv: list[str] | None = None, *, llm=None,
         claude_backend=None, codex_backend=None, impl_codex_backend=None,
         human_gate=None, discussion_control=None, consensus_gate=None, view=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "collab":
        gate = human_gate or collab_human_gate
        return _collab_command(args, claude_backend=claude_backend, codex_backend=codex_backend, human_gate=gate)
    if args.command == "discuss":
        return _discuss_command(
            args, claude_backend=claude_backend, codex_backend=codex_backend,
            impl_codex_backend=impl_codex_backend,
            discussion_control=discussion_control, consensus_gate=consensus_gate,
            human_gate=human_gate, view=view)
    gate = human_gate or interactive_human_gate
    return _run_command(args, llm=llm, human_gate=gate)
```
Note: `collab_human_gate` is already imported at the top of cli.py. The `_discuss_command` imports `consensus_human_gate` locally where needed.

- [ ] **Step 4: Run new + ALL regressions + FULL suite:**
- `.venv/bin/pytest tests/test_cli_discuss.py -v` (existing 2 + 2 new = 4 passed)
- `.venv/bin/pytest tests/test_cli.py tests/test_cli_collab.py tests/test_cli_subagents.py -v` (green)
- `.venv/bin/pytest -q` (FULL suite green)
Fix any regression before committing.

- [ ] **Step 5: Commit**
```bash
git add macr/cli.py tests/test_cli_discuss.py
git commit -m "feat: add --tui two-pane view to macr discuss and view injection"
```

---

### Task 6: README

**Files:** Modify `README.md` (append only).

- [ ] **Step 1: Append to the END of `README.md`** (keep all existing content):
```markdown

#### 双栏实况视图 (Stage C2) / Two-pane live view

给 `macr discuss` 加 `--tui`,用 `rich` 左右两栏(Claude / Codex)+ 底部状态/人声面板实时围观讨论;需真终端,非终端自动回退到逐轮单栏(C1 行为)。

```bash
.venv/bin/macr discuss "为模块加 hello() 函数" --repo /path/to/repo --test-cmd "pytest -q" --tui
```

每轮边界仍是 `[c]继续 / [i]插话 / [e]定稿 / [a]中止`(rich 会短暂让位给输入);不加 `--tui` 时行为与 C1 完全一致。
```

- [ ] **Step 2: Full suite green** — `.venv/bin/pytest -q`.

- [ ] **Step 3: Commit**
```bash
git add README.md
git commit -m "docs: document the --tui two-pane discuss view"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §3 `DiscussionView` + ConsoleView/SilentView/FakeView → Task 2; TwoPaneView → Task 3.
- §4 layout (header/two panes/bottom status), buffers, control/gate-pause-Live, non-tty fallback → Task 3.
- §5 `run_discuss` printer→view refactor, `_implementation_loop` unchanged (gets `printer=view.status`) → Task 4.
- §6 CLI `--tui`, view selection (TwoPaneView if --tui & tty else ConsoleView), TUI binds control/gates to view, `with view:` lifecycle, `view` injectable → Task 5.
- §7 tests: views (Task 2/3), orchestrator via FakeView/SilentView (Task 4), CLI --tui fallback + injected view (Task 5); regressions re-run each task. §2 rich dependency → Task 1.
- §8 non-tty/Live-exception safety → Task 3 (`_paused`, `__exit__` always stops Live; `with view` in cli).

**Placeholder scan:** No TBD/TODO. One cosmetic noqa-guarded dead line (`consensus_human_gate_unused`) is unnecessary — the implementer should simply import `consensus_human_gate` locally before its use in the `consensus_gate is None` branch (as written) and may delete the stray `consensus_human_gate_unused` line; it is harmless either way. (Correctness note: the `from macr.human_gate import consensus_human_gate` sits inside the `if consensus_gate is None:` block, so it is in scope there.)

**Type/name consistency:** `DiscussionView` methods `plan/turn/interjection/status/consensus/note` identical across ConsoleView/SilentView/FakeView/TwoPaneView (Tasks 2/3) and all call sites in `run_discuss` (Task 4). `run_discuss(..., view=...)` replaces `printer` consistently (Task 4) and is passed by cli (Task 5) and tests. `TwoPaneView(enabled=, topic=, console=)` ctor + `.control/.consensus_gate/.final_gate` + `.enabled` + `._render`/`._live` used consistently (Task 3 ↔ Task 5). `view.status` is the printer adapter into `_implementation_loop` (unchanged signature). `cli.main(..., view=None)` threaded to `_discuss_command(..., view=view)` (Task 5). ConsoleView default keeps C1's exact strings (Task 2) so console-mode behavior is unchanged.
```
