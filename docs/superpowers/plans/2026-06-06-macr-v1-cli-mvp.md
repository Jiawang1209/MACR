# MACR V1 CLI MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hand-rolled Python CLI (`macr run "<task>"`) that runs the MACR loop — Planner → Executor → Reviewer → Evaluator → (revision loop) → interactive Human Gate → Final — using a single Claude model differentiated by role specs, with all artifacts written to `.macr/runs/<run_id>/`.

**Architecture:** Flat `macr/` package. `llm.py` is the only network boundary (a `LLM` Protocol with `AnthropicLLM` real impl + `FakeLLM` for tests). Four roles are data (`roles.py`); one generic `agent.run_agent` executes any role via Anthropic tool-use forced schemas (Pydantic). `orchestrator.run_task` drives the loop and persistence. Everything is dependency-injected (llm, human-gate input fn, runs dir, clock) so the whole system is testable without real API calls.

**Tech Stack:** Python 3.11+ (3.13 available via miniforge), Pydantic v2, `anthropic` SDK, pytest. **Isolation rule (hard):** a project-local `.venv` only — never install into the base/miniforge env. `uv` is not installed; use stdlib `venv` + `pip`.

**Spec:** `docs/superpowers/specs/2026-06-06-macr-v1-cli-mvp-design.md`.

**Conventions for every task:**
- Run all Python/pytest via `.venv/bin/...` (created in Task 1).
- TDD: write the failing test, see it fail, implement, see it pass, commit.
- Commit messages: plain, no `Co-Authored-By` / AI attribution (user preference).
- After Task 1, every test run command is `.venv/bin/pytest <path> -v`.

---

### Task 1: Project scaffold + isolated venv

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `macr/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "macr"
version = "0.1.0"
description = "MACR — Multi-Agent Collaborative Reasoning Framework (CLI MVP)"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "anthropic>=0.40",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
macr = "macr.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["macr"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.macr/
.pytest_cache/
*.egg-info/
dist/
build/
```

- [ ] **Step 3: Create empty package + test markers**

`macr/__init__.py`:
```python
"""MACR — Multi-Agent Collaborative Reasoning Framework (CLI MVP)."""

__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

`tests/test_smoke.py`:
```python
import macr


def test_package_imports():
    assert macr.__version__ == "0.1.0"
```

- [ ] **Step 4: Create the isolated venv and install (NEVER touch base env)**

Run:
```bash
cd /Users/liuyue/Desktop/Github_repos/MACR
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```
Expected: installs into `.venv` only; `macr` installed in editable mode.

- [ ] **Step 5: Run the smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS (1 passed). Also confirm `.venv/bin/macr --help` does NOT yet work (cli not built) — that's fine.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore macr/ tests/
git commit -m "feat: scaffold macr package with isolated venv and pytest"
```

---

### Task 2: `utils.py` — clock and run-id

**Files:**
- Create: `macr/utils.py`
- Create: `tests/test_utils.py`

- [ ] **Step 1: Write the failing test**

`tests/test_utils.py`:
```python
from macr.utils import now_iso, next_run_id


def test_now_iso_is_iso8601_z():
    s = now_iso()
    assert s.endswith("Z")
    assert "T" in s


def test_next_run_id_first_is_001(tmp_path):
    assert next_run_id(tmp_path, today="20260606") == "R20260606_001"


def test_next_run_id_increments(tmp_path):
    (tmp_path / "R20260606_001").mkdir()
    (tmp_path / "R20260606_002").mkdir()
    assert next_run_id(tmp_path, today="20260606") == "R20260606_003"


def test_next_run_id_ignores_other_days(tmp_path):
    (tmp_path / "R20260101_009").mkdir()
    assert next_run_id(tmp_path, today="20260606") == "R20260606_001"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_utils.py -v`
Expected: FAIL (ModuleNotFoundError: macr.utils).

- [ ] **Step 3: Implement `macr/utils.py`**

```python
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """UTC timestamp in ISO-8601 with a trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_run_id(runs_dir: Path, today: str | None = None) -> str:
    """Return R<today>_<NNN>, NNN one past the highest existing for `today`.

    today defaults to the current UTC date as YYYYMMDD.
    """
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = re.compile(rf"^R{today}_(\d{{3}})$")
    highest = 0
    if runs_dir.exists():
        for child in runs_dir.iterdir():
            m = pattern.match(child.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"R{today}_{highest + 1:03d}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_utils.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/utils.py tests/test_utils.py
git commit -m "feat: add utils for iso timestamps and sequential run ids"
```

---

### Task 3: `schemas.py` — messages, role outputs, shared state

**Files:**
- Create: `macr/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from macr.schemas import (
    Decision,
    EvaluatorOutput,
    ExecutorOutput,
    Finding,
    HumanFeedback,
    Message,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_message_type_values():
    assert MessageType.PROPOSAL.value == "proposal"
    assert MessageType.EVALUATION.value == "evaluation"


def test_decision_enum():
    assert Decision.PASS.value == "PASS"
    assert {d.value for d in Decision} == {"PASS", "NEEDS_FIX", "BLOCKED"}


def test_planner_output_defaults():
    p = PlannerOutput(summary="do it", steps=["a", "b"])
    assert p.tools_needed == [] and p.risks == []


def test_reviewer_output_requires_decision():
    with pytest.raises(ValidationError):
        ReviewerOutput(summary="x")  # missing decision


def test_reviewer_finding_roundtrip():
    r = ReviewerOutput(
        summary="ok",
        findings=[Finding(level="blocking", issue="i", evidence="e", recommendation="r")],
        decision="needs_fix",
    )
    assert r.findings[0].level == "blocking"


def test_evaluator_output():
    e = EvaluatorOutput(decision=Decision.PASS, reasons=["good"], confidence=0.9)
    assert e.decision is Decision.PASS


def test_executor_output_defaults():
    ex = ExecutorOutput(artifact="hello")
    assert ex.notes == "" and ex.evidence == []


def test_shared_state_default_buckets():
    s = SharedState(run_id="R1", user_query="q")
    assert set(s.agent_outputs) == {"planner", "executor", "reviewer", "evaluator"}
    assert s.human_feedback is None and s.final_output is None


def test_human_feedback():
    hf = HumanFeedback(decision="approve", feedback="", timestamp="2026-06-06T00:00:00Z")
    assert hf.decision == "approve"


def test_message_construct():
    m = Message(
        task_id="T1", run_id="R1", agent_id="planner_agent", role="planner",
        message_type=MessageType.PLAN, content={"summary": "x"},
        timestamp="2026-06-06T00:00:00Z",
    )
    assert m.status == "submitted"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_schemas.py -v`
Expected: FAIL (ModuleNotFoundError: macr.schemas).

- [ ] **Step 3: Implement `macr/schemas.py`**

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TASK = "task"
    PROPOSAL = "proposal"
    PLAN = "plan"
    RESULT = "result"
    REVIEW = "review"
    CRITIQUE = "critique"
    REVISION_REQUEST = "revision_request"
    REVISION_RESULT = "revision_result"
    TEST_REPORT = "test_report"
    EVALUATION = "evaluation"
    DECISION = "decision"
    HUMAN_FEEDBACK = "human_feedback"


class Decision(str, Enum):
    PASS = "PASS"
    NEEDS_FIX = "NEEDS_FIX"
    BLOCKED = "BLOCKED"


# --- Role content schemas (these become tool-use input schemas) ---

class PlannerOutput(BaseModel):
    summary: str
    steps: list[str]
    tools_needed: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ExecutorOutput(BaseModel):
    artifact: str
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    level: Literal["blocking", "non_blocking"]
    issue: str
    evidence: str
    recommendation: str


class ReviewerOutput(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    decision: Literal["approve", "needs_fix"]


class EvaluatorOutput(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    confidence: float


class HumanFeedback(BaseModel):
    decision: Literal["approve", "reject"]
    feedback: str = ""
    timestamp: str


# --- Envelope + shared state ---

class Message(BaseModel):
    task_id: str
    run_id: str
    agent_id: str
    role: str
    message_type: MessageType
    content: dict
    references: list[str] = Field(default_factory=list)
    timestamp: str
    status: str = "submitted"


def _empty_buckets() -> dict[str, list[dict]]:
    return {"planner": [], "executor": [], "reviewer": [], "evaluator": []}


class SharedState(BaseModel):
    run_id: str
    user_query: str
    task_plan: list[str] = Field(default_factory=list)
    agent_outputs: dict[str, list[dict]] = Field(default_factory=_empty_buckets)
    reviews: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    human_feedback: HumanFeedback | None = None
    final_output: str | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_schemas.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/schemas.py tests/test_schemas.py
git commit -m "feat: add pydantic schemas for messages, role outputs, shared state"
```

---

### Task 4: `runlog.py` — write the run directory

**Files:**
- Create: `macr/runlog.py`
- Create: `tests/test_runlog.py`

- [ ] **Step 1: Write the failing test**

`tests/test_runlog.py`:
```python
import json

from macr.runlog import RunLog
from macr.schemas import SharedState


def test_runlog_writes_all_files(tmp_path):
    run_path = tmp_path / "R20260606_001"
    log = RunLog(run_path)
    log.write_input("build a thing")
    log.write_planner({"summary": "plan", "steps": ["a"]})
    log.write_executor({"artifact": "code v1", "notes": "", "evidence": []}, attempt=1)
    log.write_reviewer({"summary": "lgtm", "findings": [], "decision": "approve"})
    log.write_evaluator({"decision": "PASS", "reasons": ["ok"], "confidence": 0.9})
    log.write_final("final text")
    state = SharedState(run_id="R20260606_001", user_query="build a thing")
    log.write_state(state)

    assert (run_path / "input.md").read_text().strip() == "build a thing"
    assert "plan" in (run_path / "planner.output.md").read_text()
    assert "code v1" in (run_path / "executor.output.md").read_text()
    assert (run_path / "reviewer.output.md").exists()
    ev = json.loads((run_path / "evaluator.output.json").read_text())
    assert ev["decision"] == "PASS"
    assert (run_path / "final.md").read_text() == "final text"
    st = json.loads((run_path / "state.json").read_text())
    assert st["run_id"] == "R20260606_001"


def test_runlog_executor_revision_keeps_history(tmp_path):
    run_path = tmp_path / "R1"
    log = RunLog(run_path)
    log.write_executor({"artifact": "v1", "notes": "", "evidence": []}, attempt=1)
    log.write_executor({"artifact": "v2", "notes": "", "evidence": []}, attempt=2)
    # latest always at executor.output.md; history preserved per attempt
    assert "v2" in (run_path / "executor.output.md").read_text()
    assert "v1" in (run_path / "executor.output.v1.md").read_text()
    assert "v2" in (run_path / "executor.output.v2.md").read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_runlog.py -v`
Expected: FAIL (ModuleNotFoundError: macr.runlog).

- [ ] **Step 3: Implement `macr/runlog.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

from macr.schemas import SharedState


class RunLog:
    """Writes all artifacts for one run into `.macr/runs/<run_id>/`."""

    def __init__(self, run_path: Path):
        self.run_path = run_path
        self.run_path.mkdir(parents=True, exist_ok=True)

    def _write(self, name: str, text: str) -> None:
        (self.run_path / name).write_text(text, encoding="utf-8")

    def write_input(self, task: str) -> None:
        self._write("input.md", f"# Task\n\n{task}\n")

    def write_planner(self, content: dict) -> None:
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(content.get("steps", []), 1))
        risks = "\n".join(f"- {r}" for r in content.get("risks", []))
        self._write(
            "planner.output.md",
            f"# Planner\n\n## Summary\n{content.get('summary', '')}\n\n"
            f"## Steps\n{steps}\n\n## Risks\n{risks}\n",
        )

    def write_executor(self, content: dict, attempt: int) -> None:
        body = (
            f"# Executor (attempt {attempt})\n\n## Artifact\n{content.get('artifact', '')}\n\n"
            f"## Notes\n{content.get('notes', '')}\n"
        )
        self._write(f"executor.output.v{attempt}.md", body)
        self._write("executor.output.md", body)

    def write_reviewer(self, content: dict) -> None:
        findings = "\n".join(
            f"- [{f.get('level')}] {f.get('issue')} — {f.get('recommendation')} ({f.get('evidence')})"
            for f in content.get("findings", [])
        )
        self._write(
            "reviewer.output.md",
            f"# Reviewer\n\n## Summary\n{content.get('summary', '')}\n\n"
            f"## Decision\n{content.get('decision', '')}\n\n## Findings\n{findings}\n",
        )

    def write_evaluator(self, content: dict) -> None:
        self._write("evaluator.output.json", json.dumps(content, ensure_ascii=False, indent=2))

    def write_final(self, text: str) -> None:
        self._write("final.md", text)

    def write_state(self, state: SharedState) -> None:
        self._write("state.json", state.model_dump_json(indent=2))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_runlog.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/runlog.py tests/test_runlog.py
git commit -m "feat: add runlog writing run artifacts with revision history"
```

---

### Task 5: `llm.py` — LLM protocol, FakeLLM, AnthropicLLM

**Files:**
- Create: `macr/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
import pytest

from macr.llm import FakeLLM, LLMError, extract_tool_input


def test_fakellm_pops_in_order():
    llm = FakeLLM([{"a": 1}, {"b": 2}])
    assert llm.call_role(system="s", user="u", tool_name="t", tool_schema={}) == {"a": 1}
    assert llm.call_role(system="s", user="u", tool_name="t", tool_schema={}) == {"b": 2}


def test_fakellm_records_calls():
    llm = FakeLLM([{"a": 1}])
    llm.call_role(system="sys", user="usr", tool_name="submit_plan", tool_schema={})
    assert llm.calls[0]["tool_name"] == "submit_plan"
    assert llm.calls[0]["user"] == "usr"


def test_fakellm_exhausted_raises():
    llm = FakeLLM([])
    with pytest.raises(LLMError):
        llm.call_role(system="s", user="u", tool_name="t", tool_schema={})


class _Block:
    def __init__(self, type_, name=None, input_=None):
        self.type = type_
        self.name = name
        self.input = input_


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


def test_extract_tool_input_finds_matching_tool():
    resp = _Resp([_Block("text"), _Block("tool_use", name="submit_plan", input_={"summary": "x"})])
    assert extract_tool_input(resp, "submit_plan") == {"summary": "x"}


def test_extract_tool_input_missing_raises():
    resp = _Resp([_Block("text")])
    with pytest.raises(LLMError):
        extract_tool_input(resp, "submit_plan")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_llm.py -v`
Expected: FAIL (ModuleNotFoundError: macr.llm).

- [ ] **Step 3: Implement `macr/llm.py`**

```python
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Raised when the model call fails or returns no usable tool output."""


@runtime_checkable
class LLM(Protocol):
    def call_role(
        self, *, system: str, user: str, tool_name: str, tool_schema: dict
    ) -> dict:
        """Return the raw tool-input dict the model produced for `tool_name`."""
        ...


def extract_tool_input(response: Any, tool_name: str) -> dict:
    """Pull the input of the first `tool_use` block matching tool_name."""
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input)
    raise LLMError(f"model did not call tool '{tool_name}'")


class FakeLLM:
    """Test double: returns scripted dicts in order; records calls."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def call_role(self, *, system: str, user: str, tool_name: str, tool_schema: dict) -> dict:
        self.calls.append(
            {"system": system, "user": user, "tool_name": tool_name, "tool_schema": tool_schema}
        )
        if not self._responses:
            raise LLMError("FakeLLM exhausted")
        return self._responses.pop(0)


class AnthropicLLM:
    """Real implementation using the Anthropic SDK with forced tool-use."""

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 4096, client: Any = None):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            import anthropic  # imported lazily so tests never need the network

            client = anthropic.Anthropic()
        self._client = client

    def call_role(self, *, system: str, user: str, tool_name: str, tool_schema: dict) -> dict:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[{"name": tool_name, "description": f"Submit the {tool_name} result.", "input_schema": tool_schema}],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # surface SDK/network errors as LLMError
            raise LLMError(f"Anthropic call failed: {exc}") from exc
        return extract_tool_input(response, tool_name)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_llm.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/llm.py tests/test_llm.py
git commit -m "feat: add LLM protocol, FakeLLM test double, and AnthropicLLM tool-use client"
```

---

### Task 6: `roles.py` — the four role specs

**Files:**
- Create: `macr/roles.py`
- Create: `tests/test_roles.py`

- [ ] **Step 1: Write the failing test**

`tests/test_roles.py`:
```python
from macr.roles import EVALUATOR, EXECUTOR, PLANNER, REVIEWER, ROLES
from macr.schemas import (
    EvaluatorOutput,
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_roles_registry():
    assert set(ROLES) == {"planner", "executor", "reviewer", "evaluator"}


def test_role_specs_wired_correctly():
    assert PLANNER.content_model is PlannerOutput
    assert EXECUTOR.content_model is ExecutorOutput
    assert REVIEWER.content_model is ReviewerOutput
    assert EVALUATOR.content_model is EvaluatorOutput
    assert PLANNER.tool_name == "submit_plan"
    assert EVALUATOR.message_type is MessageType.EVALUATION


def test_planner_user_includes_task():
    state = SharedState(run_id="R1", user_query="build a parser")
    assert "build a parser" in PLANNER.build_user(state)


def test_executor_user_includes_plan_steps():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["planner"].append({"summary": "s", "steps": ["step-one"], "risks": []})
    assert "step-one" in EXECUTOR.build_user(state)


def test_executor_user_includes_review_feedback_on_revision():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["planner"].append({"summary": "s", "steps": ["x"], "risks": []})
    state.agent_outputs["executor"].append({"artifact": "v1", "notes": "", "evidence": []})
    state.agent_outputs["reviewer"].append(
        {"summary": "needs work", "findings": [], "decision": "needs_fix"}
    )
    user = EXECUTOR.build_user(state)
    assert "needs work" in user


def test_reviewer_user_includes_executor_artifact():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["executor"].append({"artifact": "THE CODE", "notes": "", "evidence": []})
    assert "THE CODE" in REVIEWER.build_user(state)


def test_evaluator_user_includes_artifact_and_review():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["executor"].append({"artifact": "ART", "notes": "", "evidence": []})
    state.agent_outputs["reviewer"].append(
        {"summary": "REV", "findings": [], "decision": "approve"}
    )
    user = EVALUATOR.build_user(state)
    assert "ART" in user and "REV" in user


def test_tool_schema_is_generated_from_model():
    schema = PLANNER.content_model.model_json_schema()
    assert "summary" in schema["properties"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_roles.py -v`
Expected: FAIL (ModuleNotFoundError: macr.roles).

- [ ] **Step 3: Implement `macr/roles.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from macr.schemas import (
    EvaluatorOutput,
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


@dataclass(frozen=True)
class RoleSpec:
    name: str
    agent_id: str
    tool_name: str
    message_type: MessageType
    content_model: type[BaseModel]
    system_prompt: str
    build_user: Callable[[SharedState], str]


def _latest(state: SharedState, bucket: str) -> dict | None:
    items = state.agent_outputs.get(bucket, [])
    return items[-1] if items else None


def _planner_user(state: SharedState) -> str:
    return f"任务 / Task:\n{state.user_query}\n\n请制定方案:总结、分步骤、所需工具、潜在风险。"


def _executor_user(state: SharedState) -> str:
    plan = _latest(state, "planner") or {}
    steps = "\n".join(f"- {s}" for s in plan.get("steps", []))
    parts = [
        f"任务 / Task:\n{state.user_query}",
        f"方案步骤 / Plan steps:\n{steps}",
    ]
    review = _latest(state, "reviewer")
    if review is not None:
        findings = "\n".join(
            f"- {f.get('issue')}: {f.get('recommendation')}" for f in review.get("findings", [])
        )
        parts.append(
            "上一轮审查反馈 / Previous review feedback:\n"
            f"{review.get('summary', '')}\n{findings}\n请据此修订产物。"
        )
    parts.append("请产出 artifact(正文/代码片段)、notes 与 evidence。")
    return "\n\n".join(parts)


def _reviewer_user(state: SharedState) -> str:
    ex = _latest(state, "executor") or {}
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"待审产物 / Artifact to review:\n{ex.get('artifact', '')}\n\n"
        "请审查:逻辑错误、是否偏离任务、是否缺证据;给出 findings 与 decision(approve/needs_fix)。"
    )


def _evaluator_user(state: SharedState) -> str:
    ex = _latest(state, "executor") or {}
    rev = _latest(state, "reviewer") or {}
    findings = "\n".join(f"- {f.get('issue')}" for f in rev.get("findings", []))
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"产物 / Artifact:\n{ex.get('artifact', '')}\n\n"
        f"审查意见 / Review:\n{rev.get('summary', '')}\n{findings}\n\n"
        "请判定 decision(PASS/NEEDS_FIX/BLOCKED)、reasons 与 confidence(0-1)。"
    )


PLANNER = RoleSpec(
    name="planner", agent_id="planner_agent", tool_name="submit_plan",
    message_type=MessageType.PLAN, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 的 Planner 智能体。只负责规划:把任务拆成清晰步骤、列出所需工具与风险。"
        "不要执行任务,不要评判合格。必须通过 submit_plan 工具提交结构化结果。"
    ),
    build_user=_planner_user,
)

EXECUTOR = RoleSpec(
    name="executor", agent_id="executor_agent", tool_name="submit_result",
    message_type=MessageType.RESULT, content_model=ExecutorOutput,
    system_prompt=(
        "你是 MACR 的 Executor 智能体。严格按既定方案执行,产出真实的文本/代码片段 artifact,"
        "并记录 notes 与 evidence。若收到审查反馈,请据此修订。不要自评是否合格。"
        "必须通过 submit_result 工具提交结构化结果。"
    ),
    build_user=_executor_user,
)

REVIEWER = RoleSpec(
    name="reviewer", agent_id="reviewer_agent", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 的 Reviewer 智能体。只审查产物,不重写产物。检查逻辑错误、是否偏离任务、"
        "证据是否充分;每个 finding 含 level/issue/evidence/recommendation;给出 decision。"
        "必须通过 submit_review 工具提交结构化结果。"
    ),
    build_user=_reviewer_user,
)

EVALUATOR = RoleSpec(
    name="evaluator", agent_id="evaluator_agent", tool_name="submit_evaluation",
    message_type=MessageType.EVALUATION, content_model=EvaluatorOutput,
    system_prompt=(
        "你是 MACR 的 Evaluator 智能体,质量门控。基于产物+审查意见判定 PASS/NEEDS_FIX/BLOCKED,"
        "给出 reasons 与 confidence。证据严重不足或任务不可达时用 BLOCKED。不要执行任务。"
        "必须通过 submit_evaluation 工具提交结构化结果。"
    ),
    build_user=_evaluator_user,
)

ROLES: dict[str, RoleSpec] = {
    r.name: r for r in (PLANNER, EXECUTOR, REVIEWER, EVALUATOR)
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_roles.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/roles.py tests/test_roles.py
git commit -m "feat: add four role specs (prompt + schema + input selector)"
```

---

### Task 7: `agent.py` — generic role runner with validate-and-retry

**Files:**
- Create: `macr/agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

`tests/test_agent.py`:
```python
import pytest

from macr.agent import AgentError, run_agent
from macr.llm import FakeLLM
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def _state():
    return SharedState(run_id="R1", user_query="build a parser")


def test_run_agent_returns_validated_message():
    llm = FakeLLM([{"summary": "plan it", "steps": ["a", "b"], "tools_needed": [], "risks": []}])
    msg = run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="2026-06-06T00:00:00Z")
    assert msg.message_type is MessageType.PLAN
    assert msg.role == "planner"
    assert msg.agent_id == "planner_agent"
    assert msg.content["steps"] == ["a", "b"]
    # forced tool was requested
    assert llm.calls[0]["tool_name"] == "submit_plan"


def test_run_agent_retries_once_on_invalid_then_succeeds():
    llm = FakeLLM([
        {"summary": "missing steps"},  # invalid: steps required -> triggers retry
        {"summary": "ok", "steps": ["x"], "tools_needed": [], "risks": []},
    ])
    msg = run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="t")
    assert msg.content["steps"] == ["x"]
    assert len(llm.calls) == 2
    # the retry user prompt should mention validation failure
    assert "validation" in llm.calls[1]["user"].lower()


def test_run_agent_raises_after_second_failure():
    llm = FakeLLM([{"bad": 1}, {"also": "bad"}])
    with pytest.raises(AgentError):
        run_agent(PLANNER, _state(), llm, task_id="R1", run_id="R1", timestamp="t")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_agent.py -v`
Expected: FAIL (ModuleNotFoundError: macr.agent).

- [ ] **Step 3: Implement `macr/agent.py`**

```python
from __future__ import annotations

from pydantic import ValidationError

from macr.llm import LLM, LLMError
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState
from macr.utils import now_iso


class AgentError(RuntimeError):
    """Raised when a role cannot produce schema-valid output after one retry."""


def run_agent(
    role: RoleSpec,
    state: SharedState,
    llm: LLM,
    *,
    task_id: str,
    run_id: str,
    timestamp: str | None = None,
) -> Message:
    system = role.system_prompt
    user = role.build_user(state)
    schema = role.content_model.model_json_schema()

    try:
        raw = llm.call_role(system=system, user=user, tool_name=role.tool_name, tool_schema=schema)
        model = role.content_model(**raw)
    except (ValidationError, LLMError) as first_err:
        retry_user = (
            f"{user}\n\n上一次输出未通过校验 / Previous output failed validation:\n"
            f"{first_err}\n请严格按 schema 重新提交。"
        )
        try:
            raw = llm.call_role(
                system=system, user=retry_user, tool_name=role.tool_name, tool_schema=schema
            )
            model = role.content_model(**raw)
        except (ValidationError, LLMError) as second_err:
            raise AgentError(f"{role.name} failed schema validation twice: {second_err}") from second_err

    return Message(
        task_id=task_id,
        run_id=run_id,
        agent_id=role.agent_id,
        role=role.name,
        message_type=role.message_type,
        content=model.model_dump(),
        timestamp=timestamp or now_iso(),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_agent.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/agent.py tests/test_agent.py
git commit -m "feat: add generic agent runner with one validate-and-retry"
```

---

### Task 8: `human_gate.py` — interactive approve/reject/edit

**Files:**
- Create: `macr/human_gate.py`
- Create: `tests/test_human_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_human_gate.py`:
```python
from macr.human_gate import interactive_human_gate
from macr.schemas import SharedState


def _state_with_artifact():
    s = SharedState(run_id="R1", user_query="q")
    s.agent_outputs["executor"].append({"artifact": "FINAL ART", "notes": "", "evidence": []})
    return s


def test_approve():
    out = []
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: "a", printer=out.append,
        timestamp="2026-06-06T00:00:00Z",
    )
    assert hf.decision == "approve" and hf.feedback == ""
    assert any("FINAL ART" in line for line in out)


def test_reject_collects_reason():
    answers = iter(["r", "not good enough"])
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: next(answers), printer=lambda *_: None,
        timestamp="t",
    )
    assert hf.decision == "reject" and hf.feedback == "not good enough"


def test_edit_is_approve_with_feedback():
    answers = iter(["e", "tweak the wording"])
    hf = interactive_human_gate(
        _state_with_artifact(), input_fn=lambda prompt: next(answers), printer=lambda *_: None,
        timestamp="t",
    )
    assert hf.decision == "approve" and hf.feedback == "tweak the wording"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_human_gate.py -v`
Expected: FAIL (ModuleNotFoundError: macr.human_gate).

- [ ] **Step 3: Implement `macr/human_gate.py`**

```python
from __future__ import annotations

from typing import Callable

from macr.schemas import HumanFeedback, SharedState
from macr.utils import now_iso


def _latest_artifact(state: SharedState) -> str:
    items = state.agent_outputs.get("executor", [])
    return items[-1].get("artifact", "") if items else ""


def interactive_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] = input,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    ts = timestamp or now_iso()
    printer("\n===== Human Gate =====")
    printer(f"Task: {state.user_query}")
    printer("Final artifact:\n")
    printer(_latest_artifact(state))
    printer("\n[a]pprove / [r]eject / [e]dit")

    choice = input_fn("> ").strip().lower()
    if choice.startswith("r"):
        reason = input_fn("Reject reason: ").strip()
        return HumanFeedback(decision="reject", feedback=reason, timestamp=ts)
    if choice.startswith("e"):
        fb = input_fn("Feedback / edits: ").strip()
        return HumanFeedback(decision="approve", feedback=fb, timestamp=ts)
    return HumanFeedback(decision="approve", feedback="", timestamp=ts)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_human_gate.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/human_gate.py tests/test_human_gate.py
git commit -m "feat: add interactive human gate (approve/reject/edit)"
```

---

### Task 9: `orchestrator.py` — the Supervisor loop

**Files:**
- Create: `macr/orchestrator.py`
- Create: `tests/test_orchestrator.py`

This is the integration core. It wires Planner → (Executor → Reviewer → Evaluator)* → Human Gate, persists every step, and bounds revisions.

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:
```python
import json

from macr.llm import FakeLLM
from macr.orchestrator import run_task
from macr.schemas import HumanFeedback


def _plan():
    return {"summary": "plan", "steps": ["s1"], "tools_needed": [], "risks": []}


def _exec(v):
    return {"artifact": f"artifact-{v}", "notes": "", "evidence": []}


def _review(decision):
    return {"summary": "rev", "findings": [], "decision": decision}


def _eval(decision):
    return {"decision": decision, "reasons": ["r"], "confidence": 0.9}


def _approve_gate(state, **kwargs):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def test_pass_path_writes_all_artifacts(tmp_path):
    llm = FakeLLM([_plan(), _exec(1), _review("approve"), _eval("PASS")])
    state = run_task(
        "build a thing", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    run_path = tmp_path / "R20260606_001"
    assert (run_path / "input.md").exists()
    assert (run_path / "planner.output.md").exists()
    assert "artifact-1" in (run_path / "executor.output.md").read_text()
    assert (run_path / "evaluator.output.json").exists()
    assert state.human_feedback.decision == "approve"
    assert state.final_output is not None and "artifact-1" in state.final_output
    saved = json.loads((run_path / "state.json").read_text())
    assert saved["decisions"][-1]["decision"] == "PASS"


def test_needs_fix_then_pass_runs_revision(tmp_path):
    llm = FakeLLM([
        _plan(),
        _exec(1), _review("needs_fix"), _eval("NEEDS_FIX"),
        _exec(2), _review("approve"), _eval("PASS"),
    ])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    run_path = tmp_path / "R20260606_001"
    assert "artifact-2" in (run_path / "executor.output.md").read_text()
    assert (run_path / "executor.output.v1.md").exists()
    assert (run_path / "executor.output.v2.md").exists()
    assert [d["decision"] for d in state.decisions] == ["NEEDS_FIX", "PASS"]


def test_blocked_goes_straight_to_gate(tmp_path):
    llm = FakeLLM([_plan(), _exec(1), _review("needs_fix"), _eval("BLOCKED")])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    assert [d["decision"] for d in state.decisions] == ["BLOCKED"]
    assert state.human_feedback is not None


def test_revisions_exhausted_goes_to_gate(tmp_path):
    # max_revisions=1 -> total 2 attempts, both NEEDS_FIX -> gate
    llm = FakeLLM([
        _plan(),
        _exec(1), _review("needs_fix"), _eval("NEEDS_FIX"),
        _exec(2), _review("needs_fix"), _eval("NEEDS_FIX"),
    ])
    state = run_task(
        "task", llm, tmp_path, max_revisions=1,
        human_gate=_approve_gate, printer=lambda *_: None, today="20260606",
    )
    assert len(state.decisions) == 2
    assert all(d["decision"] == "NEEDS_FIX" for d in state.decisions)
    assert state.human_feedback is not None


def test_reject_sets_feedback(tmp_path):
    def reject_gate(state, **kwargs):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")

    llm = FakeLLM([_plan(), _exec(1), _review("approve"), _eval("PASS")])
    state = run_task(
        "task", llm, tmp_path, max_revisions=2,
        human_gate=reject_gate, printer=lambda *_: None, today="20260606",
    )
    assert state.human_feedback.decision == "reject"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_orchestrator.py -v`
Expected: FAIL (ModuleNotFoundError: macr.orchestrator).

- [ ] **Step 3: Implement `macr/orchestrator.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from macr.agent import run_agent
from macr.human_gate import interactive_human_gate
from macr.llm import LLM
from macr.roles import EVALUATOR, EXECUTOR, PLANNER, REVIEWER
from macr.runlog import RunLog
from macr.schemas import Decision, HumanFeedback, SharedState
from macr.utils import next_run_id

HumanGate = Callable[..., HumanFeedback]


def _build_final(state: SharedState) -> str:
    ex = state.agent_outputs["executor"][-1] if state.agent_outputs["executor"] else {}
    trail = " → ".join(d["decision"] for d in state.decisions) or "(no evaluation)"
    parts = [
        "# Final Output",
        f"\n## Task\n{state.user_query}",
        f"\n## Artifact\n{ex.get('artifact', '')}",
        f"\n## Decision trail\n{trail}",
    ]
    hf = state.human_feedback
    if hf is not None:
        parts.append(f"\n## Human decision\n{hf.decision}")
        if hf.feedback:
            parts.append(f"\n## 人工批注 / Human annotation\n{hf.feedback}")
    return "\n".join(parts) + "\n"


def run_task(
    task: str,
    llm: LLM,
    runs_dir: Path,
    *,
    max_revisions: int = 2,
    human_gate: HumanGate = interactive_human_gate,
    printer: Callable[..., None] = print,
    today: str | None = None,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=task)
    log.write_input(task)
    task_id = run_id

    # --- Planner (once) ---
    planner_msg = run_agent(PLANNER, state, llm, task_id=task_id, run_id=run_id)
    state.agent_outputs["planner"].append(planner_msg.content)
    state.task_plan = list(planner_msg.content.get("steps", []))
    log.write_planner(planner_msg.content)
    printer(f"[planner] {planner_msg.content.get('summary', '')}")

    # --- Execute / Review / Evaluate loop ---
    total_attempts = max_revisions + 1
    for attempt in range(1, total_attempts + 1):
        executor_msg = run_agent(EXECUTOR, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["executor"].append(executor_msg.content)
        log.write_executor(executor_msg.content, attempt)
        printer(f"[executor #{attempt}] {executor_msg.content.get('notes', '') or 'artifact produced'}")

        reviewer_msg = run_agent(REVIEWER, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["reviewer"].append(reviewer_msg.content)
        state.reviews.append(reviewer_msg.content)
        log.write_reviewer(reviewer_msg.content)
        printer(f"[reviewer] {reviewer_msg.content.get('decision', '')}")

        evaluator_msg = run_agent(EVALUATOR, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["evaluator"].append(evaluator_msg.content)
        decision = evaluator_msg.content["decision"]
        state.decisions.append({"attempt": attempt, "decision": decision})
        log.write_evaluator(evaluator_msg.content)
        printer(f"[evaluator] {decision}")

        if decision == Decision.PASS.value:
            break
        if decision == Decision.BLOCKED.value:
            break
        # NEEDS_FIX: loop again if budget remains, else fall through to gate
        if attempt >= total_attempts:
            break

    # --- Human Gate ---
    feedback = human_gate(state, printer=printer)
    state.human_feedback = feedback
    final = _build_final(state)
    state.final_output = final
    log.write_final(final)
    log.write_state(state)
    printer(f"[human] {feedback.decision}")
    return state
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_orchestrator.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add supervisor orchestration loop with bounded revisions"
```

---

### Task 10: `cli.py` — `macr run` entrypoint

**Files:**
- Create: `macr/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from macr import cli
from macr.llm import FakeLLM
from macr.schemas import HumanFeedback


def _scripted_llm():
    return FakeLLM([
        {"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []},
        {"artifact": "done", "notes": "", "evidence": []},
        {"summary": "ok", "findings": [], "decision": "approve"},
        {"decision": "PASS", "reasons": ["good"], "confidence": 0.9},
    ])


def test_cli_run_approve_returns_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "build a thing", "--max-revisions", "2"],
        llm=_scripted_llm(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_cli_run_reject_returns_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "task"],
        llm=_scripted_llm(),
        human_gate=lambda state, **kw: HumanFeedback(decision="reject", feedback="no", timestamp="t"),
    )
    assert rc == 1


def test_cli_missing_api_key_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No injected llm -> cli must build AnthropicLLM, which needs a key
    rc = cli.main(["run", "task"])
    assert rc == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL (ModuleNotFoundError or AttributeError: cli.main).

- [ ] **Step 3: Implement `macr/cli.py`**

```python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from macr.human_gate import interactive_human_gate
from macr.llm import LLMError
from macr.orchestrator import run_task


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="macr", description="MACR multi-agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run one MACR task end-to-end")
    run_p.add_argument("task", help="the task description")
    run_p.add_argument("--max-revisions", type=int, default=2)
    run_p.add_argument("--model", default="claude-sonnet-4-6")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, llm=None, human_gate=interactive_human_gate) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        from macr.llm import AnthropicLLM

        llm = AnthropicLLM(model=args.model)

    runs_dir = Path(".macr/runs")
    try:
        state = run_task(
            args.task, llm, runs_dir,
            max_revisions=args.max_revisions, human_gate=human_gate,
        )
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface any failure as non-zero
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the FULL suite**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS (utils 4, schemas 10, runlog 2, llm 5, roles 8, agent 3, human_gate 3, orchestrator 5, cli 3, smoke 1).

- [ ] **Step 6: Commit**

```bash
git add macr/cli.py tests/test_cli.py
git commit -m "feat: add macr run CLI entrypoint with exit codes"
```

---

### Task 11: Smoke script + README usage

**Files:**
- Create: `scripts/smoke.py`
- Modify: `README.md` (append a "Running the CLI MVP (V1)" section)

This task is NOT covered by automated tests (it hits the real API). It is a manual verification aid.

- [ ] **Step 1: Create `scripts/smoke.py`**

```python
"""Manual smoke test against the real Anthropic API.

Usage:
    ANTHROPIC_API_KEY=... .venv/bin/python scripts/smoke.py
Requires a network connection and a valid key. Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "写一个 Python 函数,判断一个字符串是否为回文,并附简短说明。"
    raise SystemExit(main(["run", task]))
```

- [ ] **Step 2: Append usage docs to `README.md`**

Add this section at the end of `README.md` (keep all existing content above it):
```markdown

---

## 运行 CLI MVP (V1) / Running the CLI MVP

> 仅在项目专属虚拟环境中运行,不污染基础环境 / Project-local venv only.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 跑测试 / run tests (no network)
.venv/bin/pytest

# 真实运行一条任务 / run a real task (needs an API key)
export ANTHROPIC_API_KEY=sk-...
.venv/bin/macr run "写一个判断回文的 Python 函数"
```

产物写入 `.macr/runs/<run_id>/`:`input.md` / `planner.output.md` / `executor.output.md` / `reviewer.output.md` / `evaluator.output.json` / `state.json` / `final.md`。
```

- [ ] **Step 3: Verify the smoke script imports cleanly (no network)**

Run: `.venv/bin/python -c "import scripts.smoke" 2>/dev/null || .venv/bin/python -c "import ast; ast.parse(open('scripts/smoke.py').read()); print('parse ok')"`
Expected: prints `parse ok` (or imports cleanly). This only checks the file is valid Python; do NOT run it (it would hit the API).

- [ ] **Step 4: Confirm full suite still green**

Run: `.venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke.py README.md
git commit -m "docs: add real-API smoke script and CLI usage to README"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Spec §3 package structure → Tasks 1–10 create every listed module (utils added in Task 2 as a small, justified helper for deterministic timestamps/run-ids; spec §7 referenced sequential run_id which this implements).
- Spec §4 data model → Task 3 (all enums + role outputs + SharedState + HumanFeedback).
- Spec §5 orchestration loop incl. `max_revisions`, NEEDS_FIX/BLOCKED/exhausted → Task 9 (4 path tests).
- Spec §6 tool-use forced schema + one retry → Task 5 (AnthropicLLM `tool_choice`) + Task 7 (validate-and-retry).
- Spec §7 run-dir layout incl. `state.json` and executor revision history → Task 4.
- Spec §8 error handling → Task 7 (AgentError), Task 5 (LLMError), Task 10 (exit code 2).
- Spec §9 TDD with FakeLLM, no real API → every task uses FakeLLM/injection; Task 11 isolates the only real-API path as a manual script.
- Spec §10 CLI + exit codes + edit=approve-with-feedback → Task 10 (exit 0/1/2) + Task 8 (edit→approve+feedback).
- Spec §11 DoD → Task 10 Step 5 runs the full suite; Task 11 provides the real-API smoke path.

**Placeholder scan:** No TBD/TODO. Every code step contains complete, runnable code. The broad `except Exception` in `cli.main` is intentional (surface-any-failure-as-nonzero) and documented inline.

**Type/name consistency:** `run_agent(role, state, llm, *, task_id, run_id, timestamp=None)` signature identical in Tasks 7, 9. `RoleSpec` fields (`name/agent_id/tool_name/message_type/content_model/system_prompt/build_user`) defined in Task 6, consumed unchanged in Task 7. `RunLog` methods (`write_input/write_planner/write_executor(…, attempt)/write_reviewer/write_evaluator/write_final/write_state`) defined in Task 4, called identically in Task 9. `FakeLLM(responses)` and `call_role(*, system, user, tool_name, tool_schema)` consistent across Tasks 5,7,9,10. `Decision` compared by `.value` (strings) in orchestrator because `content` is a dumped dict — consistent with Task 3. Run-id `today=` param threaded through Tasks 2, 9, and tests. `human_gate(state, printer=...)` calling convention consistent between Task 8 signature and Task 9 call site (`**kwargs` in test doubles absorbs `printer`).
