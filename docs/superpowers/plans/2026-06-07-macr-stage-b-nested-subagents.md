# MACR Stage B — Native Nested Subagents + Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `macr collab` allow Claude and Codex to use their native subagents during a run, and capture that nested activity (raw event stream + structured summary) into `.macr/runs/<run_id>/subagents/`, with a `--no-subagents` opt-out.

**Architecture:** Switch the two CLI backends to streaming output (`claude -p --output-format stream-json`, `codex exec --json`), enable each CLI's native subagent tools, and parse the event stream defensively to recover the role's final structured result + a subagent summary. A new `agents/trace.py` (pure parsers + `TraceSink`) handles capture. `run_role` gains an optional `trace` param (old backends ignore it). The orchestrator wires a per-(role,attempt) `TraceSink` and aggregates `state.subagents`.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `subprocess`/`json`, pytest. **Isolation rule:** project-local `.venv` only (`.venv/bin/...`). Commits: plain, NO Co-Authored-By / AI attribution. One git command at a time.

**Spec:** `docs/superpowers/specs/2026-06-07-macr-stage-b-nested-subagents-design.md` (note especially §7 — event schemas are best-effort/defensive, calibrated against real CLI output in a later manual smoke; do NOT run real `claude`/`codex` here).

**Current interfaces (verified, do not break):**
- `macr/agents/base.py`: `ProcResult`, `ProcessRunner`, `SubprocessRunner`, `AgentBackend` (Protocol), `extract_json_object`, `validate_with_retry`, `message_from_content`, `FakeProcessRunner`, `FakeAgentBackend`. `validate_with_retry` currently catches only `ValidationError`.
- `macr/agents/cli_backend.py`: `ClaudeCliBackend` (uses `--output-format json`), `CodexCliBackend` (parses stdout), `_base_prompt`, `_schema_instruction`.
- `macr/collab_orchestrator.py`: `run_collab(...)`, `_build_final`.
- `macr/cli.py`: `_collab_command`, `main`.
- `macr/schemas.py`: `SharedState` (has collab fields), `TestResult` (has `__test__ = False`).

**Conventions:** TDD per task (red → green → commit). Run all tests via `.venv/bin/pytest`.

---

### Task 1: `schemas.py` — `SubagentRecord` + `SharedState.subagents`

**Files:** Modify `macr/schemas.py`; Create `tests/test_schemas_subagents.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_schemas_subagents.py`:
```python
from macr.schemas import SharedState, SubagentRecord


def test_subagent_record_defaults():
    r = SubagentRecord(source="claude", ref="toolu_1")
    assert r.agent_type == "unknown"
    assert r.source == "claude"
    assert r.ref == "toolu_1"


def test_shared_state_subagents_default_and_roundtrip():
    s = SharedState(run_id="R1", user_query="q")
    assert s.subagents == []
    s.subagents.append({"role": "planner", "attempt": 1, "count": 2, "types": ["Explore"]})
    assert s.model_dump()["subagents"][0]["count"] == 2
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_schemas_subagents.py -v`.

- [ ] **Step 3: Implement** — in `macr/schemas.py`, add the `SubagentRecord` model (place it after `TestResult`):
```python
class SubagentRecord(BaseModel):
    source: Literal["claude", "codex"]
    agent_type: str = "unknown"
    ref: str = ""
```
and add one field to `SharedState` (after the existing `test_results` field, keep all others unchanged):
```python
    subagents: list[dict] = Field(default_factory=list)
```
(`Literal` is already imported in schemas.py; if not, add `from typing import Literal`.)

- [ ] **Step 4: Run, expect PASS, and confirm V1/Stage A schema tests still pass** — `.venv/bin/pytest tests/test_schemas_subagents.py tests/test_schemas.py tests/test_schemas_collab.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/schemas.py tests/test_schemas_subagents.py
git commit -m "feat: add SubagentRecord schema and SharedState.subagents field"
```

---

### Task 2: `agents/trace.py` — defensive stream parsers + TraceSink

**Files:** Create `macr/agents/trace.py`, `tests/test_trace.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_trace.py`:
```python
import json

from macr.agents.trace import TraceSink, parse_claude_stream, parse_codex_stream
from macr.schemas import SubagentRecord


def test_parse_claude_stream_extracts_result_and_subagent():
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_sub1", "name": "Agent",
             "input": {"subagent_type": "Explore", "prompt": "look"}}]},
            "parent_tool_use_id": None}),
        json.dumps({"type": "stream_event", "event": {"type": "x"}, "parent_tool_use_id": "toolu_sub1"}),
        json.dumps({"type": "result", "result": '{"summary":"p","steps":["a"]}', "session_id": "s1"}),
    ]
    final_text, subs = parse_claude_stream(lines)
    assert json.loads(final_text)["steps"] == ["a"]
    assert len(subs) == 1
    assert subs[0].source == "claude" and subs[0].agent_type == "Explore" and subs[0].ref == "toolu_sub1"


def test_parse_claude_stream_tolerates_garbage_and_missing_result():
    final_text, subs = parse_claude_stream(["not json", json.dumps({"type": "assistant"})])
    assert final_text == ""
    assert subs == []


def test_parse_codex_stream_extracts_message_and_subthread():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "root"}),
        json.dumps({"type": "thread.started", "thread_id": "sub-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                                                       "text": '{"artifact":"x","notes":"","evidence":[]}'}}),
        json.dumps({"type": "turn.completed"}),
    ]
    final_text, subs = parse_codex_stream(lines)
    assert json.loads(final_text)["artifact"] == "x"
    assert len(subs) == 1
    assert subs[0].source == "codex" and subs[0].ref == "sub-1"


def test_parse_codex_stream_tolerates_garbage():
    final_text, subs = parse_codex_stream(["", "{bad", json.dumps({"type": "turn.completed"})])
    assert final_text == "" and subs == []


def test_trace_sink_capture_writes_two_files(tmp_path):
    sink = TraceSink(tmp_path / "subagents", "planner.v1")
    sink.capture(['{"a":1}', '{"b":2}'],
                 [SubagentRecord(source="claude", agent_type="Explore", ref="r1")])
    events = (tmp_path / "subagents" / "planner.v1.events.jsonl").read_text()
    assert '{"a":1}' in events and '{"b":2}' in events
    summary = json.loads((tmp_path / "subagents" / "planner.v1.subagents.json").read_text())
    assert summary[0]["agent_type"] == "Explore"
    assert sink.records[0].ref == "r1"
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_trace.py -v`.

- [ ] **Step 3: Implement** — `macr/agents/trace.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from macr.schemas import SubagentRecord


def _iter_json_lines(lines: list[str]) -> Iterator[dict]:
    """Parse each line as JSON; silently skip anything that isn't a JSON object."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _walk(obj) -> Iterator[dict]:
    """Yield every dict nested anywhere inside obj."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_claude_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]:
    """Best-effort: recover the final result text + subagent records from claude stream-json.

    Defensive against unknown/missing fields (spec §7). Never raises.
    """
    objs = list(_iter_json_lines(lines))

    final_text = ""
    for o in objs:
        result = o.get("result")
        if isinstance(result, str):
            final_text = result  # last one wins (the terminal result event)

    type_by_id: dict[str, str] = {}
    for o in objs:
        for d in _walk(o):
            if d.get("type") == "tool_use" and d.get("name") in ("Agent", "Task"):
                tid = d.get("id")
                if tid:
                    subtype = (d.get("input") or {}).get("subagent_type")
                    type_by_id[tid] = subtype or "unknown"

    refs: list[str] = []
    seen: set[str] = set()
    for o in objs:
        parent = o.get("parent_tool_use_id")
        if parent and parent not in seen:
            seen.add(parent)
            refs.append(parent)

    records = [
        SubagentRecord(source="claude", agent_type=type_by_id.get(ref, "unknown"), ref=ref)
        for ref in refs
    ]
    return final_text, records


def parse_codex_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]:
    """Best-effort: recover the final agent message + spawned sub-thread records from codex --json.

    Defensive against unknown/missing fields (spec §7). Never raises.
    """
    objs = list(_iter_json_lines(lines))

    threads: list[str] = []
    for o in objs:
        if o.get("type") == "thread.started":
            tid = o.get("thread_id") or (o.get("thread") or {}).get("id")
            if tid:
                threads.append(tid)

    final_text = ""
    for o in objs:
        if o.get("type") == "item.completed":
            item = o.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"]  # last agent message wins

    sub_ids = threads[1:] if len(threads) > 1 else []  # first thread is the root session
    records = [SubagentRecord(source="codex", agent_type="unknown", ref=t) for t in sub_ids]
    return final_text, records


class TraceSink:
    """Persists one role-invocation's raw event stream + parsed subagent summary."""

    def __init__(self, directory: Path, label: str):
        self.directory = Path(directory)
        self.label = label
        self.records: list[SubagentRecord] = []

    def capture(self, raw_lines: list[str], subagents: list[SubagentRecord]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{self.label}.events.jsonl").write_text(
            "\n".join(raw_lines), encoding="utf-8"
        )
        (self.directory / f"{self.label}.subagents.json").write_text(
            json.dumps([s.model_dump() for s in subagents], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.records = list(subagents)
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_trace.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/agents/trace.py tests/test_trace.py
git commit -m "feat: add defensive subagent stream parsers and TraceSink"
```

---

### Task 3: `agents/base.py` + `api_backend.py` — optional `trace` param; retry on parse failure

**Files:** Modify `macr/agents/base.py`, `macr/agents/api_backend.py`; Create `tests/test_base_trace.py`.

This makes `run_role` accept an optional `trace` (the Protocol + the two test/dormant backends), and makes `validate_with_retry` also retry on a parse failure (`ValueError` from `extract_json_object`) so "no final result → retry → BLOCKED" (spec §7) works.

- [ ] **Step 1: Write the failing test** — `tests/test_base_trace.py`:
```python
import pytest

from macr.agent import AgentError
from macr.agents.base import FakeAgentBackend, validate_with_retry
from macr.agents.trace import TraceSink
from macr.roles import PLANNER
from macr.schemas import SharedState, SubagentRecord


def test_validate_with_retry_retries_on_parse_valueerror_then_raises():
    def call_fn(extra):
        raise ValueError("no JSON object found")

    with pytest.raises(AgentError):
        validate_with_retry(PLANNER, call_fn)


def test_fake_agent_backend_accepts_and_ignores_trace_without_script(tmp_path):
    fab = FakeAgentBackend({"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]})
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="q")
    msg = fab.run_role(PLANNER, state, run_id="R1", task_id="R1", trace=sink)
    assert msg.content["steps"] == ["a"]
    assert sink.records == []  # no scripted subagents -> nothing captured


def test_fake_agent_backend_captures_scripted_subagents(tmp_path):
    fab = FakeAgentBackend(
        {"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]},
        subagents={"planner": [SubagentRecord(source="claude", agent_type="Explore", ref="r1")]},
    )
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="q")
    fab.run_role(PLANNER, state, run_id="R1", task_id="R1", trace=sink)
    assert len(sink.records) == 1 and sink.records[0].agent_type == "Explore"
    assert (tmp_path / "planner.v1.subagents.json").exists()
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_base_trace.py -v`.

- [ ] **Step 3a: Update `macr/agents/base.py`:**

(i) Make `validate_with_retry` also catch `ValueError` (replace the function body's two `except ValidationError` clauses):
```python
def validate_with_retry(role: RoleSpec, call_fn: Callable[[str], dict]) -> BaseModel:
    """call_fn(extra_note) -> raw dict. Validate into role.content_model with one retry.

    Retries once on schema validation failure (ValidationError) or output-parse
    failure (ValueError from extract_json_object); a second failure -> AgentError.
    """
    raw = call_fn("")
    try:
        return role.content_model(**raw)
    except (ValidationError, ValueError) as first:
        note = (
            "\n\nPrevious output failed validation:\n"
            f"{first}\nReturn corrected JSON only, matching the schema."
        )
        raw = call_fn(note)
        try:
            return role.content_model(**raw)
        except (ValidationError, ValueError) as second:
            raise AgentError(f"{role.name} failed schema validation twice: {second}") from second
```
Note: when `call_fn` itself raises `ValueError` (e.g. a parse failure inside it), `raw = call_fn("")` raises before the inner `try`. To retry that too, wrap the first call:
```python
def validate_with_retry(role: RoleSpec, call_fn: Callable[[str], dict]) -> BaseModel:
    try:
        raw = call_fn("")
        return role.content_model(**raw)
    except (ValidationError, ValueError) as first:
        note = (
            "\n\nPrevious output failed validation:\n"
            f"{first}\nReturn corrected JSON only, matching the schema."
        )
        try:
            raw = call_fn(note)
            return role.content_model(**raw)
        except (ValidationError, ValueError) as second:
            raise AgentError(f"{role.name} failed schema validation twice: {second}") from second
```
Use this second form (it retries when `call_fn` raises `ValueError` directly).

(ii) Add `trace` to the `AgentBackend` Protocol signature:
```python
@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None,
                 trace: "TraceSink | None" = None) -> Message: ...
```
Add this import near the top (after the existing imports), guarded to avoid a circular import at module load (trace.py imports from schemas only, base imports trace only for typing):
```python
from macr.agents.trace import TraceSink  # noqa: E402  (used in type hints + FakeAgentBackend)
```
Place this import at the END of base.py's import block. (trace.py does NOT import base.py, so there is no cycle.)

(iii) Update `FakeAgentBackend` to accept `subagents` and `trace`:
```python
class FakeAgentBackend:
    """AgentBackend test double: scripted content per role name; optional on_run side effect.

    Optionally captures scripted SubagentRecords into a provided trace sink.
    """

    name = "fake"

    def __init__(self, scripted: dict[str, list[dict]],
                 on_run: Callable[[RoleSpec, SharedState], None] | None = None,
                 subagents: dict[str, list] | None = None):
        self._scripted = {k: list(v) for k, v in scripted.items()}
        self._on_run = on_run
        self._subagents = subagents or {}
        self.calls: list[str] = []

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None) -> Message:
        self.calls.append(role.name)
        if self._on_run is not None:
            self._on_run(role, state)
        if not self._scripted.get(role.name):
            raise AssertionError(f"FakeAgentBackend has no scripted output for role '{role.name}'")
        content = self._scripted[role.name].pop(0)
        if trace is not None and self._subagents.get(role.name):
            trace.capture(["{}"], list(self._subagents[role.name]))
        return Message(
            task_id=task_id, run_id=run_id, agent_id=role.agent_id, role=role.name,
            message_type=role.message_type, content=content, timestamp=timestamp or "t",
        )
```

- [ ] **Step 3b: Update `macr/agents/api_backend.py`** — add `trace=None` to the signature (ignored):
```python
    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None,
                 trace=None) -> Message:
        return run_agent(role, state, self._llm, task_id=task_id, run_id=run_id, timestamp=timestamp)
```

- [ ] **Step 4: Run new tests + regressions** — `.venv/bin/pytest tests/test_base_trace.py tests/test_agents_base.py tests/test_api_backend.py -v` (new pass + Stage A base/api still green).

- [ ] **Step 5: Commit**
```bash
git add macr/agents/base.py macr/agents/api_backend.py tests/test_base_trace.py
git commit -m "feat: add optional trace param to backends and retry on parse failure"
```

---

### Task 4: `agents/cli_backend.py` — streaming + native subagents + capture

**Files:** Modify `macr/agents/cli_backend.py`; rewrite `tests/test_cli_backend.py`.

Switches Claude to `stream-json` (+ `--allowedTools` incl. `Agent`, worktree as cwd) and Codex to `--json`, parses via `trace.py`, captures into the optional `trace`, and adds `enable_subagents`.

- [ ] **Step 1: Rewrite `tests/test_cli_backend.py`** (Stage A's version asserted the old `--output-format json`; replace the whole file):
```python
import json

import pytest

from macr.agent import AgentError
from macr.agents.base import ProcResult, FakeProcessRunner
from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
from macr.agents.trace import TraceSink
from macr.collab_roles import EXECUTOR_C, PLANNER_C
from macr.schemas import SharedState


def _claude_stream(inner: dict, *, with_sub: bool = False) -> str:
    lines = []
    if with_sub:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_s1", "name": "Agent",
             "input": {"subagent_type": "Explore"}}]}, "parent_tool_use_id": None}))
        lines.append(json.dumps({"type": "stream_event", "event": {}, "parent_tool_use_id": "toolu_s1"}))
    lines.append(json.dumps({"type": "result", "result": json.dumps(inner), "session_id": "s1"}))
    return "\n".join(lines)


def _codex_stream(inner: dict, *, with_sub: bool = False) -> str:
    lines = [json.dumps({"type": "thread.started", "thread_id": "root"})]
    if with_sub:
        lines.append(json.dumps({"type": "thread.started", "thread_id": "sub-1"}))
    lines.append(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(inner)}}))
    lines.append(json.dumps({"type": "turn.completed"}))
    return "\n".join(lines)


def _plan():
    return {"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}


def test_claude_streaming_parses_and_argv_has_agent_and_cwd():
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner, model="claude-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    call = runner.calls[0]
    argv = call["argv"]
    assert argv[0] == "claude" and "--output-format" in argv and "stream-json" in argv
    assert "--allowedTools" in argv
    tools = argv[argv.index("--allowedTools") + 1]
    assert "Agent" in tools
    assert call["cwd"] == "/tmp/wt"


def test_claude_no_subagents_drops_agent_tool():
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan()), "")])
    backend = ClaudeCliBackend(runner=runner, enable_subagents=False)
    state = SharedState(run_id="R1", user_query="task")
    backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    tools = runner.calls[0]["argv"][runner.calls[0]["argv"].index("--allowedTools") + 1]
    assert "Agent" not in tools


def test_claude_captures_trace(tmp_path):
    runner = FakeProcessRunner([ProcResult(0, _claude_stream(_plan(), with_sub=True), "")])
    backend = ClaudeCliBackend(runner=runner)
    sink = TraceSink(tmp_path, "planner.v1")
    state = SharedState(run_id="R1", user_query="task")
    backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t", trace=sink)
    assert (tmp_path / "planner.v1.events.jsonl").exists()
    assert len(sink.records) == 1 and sink.records[0].agent_type == "Explore"


def test_claude_nonzero_exit_raises():
    runner = FakeProcessRunner([ProcResult(1, "", "boom"), ProcResult(1, "", "boom")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_claude_empty_result_retries_then_raises():
    # stream with no result event -> final_text empty -> ValueError -> retry -> AgentError
    empty = json.dumps({"type": "turn.completed"})
    runner = FakeProcessRunner([ProcResult(0, empty, ""), ProcResult(0, empty, "")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_codex_streaming_parses_and_argv():
    inner = {"artifact": "edited", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner), "")])
    backend = CodexCliBackend(runner=runner, model="gpt-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["artifact"] == "edited"
    argv = runner.calls[0]["argv"]
    assert argv[0] == "codex" and argv[1] == "exec"
    assert "--json" in argv and "--cd" in argv and "/tmp/wt" in argv
    assert "--sandbox" in argv and "--ask-for-approval" in argv


def test_codex_no_subagents_disables_multi_agent():
    inner = {"artifact": "x", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner), "")])
    backend = CodexCliBackend(runner=runner, enable_subagents=False)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    argv = runner.calls[0]["argv"]
    assert "features.multi_agent=false" in argv


def test_codex_captures_trace(tmp_path):
    inner = {"artifact": "x", "notes": "", "evidence": []}
    runner = FakeProcessRunner([ProcResult(0, _codex_stream(inner, with_sub=True), "")])
    backend = CodexCliBackend(runner=runner)
    sink = TraceSink(tmp_path, "executor.v1")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t", trace=sink)
    assert (tmp_path / "executor.v1.subagents.json").exists()
    assert len(sink.records) == 1 and sink.records[0].ref == "sub-1"
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_backend.py -v`.

- [ ] **Step 3: Rewrite `macr/agents/cli_backend.py`:**
```python
from __future__ import annotations

import json

from macr.agent import AgentError
from macr.agents.base import (
    ProcessRunner,
    SubprocessRunner,
    extract_json_object,
    message_from_content,
    validate_with_retry,
)
from macr.agents.trace import TraceSink, parse_claude_stream, parse_codex_stream
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState


def _schema_instruction(role: RoleSpec) -> str:
    schema = role.content_model.model_json_schema()
    return (
        "\n\n只输出一个符合以下 JSON Schema 的 JSON 对象,不要任何解释或额外文本:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _base_prompt(role: RoleSpec, state: SharedState) -> str:
    return f"{role.system_prompt}\n\n{role.build_user(state)}{_schema_instruction(role)}"


class ClaudeCliBackend:
    """Drives the `claude` CLI headless, with streaming output and native subagents."""

    name = "claude_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 claude_bin: str = "claude", timeout: int = 1800, enable_subagents: bool = True):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.claude_bin = claude_bin
        self.timeout = timeout
        self.enable_subagents = enable_subagents

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace: TraceSink | None = None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path
        captured: dict = {"lines": [], "subs": []}

        def call_fn(extra: str) -> dict:
            tools = "Read,Grep,Glob,Agent" if self.enable_subagents else "Read,Grep,Glob"
            argv = [self.claude_bin, "-p", prompt + extra,
                    "--output-format", "stream-json", "--verbose",
                    "--include-partial-messages", "--allowedTools", tools]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, cwd=cwd, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"claude CLI exited {res.returncode}: {res.stderr.strip()}")
            lines = res.stdout.splitlines()
            final_text, subs = parse_claude_stream(lines)
            captured["lines"], captured["subs"] = lines, subs
            return extract_json_object(final_text)

        content = validate_with_retry(role, call_fn)
        if trace is not None:
            trace.capture(captured["lines"], captured["subs"])
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)


class CodexCliBackend:
    """Drives the `codex` CLI in non-interactive exec mode with JSON streaming + subagents."""

    name = "codex_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 approval: str = "never", timeout: int = 1800, enable_subagents: bool = True):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.approval = approval
        self.timeout = timeout
        self.enable_subagents = enable_subagents

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace: TraceSink | None = None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."
        captured: dict = {"lines": [], "subs": []}

        def call_fn(extra: str) -> dict:
            argv = [self.codex_bin, "exec", prompt + extra,
                    "--cd", cwd, "--sandbox", self.sandbox,
                    "--ask-for-approval", self.approval, "--json"]
            if not self.enable_subagents:
                argv += ["-c", "features.multi_agent=false"]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"codex CLI exited {res.returncode}: {res.stderr.strip()}")
            lines = res.stdout.splitlines()
            final_text, subs = parse_codex_stream(lines)
            captured["lines"], captured["subs"] = lines, subs
            return extract_json_object(final_text)

        content = validate_with_retry(role, call_fn)
        if trace is not None:
            trace.capture(captured["lines"], captured["subs"])
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
```

- [ ] **Step 4: Run, expect PASS (8 passed)** — `.venv/bin/pytest tests/test_cli_backend.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/agents/cli_backend.py tests/test_cli_backend.py
git commit -m "feat: stream CLI output, enable native subagents, capture into trace"
```

---

### Task 5: `collab_orchestrator.py` — wire trace + aggregate `state.subagents`

**Files:** Modify `macr/collab_orchestrator.py`; Create `tests/test_collab_orchestrator_subagents.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_collab_orchestrator_subagents.py`:
```python
import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.collab_orchestrator import run_collab
from macr.schemas import HumanFeedback, SubagentRecord


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path) / "a.txt").write_text("changed\n")


def test_subagents_captured_and_aggregated(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend(
        {"planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
         "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]},
        subagents={"planner": [SubagentRecord(source="claude", agent_type="Explore", ref="r1")]},
    )
    codex = FakeAgentBackend(
        {"executor": [{"artifact": "x", "notes": "", "evidence": []}]},
        on_run=_editor,
        subagents={"executor": [SubagentRecord(source="codex", agent_type="unknown", ref="t1")]},
    )
    state = run_collab(
        "task", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_revisions=2, human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        printer=lambda *_: None, today="20260607",
    )
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "subagents" / "planner.v1.subagents.json").exists()
    assert (run_path / "subagents" / "executor.v1.subagents.json").exists()
    # state.subagents aggregated per role/attempt
    by_role = {s["role"]: s for s in state.subagents}
    assert by_role["planner"]["count"] == 1 and by_role["planner"]["types"] == ["Explore"]
    assert by_role["executor"]["count"] == 1
    assert "subagent" in (run_path / "final.md").read_text().lower()
    saved = json.loads((run_path / "state.json").read_text())
    assert any(s["role"] == "planner" for s in saved["subagents"])
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_collab_orchestrator_subagents.py -v`.

- [ ] **Step 3: Modify `macr/collab_orchestrator.py`:**

(i) Add the import (after the existing `from macr.agents.base import AgentBackend`):
```python
from macr.agents.trace import TraceSink
```

(ii) Add a helper near `_build_final` and extend `_build_final` to include a subagent overview. Add this function above `_build_final`:
```python
def _record_subagents(state: SharedState, sink: TraceSink, role: str, attempt: int) -> None:
    types = sorted({r.agent_type for r in sink.records})
    state.subagents.append(
        {"role": role, "attempt": attempt, "count": len(sink.records), "types": types}
    )
```
and append a subagent section inside `_build_final` (add before the `hf = state.human_feedback` line):
```python
    if state.subagents:
        overview = "\n".join(
            f"- {s['role']} v{s['attempt']}: {s['count']} subagent(s) {s['types']}"
            for s in state.subagents
        )
        parts.append(f"\n## 嵌套 subagent 概览 / Nested subagents\n{overview}")
```

(iii) In `run_collab`, create a sink per role-invocation and pass it, then record. Replace the three `run_role` call sites:

Planner (replace the planner call + its bookkeeping):
```python
            planner_sink = TraceSink(run_path / "subagents", "planner.v1")
            planner_msg = claude_backend.run_role(
                PLANNER_C, state, run_id=run_id, task_id=run_id, trace=planner_sink)
            state.agent_outputs["planner"].append(planner_msg.content)
            state.task_plan = list(planner_msg.content.get("steps", []))
            log.write_planner(planner_msg.content)
            _record_subagents(state, planner_sink, "planner", 1)
            printer(f"[planner] {planner_msg.content.get('summary', '')}")
```

Executor (inside the loop, replace the executor call):
```python
                exec_sink = TraceSink(run_path / "subagents", f"executor.v{attempt}")
                exec_msg = codex_backend.run_role(
                    EXECUTOR_C, state, run_id=run_id, task_id=run_id, trace=exec_sink)
                state.agent_outputs["executor"].append(exec_msg.content)
                log.write_executor(exec_msg.content, attempt)
                _record_subagents(state, exec_sink, "executor", attempt)
```

Reviewer (inside the loop, replace the reviewer call):
```python
                review_sink = TraceSink(run_path / "subagents", f"reviewer.v{attempt}")
                review_msg = claude_backend.run_role(
                    REVIEWER_C, state, run_id=run_id, task_id=run_id, trace=review_sink)
                state.agent_outputs["reviewer"].append(review_msg.content)
                state.reviews.append(review_msg.content)
                log.write_reviewer(review_msg.content)
                _record_subagents(state, review_sink, "reviewer", attempt)
                printer(f"[reviewer] {review_msg.content.get('decision', '')}")
```

- [ ] **Step 4: Run new test + Stage A orchestrator regression** — `.venv/bin/pytest tests/test_collab_orchestrator_subagents.py tests/test_collab_orchestrator.py -v` (new pass; Stage A's 6 orchestrator tests still pass — they use FakeAgentBackend without `subagents`, so each records count 0, which doesn't affect their assertions).

- [ ] **Step 5: Commit**
```bash
git add macr/collab_orchestrator.py tests/test_collab_orchestrator_subagents.py
git commit -m "feat: wire subagent tracing into collab orchestrator and final summary"
```

---

### Task 6: `cli.py` — `--no-subagents` flag

**Files:** Modify `macr/cli.py`; Create `tests/test_cli_subagents.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_cli_subagents.py`:
```python
import subprocess
from pathlib import Path

from macr import cli
from macr.agents.base import FakeAgentBackend
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _claude():
    return FakeAgentBackend({
        "planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })


def _codex():
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")
    return FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=on_run)


def test_collab_accepts_no_subagents_flag(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true", "--no-subagents"],
        claude_backend=_claude(), codex_backend=_codex(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0


def test_build_real_backends_respects_no_subagents(monkeypatch):
    # When backends are NOT injected, the flag must flow into ClaudeCliBackend(enable_subagents=...)
    captured = {}

    class _FakeClaude:
        def __init__(self, *, model=None, timeout=1800, enable_subagents=True):
            captured["claude"] = enable_subagents

    class _FakeCodex:
        def __init__(self, *, model=None, timeout=1800, enable_subagents=True):
            captured["codex"] = enable_subagents

    import macr.agents.cli_backend as clib
    monkeypatch.setattr(clib, "ClaudeCliBackend", _FakeClaude)
    monkeypatch.setattr(clib, "CodexCliBackend", _FakeCodex)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)

    # run_collab will fail fast (fake backends have no run_role); we only assert construction flags
    import argparse
    args = argparse.Namespace(task="t", repo=".", test_cmd="true", max_revisions=2,
                              claude_model=None, codex_model=None, timeout=1800, no_subagents=True)
    cli._collab_command(args, claude_backend=None, codex_backend=None,
                        human_gate=lambda *a, **k: None)
    assert captured == {"claude": False, "codex": False}
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_subagents.py -v`.

- [ ] **Step 3: Modify `macr/cli.py`:**

(i) Add the flag to the `collab` subparser (after the `--timeout` argument):
```python
    collab_p.add_argument("--no-subagents", action="store_true",
                          help="disable native subagents in Claude/Codex")
```

(ii) In `_collab_command`, pass `enable_subagents` when constructing real backends. Replace the construction block:
```python
        from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend

        enable = not getattr(args, "no_subagents", False)
        if claude_backend is None:
            claude_backend = ClaudeCliBackend(
                model=args.claude_model, timeout=args.timeout, enable_subagents=enable)
        if codex_backend is None:
            codex_backend = CodexCliBackend(
                model=args.codex_model, timeout=args.timeout, enable_subagents=enable)
```

- [ ] **Step 4: Run new tests + the FULL suite** — `.venv/bin/pytest tests/test_cli_subagents.py tests/test_cli_collab.py tests/test_cli.py -v` then `.venv/bin/pytest -q`. Everything must pass. Fix regressions before committing.

- [ ] **Step 5: Commit**
```bash
git add macr/cli.py tests/test_cli_subagents.py
git commit -m "feat: add --no-subagents flag to macr collab"
```

---

### Task 7: README + calibration note

**Files:** Modify `README.md` (append only); Create `docs/superpowers/STAGE_B_CALIBRATION.md`.

- [ ] **Step 1: Create `docs/superpowers/STAGE_B_CALIBRATION.md`:**
```markdown
# Stage B — subagent 解析器真实校准(待人工执行)

Stage B 的解析器(`macr/agents/trace.py`)对 Claude `stream-json` / Codex `--json` 的事件 schema 是**防御式假设**(见 spec §7)。需要用真实 CLI 校准一次:

```bash
.venv/bin/python scripts/smoke_collab.py <真实git仓库> "pytest -q" "一个小任务"
# 查看捕获的原始事件流:
ls .macr/runs/<run_id>/subagents/*.events.jsonl
```

对照真实事件的键名,若与 `parse_claude_stream` / `parse_codex_stream` 的假设(`type=="result"` 的 `result` 字段;`parent_tool_use_id`;`thread.started` 的 `thread_id`;`item.completed` 的 `agent_message.text`)有出入,就微调这两个解析器并补一条对应的合成-流单测。原始 `events.jsonl` 始终全保真落盘,即便摘要解析暂不完美也不丢可追踪性。
```

- [ ] **Step 2: Append to the END of `README.md`** (keep all existing content):
```markdown

### 嵌套 subagent (Stage B) / Nested subagents

`macr collab` 默认允许 Claude(`Agent` 工具)与 Codex(`multi_agent`)使用各自的**原生 subagent**;用 `--no-subagents` 关闭。每个角色调用的原始事件流与 subagent 摘要落在 `.macr/runs/<run_id>/subagents/`。解析器为防御式,真实事件 schema 校准见 `docs/superpowers/STAGE_B_CALIBRATION.md`。
```

- [ ] **Step 3: Full suite still green** — `.venv/bin/pytest -q`.

- [ ] **Step 4: Commit**
```bash
git add README.md docs/superpowers/STAGE_B_CALIBRATION.md
git commit -m "docs: document Stage B subagents usage and parser calibration"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §4 module map → Task 2 (trace.py), 3 (base/api trace param), 4 (cli_backend streaming), 5 (orchestrator), 6 (cli), 1 (schemas).
- §4.1 `run_role(trace=None)`, old backends ignore → Task 3 (Protocol + FakeAgentBackend + ApiBackend).
- §5.1 SubagentRecord + state.subagents → Task 1; §5.2 defensive parsers → Task 2; §5.3 TraceSink → Task 2; §5.4 run-dir `subagents/` layout → Task 5 (sinks write under `run_path/subagents`).
- §6 Claude stream-json + allowedTools+Agent + worktree cwd; Codex --json; enable_subagents toggle; capture on success → Task 4. §6.3 capture last attempt → Task 4 (`captured` holder updated each call, captured after success).
- §7 defensive parse + "no final result → retry → BLOCKED" → Task 2 (never-raise parsers) + Task 3 (`validate_with_retry` catches `ValueError`) + Task 4 (empty `final_text` → `extract_json_object` ValueError → retry → AgentError; test `test_claude_empty_result_retries_then_raises`).
- §8 orchestrator trace wiring + state.subagents + final overview + state.json → Task 5. CLI `--no-subagents` → Task 6.
- §9 capture-failure non-fatal: `trace.capture` only runs after a successful result; if it raised it would propagate — acceptable since it writes to the run dir which already exists. (No extra guard added; matches "附带产物" intent without masking real IO errors. If hardening is wanted later, wrap the single `trace.capture` call.) CLI timeout→AgentError already from Stage A SubprocessRunner.
- §10 tests: parsers (Task 2), TraceSink (Task 2), backends incl. enable toggle + cwd + capture + retry (Task 4), base/api (Task 3), orchestrator aggregation (Task 5), cli flag (Task 6), V1+Stage A regressions re-run (Tasks 3/4/5/6). Real CLIs only in smoke (Task 7 calibration doc). §11 DoD covered.

**Placeholder scan:** No TBD/TODO. All code steps complete. The calibration doc is an intentional deliverable (spec §7), not a placeholder.

**Type/name consistency:** `run_role(..., trace: TraceSink | None = None)` identical across Protocol (Task 3), FakeAgentBackend (3), ApiBackend (3), ClaudeCliBackend/CodexCliBackend (4); call sites in orchestrator pass `trace=` (5). `parse_claude_stream`/`parse_codex_stream` return `(str, list[SubagentRecord])` (Task 2) consumed in Task 4. `TraceSink(directory, label)` + `.capture(raw_lines, subagents)` + `.records` consistent Tasks 2↔3↔4↔5. `SubagentRecord(source, agent_type, ref)` consistent Tasks 1↔2↔3↔4↔5. `enable_subagents` ctor kwarg consistent Tasks 4↔6. `_record_subagents(state, sink, role, attempt)` defined+used in Task 5. `validate_with_retry` now catches `(ValidationError, ValueError)` — Stage A's `test_claude_backend_nonzero_exit_raises` still passes because `call_fn` raises `AgentError` (not caught) on nonzero exit. **Important:** Task 4 rewrites `tests/test_cli_backend.py` wholesale because Stage A's version asserted the now-removed `--output-format json`.
