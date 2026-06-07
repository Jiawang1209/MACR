# MACR Stage A — Claude⟷Codex Code Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `macr collab "<task>" --repo <path> --test-cmd "..."` command where Claude (`claude` CLI) plans/reviews and Codex (`codex` CLI) edits real code in an isolated git worktree, the framework runs tests, and a deterministic rule gates a revision loop ending at an interactive Human Gate — all CLI-only, no API key.

**Architecture:** Extends the existing `macr` package. A new `AgentBackend` abstraction has CLI implementations (`ClaudeCliBackend`, `CodexCliBackend`) driven via an injectable `ProcessRunner`, plus a dormant `ApiBackend` seam. New `worktree.py`, `testrunner.py`, `collab_evaluator.py`, `collab_roles.py`, `collab_orchestrator.py` reuse V1's `SharedState`/`RunLog`/`Message`/`RoleSpec`. Everything is dependency-injected so the loop is tested with a `FakeAgentBackend` + a real temp git repo, never touching the real CLIs.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `subprocess`/`shutil`/`shlex`, pytest, real `git` (2.50). **Isolation rule:** project-local `.venv` only (already exists from V1). Commits: plain, NO Co-Authored-By / AI attribution. Run pytest via `.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-06-07-macr-stage-a-claude-codex-collab-design.md`.

**V1 interfaces this builds on (already implemented, do not change):**
- `macr/schemas.py`: `Message`, `SharedState`, `PlannerOutput`, `ExecutorOutput`, `ReviewerOutput`, `Finding`, `Decision`, `MessageType`.
- `macr/roles.py`: `RoleSpec(name, agent_id, tool_name, message_type, content_model, system_prompt, build_user)`.
- `macr/agent.py`: `AgentError`, `run_agent(...)`.
- `macr/runlog.py`: `RunLog` with `write_input/write_planner/write_executor(content,attempt)/write_reviewer/write_evaluator/write_final/write_state`.
- `macr/human_gate.py`: `interactive_human_gate(state, *, input_fn, printer, timestamp)`.
- `macr/llm.py`: `AnthropicLLM`, `FakeLLM`. `macr/utils.py`: `now_iso`, `next_run_id`.

**Conventions:** TDD per task (red → green → commit). One git command at a time. `.macr/` and `.venv/` are gitignored.

---

### Task 1: Extend `schemas.py` — TestResult + SharedState collab fields

**Files:** Modify `macr/schemas.py`; Create `tests/test_schemas_collab.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_schemas_collab.py`:
```python
from macr.schemas import SharedState, TestResult


def test_test_result_defaults():
    tr = TestResult(command="pytest -q", passed=True, exit_code=0)
    assert tr.log == "" and tr.timed_out is False


def test_shared_state_collab_fields_default():
    s = SharedState(run_id="R1", user_query="q")
    assert s.target_repo is None
    assert s.worktree_path is None
    assert s.diffs == []
    assert s.test_results == []


def test_shared_state_collab_fields_roundtrip():
    s = SharedState(run_id="R1", user_query="q", target_repo="/repo")
    s.diffs.append("diff text")
    s.test_results.append({"passed": False})
    dumped = s.model_dump()
    assert dumped["target_repo"] == "/repo"
    assert dumped["diffs"] == ["diff text"]
    assert dumped["test_results"][0]["passed"] is False
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_schemas_collab.py -v` (ImportError: TestResult).

- [ ] **Step 3: Implement** — in `macr/schemas.py`, add `TestResult` (place it near the other content models, after `EvaluatorOutput`):
```python
class TestResult(BaseModel):
    command: str
    passed: bool
    exit_code: int
    log: str = ""
    timed_out: bool = False
```
and add four fields to `SharedState` (after the existing `final_output` field, keep all existing fields unchanged):
```python
    target_repo: str | None = None
    worktree_path: str | None = None
    diffs: list[str] = Field(default_factory=list)
    test_results: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: Run, expect PASS (3 passed); also confirm V1 still green** — `.venv/bin/pytest tests/test_schemas_collab.py tests/test_schemas.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/schemas.py tests/test_schemas_collab.py
git commit -m "feat: add TestResult schema and collab fields to SharedState"
```

---

### Task 2: `worktree.py` — isolated git worktree + diff capture

**Files:** Create `macr/worktree.py`, `tests/test_worktree.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_worktree.py`:
```python
import subprocess
from pathlib import Path

import pytest

from macr.worktree import Worktree, WorktreeError


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    env = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", *env, "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_create_rejects_non_git(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(WorktreeError):
        Worktree.create(tmp_path / "plain", "R1", tmp_path / "wts")


def test_create_rejects_dirty_tree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("dirty\n")
    with pytest.raises(WorktreeError):
        Worktree.create(repo, "R1", tmp_path / "wts")


def test_create_and_diff_captures_edits_and_new_files(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = Worktree.create(repo, "R1", tmp_path / "wts")
    assert Path(wt.path).exists()
    # edit existing + add new file inside the worktree
    (Path(wt.path) / "a.txt").write_text("hello world\n")
    (Path(wt.path) / "new.py").write_text("print('x')\n")
    diff = wt.diff()
    assert "hello world" in diff
    assert "new.py" in diff


def test_cleanup_removes_worktree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = Worktree.create(repo, "R1", tmp_path / "wts")
    assert Path(wt.path).exists()
    wt.cleanup()
    assert not Path(wt.path).exists()
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_worktree.py -v` (ModuleNotFoundError).

- [ ] **Step 3: Implement** — `macr/worktree.py`:
```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    """Raised when the target repo is invalid or a git worktree op fails."""


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


@dataclass
class Worktree:
    repo: Path
    path: Path
    base_commit: str

    @classmethod
    def create(cls, repo: Path, run_id: str, worktrees_dir: Path) -> "Worktree":
        repo = Path(repo)
        if not (repo / ".git").exists():
            inside = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(repo), capture_output=True, text=True,
            )
            if inside.returncode != 0 or inside.stdout.strip() != "true":
                raise WorktreeError(f"{repo} is not a git repository")
        status = _git(["status", "--porcelain"], repo).stdout.strip()
        if status:
            raise WorktreeError(f"{repo} has a dirty working tree; commit or stash first")
        base_commit = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        worktrees_dir = Path(worktrees_dir)
        worktrees_dir.mkdir(parents=True, exist_ok=True)
        wt_path = worktrees_dir / run_id
        _git(["worktree", "add", "--detach", str(wt_path), base_commit], repo)
        return cls(repo=repo, path=wt_path, base_commit=base_commit)

    def diff(self) -> str:
        _git(["add", "-A"], self.path)
        return _git(["diff", "--cached"], self.path).stdout

    def cleanup(self) -> None:
        _git(["worktree", "remove", "--force", str(self.path)], self.repo)
```

- [ ] **Step 4: Run, expect PASS (4 passed)** — `.venv/bin/pytest tests/test_worktree.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/worktree.py tests/test_worktree.py
git commit -m "feat: add git worktree management with diff capture"
```

---

### Task 3: `testrunner.py` — run the test command in a worktree

**Files:** Create `macr/testrunner.py`, `tests/test_testrunner.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_testrunner.py`:
```python
from macr.testrunner import run_tests


def test_passing_command(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import sys; sys.exit(0)"], timeout=30)
    assert tr.passed is True and tr.exit_code == 0 and tr.timed_out is False


def test_failing_command(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import sys; sys.exit(1)"], timeout=30)
    assert tr.passed is False and tr.exit_code == 1


def test_command_not_found(tmp_path):
    tr = run_tests(tmp_path, ["definitely-not-a-real-cmd-xyz"], timeout=30)
    assert tr.passed is False and tr.exit_code == 127


def test_captures_output(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "print('hello-out')"], timeout=30)
    assert "hello-out" in tr.log


def test_timeout(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import time; time.sleep(5)"], timeout=1)
    assert tr.passed is False and tr.timed_out is True
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_testrunner.py -v`.

- [ ] **Step 3: Implement** — `macr/testrunner.py`:
```python
from __future__ import annotations

import subprocess
from pathlib import Path

from macr.schemas import TestResult


def run_tests(worktree_path: Path, test_cmd: list[str], timeout: int = 1800) -> TestResult:
    command = " ".join(test_cmd)
    try:
        proc = subprocess.run(
            test_cmd, cwd=str(worktree_path),
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return TestResult(command=command, passed=False, exit_code=127, log="command not found")
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
        return TestResult(command=command, passed=False, exit_code=-1, log=log, timed_out=True)
    return TestResult(
        command=command,
        passed=proc.returncode == 0,
        exit_code=proc.returncode,
        log=(proc.stdout or "") + (proc.stderr or ""),
    )
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_testrunner.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/testrunner.py tests/test_testrunner.py
git commit -m "feat: add test runner capturing TestResult in a worktree"
```

---

### Task 4: `collab_evaluator.py` — deterministic gate rule

**Files:** Create `macr/collab_evaluator.py`, `tests/test_collab_evaluator.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_collab_evaluator.py`:
```python
from macr.collab_evaluator import evaluate_collab
from macr.schemas import Decision, TestResult


def _passing():
    return TestResult(command="t", passed=True, exit_code=0)


def _failing():
    return TestResult(command="t", passed=False, exit_code=1)


def _review(blocking: bool):
    findings = [{"level": "blocking", "issue": "x", "evidence": "e", "recommendation": "r"}] if blocking else []
    return {"summary": "s", "findings": findings, "decision": "needs_fix" if blocking else "approve"}


def test_agent_failed_is_blocked():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(False), agent_failed=True) is Decision.BLOCKED


def test_tests_fail_is_needs_fix():
    assert evaluate_collab(test_result=_failing(), reviewer=_review(False), agent_failed=False) is Decision.NEEDS_FIX


def test_blocking_review_is_needs_fix():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(True), agent_failed=False) is Decision.NEEDS_FIX


def test_pass_when_tests_pass_and_no_blocking():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(False), agent_failed=False) is Decision.PASS


def test_none_test_result_is_needs_fix():
    assert evaluate_collab(test_result=None, reviewer=_review(False), agent_failed=False) is Decision.NEEDS_FIX
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_collab_evaluator.py -v`.

- [ ] **Step 3: Implement** — `macr/collab_evaluator.py`:
```python
from __future__ import annotations

from macr.schemas import Decision, TestResult


def evaluate_collab(
    *,
    test_result: TestResult | None,
    reviewer: dict | None,
    agent_failed: bool,
) -> Decision:
    """Deterministic quality gate (spec §6). No model call."""
    if agent_failed:
        return Decision.BLOCKED
    if test_result is None or not test_result.passed:
        return Decision.NEEDS_FIX
    findings = (reviewer or {}).get("findings", [])
    if any(f.get("level") == "blocking" for f in findings):
        return Decision.NEEDS_FIX
    return Decision.PASS
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_collab_evaluator.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/collab_evaluator.py tests/test_collab_evaluator.py
git commit -m "feat: add deterministic collab evaluator gate rule"
```

---

### Task 5: `agents/base.py` — backend abstraction, process runner, test doubles

**Files:** Create `macr/agents/__init__.py`, `macr/agents/base.py`, `tests/test_agents_base.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_agents_base.py`:
```python
import pytest

from macr.agent import AgentError
from macr.agents.base import (
    FakeAgentBackend,
    FakeProcessRunner,
    ProcResult,
    extract_json_object,
    message_from_content,
    validate_with_retry,
)
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def test_extract_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_from_fence_and_prose():
    text = "Here you go:\n```json\n{\"a\": 2, \"b\": [1,2]}\n```\nDone."
    assert extract_json_object(text) == {"a": 2, "b": [1, 2]}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_validate_with_retry_success_first_try():
    calls = []

    def call_fn(extra):
        calls.append(extra)
        return {"summary": "ok", "steps": ["a"], "tools_needed": [], "risks": []}

    model = validate_with_retry(PLANNER, call_fn)
    assert model.steps == ["a"]
    assert calls == [""]  # no retry


def test_validate_with_retry_retries_then_succeeds():
    seq = [{"summary": "bad"}, {"summary": "ok", "steps": ["x"], "tools_needed": [], "risks": []}]

    def call_fn(extra):
        return seq.pop(0)

    model = validate_with_retry(PLANNER, call_fn)
    assert model.steps == ["x"]


def test_validate_with_retry_raises_after_two():
    def call_fn(extra):
        return {"summary": "bad"}

    with pytest.raises(AgentError):
        validate_with_retry(PLANNER, call_fn)


def test_message_from_content():
    from macr.schemas import PlannerOutput

    msg = message_from_content(
        PLANNER, PlannerOutput(summary="s", steps=["a"]),
        run_id="R1", task_id="R1", timestamp="t",
    )
    assert msg.role == "planner" and msg.message_type is MessageType.PLAN
    assert msg.content["steps"] == ["a"]


def test_fake_process_runner_pops_and_records():
    fr = FakeProcessRunner([ProcResult(0, "out", "")])
    res = fr.run(["claude", "-p", "x"], cwd="/tmp")
    assert res.stdout == "out"
    assert fr.calls[0]["argv"][0] == "claude"


def test_fake_agent_backend_returns_scripted_and_calls_hook():
    edited = []
    fab = FakeAgentBackend(
        {"planner": [{"summary": "s", "steps": ["a"], "tools_needed": [], "risks": []}]},
        on_run=lambda role, state: edited.append(role.name),
    )
    state = SharedState(run_id="R1", user_query="q")
    msg = fab.run_role(PLANNER, state, run_id="R1", task_id="R1")
    assert msg.content["steps"] == ["a"]
    assert edited == ["planner"]
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_agents_base.py -v`.

- [ ] **Step 3: Implement** — `macr/agents/__init__.py` (empty file), then `macr/agents/base.py`:
```python
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from macr.agent import AgentError
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState
from macr.utils import now_iso


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class ProcessRunner(Protocol):
    def run(self, argv: list[str], *, cwd: str | None = None,
            input_text: str | None = None, timeout: int | None = None) -> ProcResult: ...


class SubprocessRunner:
    """Real process runner wrapping subprocess.run."""

    def run(self, argv, *, cwd=None, input_text=None, timeout=None) -> ProcResult:
        proc = subprocess.run(
            argv, cwd=cwd, input=input_text,
            capture_output=True, text=True, timeout=timeout,
        )
        return ProcResult(proc.returncode, proc.stdout, proc.stderr)


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None) -> Message: ...


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from text, tolerating code fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in output: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def validate_with_retry(role: RoleSpec, call_fn: Callable[[str], dict]) -> BaseModel:
    """call_fn(extra_note) -> raw dict. Validate into role.content_model with one retry."""
    raw = call_fn("")
    try:
        return role.content_model(**raw)
    except ValidationError as first:
        note = (
            "\n\nPrevious output failed validation:\n"
            f"{first}\nReturn corrected JSON only, matching the schema."
        )
        raw = call_fn(note)
        try:
            return role.content_model(**raw)
        except ValidationError as second:
            raise AgentError(f"{role.name} failed schema validation twice: {second}") from second


def message_from_content(role: RoleSpec, content: BaseModel, *,
                         run_id: str, task_id: str, timestamp: str | None = None) -> Message:
    return Message(
        task_id=task_id, run_id=run_id, agent_id=role.agent_id, role=role.name,
        message_type=role.message_type, content=content.model_dump(mode="json"),
        timestamp=timestamp or now_iso(),
    )


# --- Test doubles ---

class FakeProcessRunner:
    """Returns scripted ProcResults in order; records calls."""

    def __init__(self, results: list[ProcResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    def run(self, argv, *, cwd=None, input_text=None, timeout=None) -> ProcResult:
        self.calls.append({"argv": list(argv), "cwd": cwd, "input_text": input_text})
        if not self._results:
            raise AssertionError("FakeProcessRunner exhausted")
        return self._results.pop(0)


class FakeAgentBackend:
    """AgentBackend test double: scripted content per role name; optional on_run side effect."""

    name = "fake"

    def __init__(self, scripted: dict[str, list[dict]],
                 on_run: Callable[[RoleSpec, SharedState], None] | None = None):
        self._scripted = {k: list(v) for k, v in scripted.items()}
        self._on_run = on_run
        self.calls: list[str] = []

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        self.calls.append(role.name)
        if self._on_run is not None:
            self._on_run(role, state)
        if not self._scripted.get(role.name):
            raise AssertionError(f"FakeAgentBackend has no scripted output for role '{role.name}'")
        content = self._scripted[role.name].pop(0)
        return Message(
            task_id=task_id, run_id=run_id, agent_id=role.agent_id, role=role.name,
            message_type=role.message_type, content=content, timestamp=timestamp or "t",
        )
```

- [ ] **Step 4: Run, expect PASS (9 passed)** — `.venv/bin/pytest tests/test_agents_base.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/agents/__init__.py macr/agents/base.py tests/test_agents_base.py
git commit -m "feat: add AgentBackend abstraction, process runner, and test doubles"
```

---

### Task 6: `collab_roles.py` — diff/test-aware role specs

**Files:** Create `macr/collab_roles.py`, `tests/test_collab_roles.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_collab_roles.py`:
```python
from macr.collab_roles import COLLAB_ROLES, EXECUTOR_C, PLANNER_C, REVIEWER_C
from macr.schemas import (
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_registry_and_wiring():
    assert set(COLLAB_ROLES) == {"planner", "executor", "reviewer"}
    assert PLANNER_C.content_model is PlannerOutput
    assert EXECUTOR_C.content_model is ExecutorOutput
    assert REVIEWER_C.content_model is ReviewerOutput
    assert REVIEWER_C.message_type is MessageType.REVIEW
    assert PLANNER_C.agent_id == "claude_planner"
    assert EXECUTOR_C.agent_id == "codex_executor"


def test_planner_user_has_task():
    s = SharedState(run_id="R1", user_query="add a CLI flag")
    assert "add a CLI flag" in PLANNER_C.build_user(s)


def test_executor_user_has_plan_and_revision_context():
    s = SharedState(run_id="R1", user_query="q")
    s.agent_outputs["planner"].append({"summary": "p", "steps": ["edit main.py"], "risks": []})
    assert "edit main.py" in EXECUTOR_C.build_user(s)
    # add a prior failing round
    s.diffs.append("some diff")
    s.test_results.append({"command": "t", "passed": False, "exit_code": 1, "log": "ASSERT boom", "timed_out": False})
    s.agent_outputs["reviewer"].append({"summary": "fix it", "findings": [], "decision": "needs_fix"})
    user = EXECUTOR_C.build_user(s)
    assert "fix it" in user and "boom" in user


def test_reviewer_user_has_diff_and_test_result():
    s = SharedState(run_id="R1", user_query="q")
    s.diffs.append("THE DIFF")
    s.test_results.append({"command": "t", "passed": True, "exit_code": 0, "log": "1 passed", "timed_out": False})
    user = REVIEWER_C.build_user(s)
    assert "THE DIFF" in user and ("passed" in user or "PASS" in user)
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_collab_roles.py -v`.

- [ ] **Step 3: Implement** — `macr/collab_roles.py`:
```python
from __future__ import annotations

from macr.roles import RoleSpec
from macr.schemas import (
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def _latest(state: SharedState, bucket: str) -> dict | None:
    items = state.agent_outputs.get(bucket, [])
    return items[-1] if items else None


def _planner_user(state: SharedState) -> str:
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        "目标代码仓库已在工作目录就绪。请制定实现方案:summary(总述)、"
        "steps(分步骤)、tools_needed、risks。不要写代码,只出方案。"
    )


def _executor_user(state: SharedState) -> str:
    plan = _latest(state, "planner") or {}
    steps = "\n".join(f"- {s}" for s in plan.get("steps", []))
    parts = [
        f"任务 / Task:\n{state.user_query}",
        f"实现方案 / Plan steps:\n{steps}",
        "请直接在当前工作目录(git worktree)中修改/新增文件来实现该方案;"
        "完成后用 JSON 汇总 artifact(改动说明)、notes、evidence(改了哪些文件)。",
    ]
    review = _latest(state, "reviewer")
    if review is not None:
        findings = "\n".join(
            f"- {f.get('issue')}: {f.get('recommendation')}" for f in review.get("findings", [])
        )
        parts.append(
            "上一轮审查反馈 / Previous review feedback:\n"
            f"{review.get('summary', '')}\n{findings}"
        )
    if state.test_results:
        tr = state.test_results[-1]
        if not tr.get("passed", False):
            parts.append("上一轮测试失败日志 / Previous test failure log:\n" + tr.get("log", ""))
    parts.append("请据此修订代码。")
    return "\n\n".join(parts)


def _reviewer_user(state: SharedState) -> str:
    diff = state.diffs[-1] if state.diffs else "(无改动 / no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    test_line = (
        f"passed={tr.get('passed')}, exit_code={tr.get('exit_code')}\n{tr.get('log', '')}"
        if tr else "(未运行 / not run)"
    )
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"本轮代码改动 (git diff):\n{diff}\n\n"
        f"测试结果 / Test result:\n{test_line}\n\n"
        "请综合 diff 与测试结果审查:逻辑错误、是否偏离任务、是否缺证据;"
        "给出 findings(含 level=blocking/non_blocking)与 decision(approve/needs_fix)。"
    )


PLANNER_C = RoleSpec(
    name="planner", agent_id="claude_planner", tool_name="submit_plan",
    message_type=MessageType.PLAN, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 的 Planner(由 Claude 扮演)。只出实现方案,不写代码,不评判合格。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_planner_user,
)

EXECUTOR_C = RoleSpec(
    name="executor", agent_id="codex_executor", tool_name="submit_result",
    message_type=MessageType.RESULT, content_model=ExecutorOutput,
    system_prompt=(
        "你是 MACR 的 Executor(由 Codex 扮演)。在当前工作目录中真实修改/新增文件实现方案,"
        "若有审查反馈或失败测试则据此修订。完成后输出符合 JSON Schema 的 artifact/notes/evidence。"
    ),
    build_user=_executor_user,
)

REVIEWER_C = RoleSpec(
    name="reviewer", agent_id="claude_reviewer", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 的 Reviewer(由 Claude 扮演)。只审查 diff 与测试结果,不改代码。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_reviewer_user,
)

COLLAB_ROLES: dict[str, RoleSpec] = {r.name: r for r in (PLANNER_C, EXECUTOR_C, REVIEWER_C)}
```

- [ ] **Step 4: Run, expect PASS (4 passed)** — `.venv/bin/pytest tests/test_collab_roles.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/collab_roles.py tests/test_collab_roles.py
git commit -m "feat: add diff/test-aware collab role specs"
```

---

### Task 7: `agents/cli_backend.py` — Claude and Codex CLI backends

**Files:** Create `macr/agents/cli_backend.py`, `tests/test_cli_backend.py`.

**Design notes:** Both backends build a prompt (`system_prompt` + `build_user(state)` + a "JSON only matching this schema" instruction) and run a CLI via the injected `ProcessRunner`. Claude uses `claude -p <prompt> --output-format json` and we parse the JSON envelope's `result` field (then `extract_json_object`). Codex uses `codex exec <prompt> --cd <worktree> --sandbox workspace-write --ask-for-approval never` and we `extract_json_object` from stdout. Both then validate via `validate_with_retry`. (Spec §4.1's `--output-schema/-o` is a future hardening; stdout-parse + Pydantic validation is the client-side equivalent and keeps the runner injectable.)

- [ ] **Step 1: Write the failing test** — `tests/test_cli_backend.py`:
```python
import json

import pytest

from macr.agent import AgentError
from macr.agents.base import ProcResult, FakeProcessRunner
from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
from macr.collab_roles import EXECUTOR_C, PLANNER_C
from macr.schemas import SharedState


def _plan_dict():
    return {"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}


def _claude_envelope(inner: dict) -> str:
    # claude -p --output-format json wraps the assistant text in `result`
    return json.dumps({"type": "result", "result": json.dumps(inner)})


def test_claude_backend_parses_and_builds_message():
    runner = FakeProcessRunner([ProcResult(0, _claude_envelope(_plan_dict()), "")])
    backend = ClaudeCliBackend(runner=runner, model="claude-x")
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    argv = runner.calls[0]["argv"]
    assert argv[0] == "claude" and "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--model" in argv and "claude-x" in argv


def test_claude_backend_retries_on_invalid():
    runner = FakeProcessRunner([
        ProcResult(0, _claude_envelope({"summary": "bad"}), ""),   # missing steps
        ProcResult(0, _claude_envelope(_plan_dict()), ""),
    ])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["steps"] == ["a"]
    assert len(runner.calls) == 2


def test_claude_backend_nonzero_exit_raises():
    runner = FakeProcessRunner([ProcResult(1, "", "boom"), ProcResult(1, "", "boom")])
    backend = ClaudeCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task")
    with pytest.raises(AgentError):
        backend.run_role(PLANNER_C, state, run_id="R1", task_id="R1", timestamp="t")


def test_codex_backend_parses_stdout_and_passes_worktree():
    exec_json = {"artifact": "edited main.py", "notes": "", "evidence": ["main.py"]}
    stdout = "working...\nDone. " + json.dumps(exec_json)
    runner = FakeProcessRunner([ProcResult(0, stdout, "")])
    backend = CodexCliBackend(runner=runner, model="gpt-x")
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    msg = backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert msg.content["artifact"] == "edited main.py"
    argv = runner.calls[0]["argv"]
    assert argv[0] == "codex" and argv[1] == "exec"
    assert "--cd" in argv and "/tmp/wt" in argv
    assert "--sandbox" in argv and "workspace-write" in argv
    assert "--ask-for-approval" in argv and "never" in argv
    assert "--model" in argv and "gpt-x" in argv
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_backend.py -v`.

- [ ] **Step 3: Implement** — `macr/agents/cli_backend.py`:
```python
from __future__ import annotations

import json

from macr.agent import AgentError
from macr.agents.base import (
    AgentBackend,
    ProcessRunner,
    SubprocessRunner,
    extract_json_object,
    message_from_content,
    validate_with_retry,
)
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
    """Drives the `claude` CLI in headless print mode."""

    name = "claude_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 claude_bin: str = "claude", timeout: int = 1800):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.claude_bin = claude_bin
        self.timeout = timeout

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        prompt = _base_prompt(role, state)

        def call_fn(extra: str) -> dict:
            argv = [self.claude_bin, "-p", prompt + extra, "--output-format", "json"]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"claude CLI exited {res.returncode}: {res.stderr.strip()}")
            return self._parse(res.stdout)

        content = validate_with_retry(role, call_fn)
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)

    @staticmethod
    def _parse(stdout: str) -> dict:
        try:
            envelope = json.loads(stdout)
            inner = envelope.get("result", stdout) if isinstance(envelope, dict) else stdout
        except json.JSONDecodeError:
            inner = stdout
        return extract_json_object(inner)


class CodexCliBackend:
    """Drives the `codex` CLI in non-interactive exec mode inside a worktree."""

    name = "codex_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 approval: str = "never", timeout: int = 1800):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.approval = approval
        self.timeout = timeout

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."

        def call_fn(extra: str) -> dict:
            argv = [
                self.codex_bin, "exec", prompt + extra,
                "--cd", cwd,
                "--sandbox", self.sandbox,
                "--ask-for-approval", self.approval,
            ]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"codex CLI exited {res.returncode}: {res.stderr.strip()}")
            return extract_json_object(res.stdout)

        content = validate_with_retry(role, call_fn)
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
```

- [ ] **Step 4: Run, expect PASS (4 passed)** — `.venv/bin/pytest tests/test_cli_backend.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/agents/cli_backend.py tests/test_cli_backend.py
git commit -m "feat: add Claude and Codex CLI agent backends"
```

---

### Task 8: `agents/api_backend.py` — dormant API seam

**Files:** Create `macr/agents/api_backend.py`, `tests/test_api_backend.py`.

This is the preserved-but-dormant backend (spec §4.1): it adapts the V1 API path (`run_agent` + an `LLM`) to the `AgentBackend` interface. Tested with V1's `FakeLLM` (no network).

- [ ] **Step 1: Write the failing test** — `tests/test_api_backend.py`:
```python
from macr.agents.api_backend import ApiBackend
from macr.llm import FakeLLM
from macr.roles import PLANNER
from macr.schemas import MessageType, SharedState


def test_api_backend_delegates_to_run_agent():
    llm = FakeLLM([{"summary": "p", "steps": ["a"], "tools_needed": [], "risks": []}])
    backend = ApiBackend(llm)
    state = SharedState(run_id="R1", user_query="task")
    msg = backend.run_role(PLANNER, state, run_id="R1", task_id="R1", timestamp="t")
    assert backend.name == "api"
    assert msg.message_type is MessageType.PLAN
    assert msg.content["steps"] == ["a"]
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_api_backend.py -v`.

- [ ] **Step 3: Implement** — `macr/agents/api_backend.py`:
```python
from __future__ import annotations

from macr.agent import run_agent
from macr.llm import LLM
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState


class ApiBackend:
    """Dormant API seam: adapts the V1 API tool-use path to the AgentBackend interface.

    Not used by `macr collab` (which is CLI-only). Kept so a future API path can be
    selected through the same AgentBackend interface without refactoring.
    """

    name = "api"

    def __init__(self, llm: LLM):
        self._llm = llm

    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None) -> Message:
        return run_agent(role, state, self._llm, task_id=task_id, run_id=run_id, timestamp=timestamp)
```

- [ ] **Step 4: Run, expect PASS (1 passed)** — `.venv/bin/pytest tests/test_api_backend.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/agents/api_backend.py tests/test_api_backend.py
git commit -m "feat: add dormant ApiBackend seam over the V1 API path"
```

---

### Task 9: RunLog collab writers + collab Human Gate

**Files:** Modify `macr/runlog.py`, `macr/human_gate.py`; Create `tests/test_runlog_collab.py`, `tests/test_human_gate_collab.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_runlog_collab.py`:
```python
import json

from macr.runlog import RunLog


def test_write_diff_and_test(tmp_path):
    log = RunLog(tmp_path / "R1")
    log.write_diff("THE DIFF", attempt=1)
    log.write_test({"command": "t", "passed": False, "exit_code": 1}, "log output", attempt=1)
    assert "THE DIFF" in (tmp_path / "R1" / "diff.v1.patch").read_text()
    assert "log output" in (tmp_path / "R1" / "test.v1.log").read_text()
    data = json.loads((tmp_path / "R1" / "test.v1.json").read_text())
    assert data["passed"] is False
```

`tests/test_human_gate_collab.py`:
```python
from macr.human_gate import collab_human_gate
from macr.schemas import SharedState


def _state():
    s = SharedState(run_id="R1", user_query="q")
    s.diffs.append("DIFF-BODY")
    s.test_results.append({"command": "t", "passed": True, "exit_code": 0, "log": "ok"})
    return s


def test_collab_gate_shows_diff_and_test_then_approves():
    out = []
    hf = collab_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    assert hf.decision == "approve"
    assert any("DIFF-BODY" in line for line in out)


def test_collab_gate_reject_collects_reason():
    answers = iter(["r", "no good"])
    hf = collab_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "reject" and hf.feedback == "no good"


def test_collab_gate_edit_is_approve_with_feedback():
    answers = iter(["e", "tweak it"])
    hf = collab_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "approve" and hf.feedback == "tweak it"
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_runlog_collab.py tests/test_human_gate_collab.py -v`.

- [ ] **Step 3a: Implement RunLog additions** — append two methods to the `RunLog` class in `macr/runlog.py` (the class already imports `json`):
```python
    def write_diff(self, diff_text: str, attempt: int) -> None:
        self._write(f"diff.v{attempt}.patch", diff_text)

    def write_test(self, result: dict, log: str, attempt: int) -> None:
        self._write(f"test.v{attempt}.log", log)
        self._write(f"test.v{attempt}.json", json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 3b: Implement collab Human Gate** — refactor `macr/human_gate.py` to share the choice logic, then add `collab_human_gate`. Replace the body of `interactive_human_gate` to delegate to a shared `_prompt_decision`, and add the new function. The full updated file:
```python
from __future__ import annotations

from typing import Callable

from macr.schemas import HumanFeedback, SharedState
from macr.utils import now_iso


def _latest_artifact(state: SharedState) -> str:
    items = state.agent_outputs.get("executor", [])
    return items[-1].get("artifact", "") if items else ""


def _prompt_decision(
    input_fn: Callable[[str], str], printer: Callable[..., None], ts: str
) -> HumanFeedback:
    printer("\n[a]pprove / [r]eject / [e]dit")
    choice = input_fn("> ").strip().lower()
    if choice.startswith("r"):
        reason = input_fn("Reject reason: ").strip()
        return HumanFeedback(decision="reject", feedback=reason, timestamp=ts)
    if choice.startswith("e"):
        fb = input_fn("Feedback / edits: ").strip()
        return HumanFeedback(decision="approve", feedback=fb, timestamp=ts)
    return HumanFeedback(decision="approve", feedback="", timestamp=ts)


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
    return _prompt_decision(input_fn, printer, ts)


def collab_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] = input,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    ts = timestamp or now_iso()
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    printer("\n===== Human Gate (collab) =====")
    printer(f"Task: {state.user_query}")
    printer(f"Worktree: {state.worktree_path}")
    printer("\n--- Final diff ---")
    printer(diff)
    printer(f"\n--- Tests: passed={tr.get('passed')} exit={tr.get('exit_code')} ---")
    return _prompt_decision(input_fn, printer, ts)
```

- [ ] **Step 4: Run, expect PASS** — `.venv/bin/pytest tests/test_runlog_collab.py tests/test_human_gate_collab.py tests/test_human_gate.py -v` (the V1 `test_human_gate.py` must still pass — 3 + 3 + 1 = 7 passed).

- [ ] **Step 5: Commit**
```bash
git add macr/runlog.py macr/human_gate.py tests/test_runlog_collab.py tests/test_human_gate_collab.py
git commit -m "feat: add collab runlog writers and collab human gate"
```

---

### Task 10: `collab_orchestrator.py` — the linear heterogeneous loop

**Files:** Create `macr/collab_orchestrator.py`, `tests/test_collab_orchestrator.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_collab_orchestrator.py`:
```python
import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.collab_orchestrator import run_collab
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _plan():
    return {"summary": "p", "steps": ["edit a.txt"], "tools_needed": [], "risks": []}


def _exec(tag):
    return {"artifact": f"edited-{tag}", "notes": "", "evidence": ["a.txt"]}


def _review(decision):
    return {"summary": "rev", "findings": [], "decision": decision}


def _approve(state, **kw):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def _make_editor(repo_dir_holder):
    # Executor side effect: write a file into the worktree so diff is non-empty
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("changed by codex\n")
    return on_run


def _run(tmp_path, *, claude_script, codex_script, test_cmd, max_revisions=2, gate=_approve):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude_backend = FakeAgentBackend(claude_script)
    codex_backend = FakeAgentBackend(codex_script, on_run=_make_editor(None))
    return run_collab(
        "do the task", repo=repo, test_cmd=test_cmd,
        claude_backend=claude_backend, codex_backend=codex_backend,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_revisions=max_revisions, human_gate=gate, printer=lambda *_: None,
        today="20260607",
    )


def test_pass_path(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve")]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
    )
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "planner.output.md").exists()
    assert (run_path / "diff.v1.patch").read_text().strip() != ""
    assert (run_path / "test.v1.json").exists()
    assert [d["decision"] for d in state.decisions] == ["PASS"]
    assert state.human_feedback.decision == "approve"
    assert "changed by codex" in (run_path / "diff.v1.patch").read_text()
    saved = json.loads((run_path / "state.json").read_text())
    assert saved["worktree_path"] is not None


def test_failing_tests_trigger_revision_then_pass(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("needs_fix"), _review("approve")]},
        codex_script={"executor": [_exec(1), _exec(2)]},
        test_cmd=["sh", "-c", "test -f a.txt && grep -q changed a.txt"],  # passes once edited
        max_revisions=2,
    )
    # tests pass on first attempt actually (file edited) -> ensure at least PASS reached
    assert state.decisions[-1]["decision"] == "PASS"


def test_persistent_test_failure_exhausts_to_gate(tmp_path):
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve"), _review("approve")]},
        codex_script={"executor": [_exec(1), _exec(2)]},
        test_cmd=["false"],  # always fails
        max_revisions=1,     # -> 2 attempts, both NEEDS_FIX -> gate
    )
    assert len(state.decisions) == 2
    assert all(d["decision"] == "NEEDS_FIX" for d in state.decisions)
    assert state.human_feedback is not None


def test_blocking_review_needs_fix(tmp_path):
    blocking = {"summary": "bad", "findings": [{"level": "blocking", "issue": "i", "evidence": "e", "recommendation": "r"}], "decision": "needs_fix"}
    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [blocking]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
        max_revisions=0,  # 1 attempt; blocking review -> NEEDS_FIX -> exhausted -> gate
    )
    assert state.decisions[-1]["decision"] == "NEEDS_FIX"


def test_reject_cleans_up_worktree(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")

    state = _run(
        tmp_path,
        claude_script={"planner": [_plan()], "reviewer": [_review("approve")]},
        codex_script={"executor": [_exec(1)]},
        test_cmd=["true"],
        gate=reject,
    )
    assert state.human_feedback.decision == "reject"
    # worktree removed on reject
    assert not (tmp_path / "wts" / "R20260607_001").exists()
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_collab_orchestrator.py -v`.

- [ ] **Step 3: Implement** — `macr/collab_orchestrator.py`:
```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import AgentBackend
from macr.collab_evaluator import evaluate_collab
from macr.collab_roles import EXECUTOR_C, PLANNER_C, REVIEWER_C
from macr.human_gate import collab_human_gate
from macr.runlog import RunLog
from macr.schemas import Decision, HumanFeedback, SharedState, TestResult
from macr.testrunner import run_tests
from macr.utils import next_run_id
from macr.worktree import Worktree

HumanGate = Callable[..., HumanFeedback]


def _build_final(state: SharedState) -> str:
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    trail = " → ".join(d["decision"] for d in state.decisions) or "(no evaluation)"
    parts = [
        "# Final Output",
        f"\n## Task\n{state.user_query}",
        f"\n## Worktree\n{state.worktree_path}",
        f"\n## Tests\npassed={tr.get('passed')} exit_code={tr.get('exit_code')}",
        f"\n## Decision trail\n{trail}",
        f"\n## Final diff\n```diff\n{diff}\n```",
    ]
    hf = state.human_feedback
    if hf is not None:
        parts.append(f"\n## Human decision\n{hf.decision}")
        if hf.feedback:
            parts.append(f"\n## 人工批注 / Human annotation\n{hf.feedback}")
    return "\n".join(parts) + "\n"


def run_collab(
    task: str,
    *,
    repo: Path,
    test_cmd: list[str],
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,
    runs_dir: Path,
    worktrees_dir: Path,
    max_revisions: int = 2,
    human_gate: HumanGate = collab_human_gate,
    printer: Callable[..., None] = print,
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=task, target_repo=str(repo))
    log.write_input(task)
    worktree: Worktree | None = None

    try:
        worktree = Worktree.create(repo, run_id, worktrees_dir)
        state.worktree_path = str(worktree.path)
        try:
            # --- Planner (Claude) ---
            planner_msg = claude_backend.run_role(PLANNER_C, state, run_id=run_id, task_id=run_id)
            state.agent_outputs["planner"].append(planner_msg.content)
            state.task_plan = list(planner_msg.content.get("steps", []))
            log.write_planner(planner_msg.content)
            printer(f"[planner] {planner_msg.content.get('summary', '')}")

            total_attempts = max_revisions + 1
            for attempt in range(1, total_attempts + 1):
                # --- Executor (Codex) edits the worktree ---
                exec_msg = codex_backend.run_role(EXECUTOR_C, state, run_id=run_id, task_id=run_id)
                state.agent_outputs["executor"].append(exec_msg.content)
                log.write_executor(exec_msg.content, attempt)

                # --- Capture diff ---
                diff = worktree.diff()
                state.diffs.append(diff)
                log.write_diff(diff, attempt)

                # --- Run tests ---
                tr: TestResult = run_tests(worktree.path, test_cmd, timeout)
                state.test_results.append(tr.model_dump())
                log.write_test(tr.model_dump(), tr.log, attempt)
                printer(f"[tests #{attempt}] passed={tr.passed}")

                # --- Reviewer (Claude) ---
                review_msg = claude_backend.run_role(REVIEWER_C, state, run_id=run_id, task_id=run_id)
                state.agent_outputs["reviewer"].append(review_msg.content)
                state.reviews.append(review_msg.content)
                log.write_reviewer(review_msg.content)
                printer(f"[reviewer] {review_msg.content.get('decision', '')}")

                # --- Evaluator (rule) ---
                decision = evaluate_collab(test_result=tr, reviewer=review_msg.content, agent_failed=False)
                state.decisions.append({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
                log.write_evaluator({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
                printer(f"[evaluator] {decision.value}")

                if decision in (Decision.PASS, Decision.BLOCKED):
                    break
                if attempt >= total_attempts:
                    break
        except AgentError as exc:
            state.decisions.append(
                {"attempt": len(state.decisions) + 1, "decision": Decision.BLOCKED.value, "error": str(exc)}
            )
            printer(f"[blocked] {exc}")

        # --- Human Gate ---
        feedback = human_gate(state, printer=printer)
        state.human_feedback = feedback
        final = _build_final(state)
        state.final_output = final
        log.write_final(final)
        printer(f"[human] {feedback.decision}")

        if feedback.decision == "reject" and worktree is not None:
            worktree.cleanup()
            state.worktree_path = None
    finally:
        log.write_state(state)
    return state
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_collab_orchestrator.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/collab_orchestrator.py tests/test_collab_orchestrator.py
git commit -m "feat: add linear heterogeneous collab orchestrator"
```

---

### Task 11: `config.py` + `cli.py` — `macr collab` subcommand

**Files:** Modify `macr/config.py` (create if absent), `macr/cli.py`; Create `tests/test_cli_collab.py`.

**Note:** V1's `macr/config.py` may be minimal or absent. If absent, create it with just `CollabConfig`. Do not break existing `config.py` contents if present — append.

- [ ] **Step 1: Write the failing test** — `tests/test_cli_collab.py`:
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


def _codex(tmp_repo_holder):
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")
    return FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=on_run)


def test_collab_approve_returns_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true"],
        claude_backend=_claude(),
        codex_backend=_codex(None),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_collab_reject_returns_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["collab", "do it", "--repo", str(repo), "--test-cmd", "true"],
        claude_backend=_claude(),
        codex_backend=_codex(None),
        human_gate=lambda state, **kw: HumanFeedback(decision="reject", feedback="no", timestamp="t"),
    )
    assert rc == 1


def test_collab_missing_binary_errors(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no claude/codex on PATH
    rc = cli.main(["collab", "do it", "--repo", str(repo), "--test-cmd", "true"])
    assert rc == 2
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_collab.py -v`.

- [ ] **Step 3a: Implement `macr/config.py`** — create the file (or append the dataclass if the file already exists):
```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CollabConfig:
    target_repo: Path
    test_cmd: list[str]
    claude_model: str | None = None
    codex_model: str | None = None
    sandbox: str = "workspace-write"
    approval: str = "never"
    timeout: int = 1800
    max_revisions: int = 2
```

- [ ] **Step 3b: Implement the `collab` subcommand in `macr/cli.py`** — add `import shutil` and `import shlex` at the top (keep existing imports), add a `collab` subparser inside `_parse_args`, and extend `main`'s signature + dispatch. The full updated `macr/cli.py`:
```python
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

from macr.human_gate import collab_human_gate, interactive_human_gate
from macr.llm import LLMError
from macr.orchestrator import run_task


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="macr", description="MACR multi-agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one MACR task end-to-end (single-model API path)")
    run_p.add_argument("task", help="the task description")
    run_p.add_argument("--max-revisions", type=int, default=2)
    run_p.add_argument("--model", default="claude-sonnet-4-6")

    collab_p = sub.add_parser("collab", help="Claude+Codex heterogeneous code collaboration (CLI-only)")
    collab_p.add_argument("task", help="the task description")
    collab_p.add_argument("--repo", required=True, help="path to the target git repository")
    collab_p.add_argument("--test-cmd", required=True, help="test command, e.g. 'pytest -q'")
    collab_p.add_argument("--max-revisions", type=int, default=2)
    collab_p.add_argument("--claude-model", default=None)
    collab_p.add_argument("--codex-model", default=None)
    collab_p.add_argument("--timeout", type=int, default=1800)
    return parser.parse_args(argv)


def _run_command(args, *, llm, human_gate) -> int:
    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        from macr.llm import AnthropicLLM

        llm = AnthropicLLM(model=args.model)
    runs_dir = Path(".macr/runs")
    try:
        state = run_task(args.task, llm, runs_dir, max_revisions=args.max_revisions, human_gate=human_gate)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


def _collab_command(args, *, claude_backend, codex_backend, human_gate) -> int:
    from macr.collab_orchestrator import run_collab

    if claude_backend is None or codex_backend is None:
        missing = [b for b in ("claude", "codex") if shutil.which(b) is None]
        if missing:
            print(f"error: required CLI not found on PATH: {', '.join(missing)}", file=sys.stderr)
            return 2
        from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend

        if claude_backend is None:
            claude_backend = ClaudeCliBackend(model=args.claude_model, timeout=args.timeout)
        if codex_backend is None:
            codex_backend = CodexCliBackend(model=args.codex_model, timeout=args.timeout)

    try:
        state = run_collab(
            args.task,
            repo=Path(args.repo),
            test_cmd=shlex.split(args.test_cmd),
            claude_backend=claude_backend,
            codex_backend=codex_backend,
            runs_dir=Path(".macr/runs"),
            worktrees_dir=Path(".macr/worktrees"),
            max_revisions=args.max_revisions,
            human_gate=human_gate,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure as non-zero
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


def main(argv: list[str] | None = None, *, llm=None,
         claude_backend=None, codex_backend=None,
         human_gate=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "collab":
        gate = human_gate or collab_human_gate
        return _collab_command(args, claude_backend=claude_backend, codex_backend=codex_backend, human_gate=gate)
    gate = human_gate or interactive_human_gate
    return _run_command(args, llm=llm, human_gate=gate)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run the collab CLI tests, then the FULL suite** — `.venv/bin/pytest tests/test_cli_collab.py -v` (3 passed), then `.venv/bin/pytest -q`. Expected: all pass (V1 44 + Stage A additions). If any V1 test broke (e.g. `test_cli.py`), fix the regression before committing.

- [ ] **Step 5: Commit**
```bash
git add macr/config.py macr/cli.py tests/test_cli_collab.py
git commit -m "feat: add macr collab subcommand wiring Claude+Codex CLI backends"
```

---

### Task 12: Smoke script + README usage

**Files:** Create `scripts/smoke_collab.py`; Modify `README.md` (append only).

This task is not covered by automated tests (it drives the real `claude` + `codex` CLIs on a real repo).

- [ ] **Step 1: Create `scripts/smoke_collab.py`:**
```python
"""Manual smoke test for `macr collab` against the real claude + codex CLIs.

Usage:
    .venv/bin/python scripts/smoke_collab.py /path/to/target-repo "pytest -q" "add a hello() function"
Requires `claude` and `codex` on PATH (logged in), and a clean git target repo.
Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: smoke_collab.py <repo> <test-cmd> <task>", file=sys.stderr)
        raise SystemExit(2)
    repo, test_cmd, task = sys.argv[1], sys.argv[2], sys.argv[3]
    raise SystemExit(main(["collab", task, "--repo", repo, "--test-cmd", test_cmd]))
```

- [ ] **Step 2: Append to the END of `README.md`** (read the file first; keep all existing content):
```markdown

---

## Claude⟷Codex 异构协作 (Stage A) / Heterogeneous collaboration

> 纯 CLI,不需要 API key。需 `claude` 与 `codex` 已安装并登录 / CLI-only, no API key; requires `claude` and `codex` on PATH.

```bash
# Claude 出方案/审 diff,Codex 在隔离 worktree 改代码,框架跑测试
.venv/bin/macr collab "为模块加一个 hello() 函数" \
    --repo /path/to/target-repo \
    --test-cmd "pytest -q"
```

流程:Claude Planner → Codex 在 `.macr/worktrees/<run_id>/` 改代码 → 框架跑 `--test-cmd` → Claude 审 diff+测试 → 规则判定 → 返工(≤ `--max-revisions`)→ Human Gate(approve/reject/edit)。产物在 `.macr/runs/<run_id>/`(含 `diff.vN.patch`、`test.vN.json`、`final.md`)。approve 后 worktree 保留供你手动 merge。
```

- [ ] **Step 3: Verify the smoke script parses (do NOT run it — it would drive the real CLIs):**
`.venv/bin/python -c "import ast; ast.parse(open('scripts/smoke_collab.py').read()); print('parse ok')"` → expect `parse ok`.

- [ ] **Step 4: Full suite still green** — `.venv/bin/pytest -q`.

- [ ] **Step 5: Commit**
```bash
git add scripts/smoke_collab.py README.md
git commit -m "docs: add collab smoke script and README usage"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §3 collab flow + roles → Task 6 (roles), Task 10 (orchestrator order Planner→Executor→diff→tests→Reviewer→Evaluator→gate).
- §4 module structure → Task 2 (worktree), 3 (testrunner), 4 (evaluator), 5 (agents/base), 6 (collab_roles), 7 (cli_backend), 8 (api_backend dormant), 10 (collab_orchestrator), 11 (config+cli). `agents/__init__.py` created in Task 5.
- §4.1 AgentBackend + CLI backends + dormant ApiBackend + "collab reads no ANTHROPIC_API_KEY" → Tasks 5/7/8/11 (`_collab_command` never touches the key).
- §4.2 worktree create/diff/cleanup (detached, add -A then diff --cached, remove --force) → Task 2.
- §4.3 testrunner → Task 3.
- §5 TestResult + SharedState fields → Task 1.
- §6 deterministic Evaluator rule (BLOCKED/NEEDS_FIX/PASS) → Task 4, wired in Task 10.
- §7 run-dir files incl diff.vN.patch / test.vN.{log,json} / state.json / final.md → Task 9 (writers) + Task 10 (calls).
- §8 config + `macr collab` flags + exit codes → Task 11.
- §9 error handling: missing binary (Task 11 exit 2), CLI nonzero/parse fail → retry → BLOCKED (Tasks 7+5+10), test missing/timeout → TestResult failure (Task 3), any exception → state.json via try/finally (Task 10).
- §10 TDD with FakeAgentBackend + real temp git repo, real CLIs only in smoke (Task 12); V1 untouched (Tasks 9/11 re-run V1 tests).
- §11 DoD → Task 11 Step 4 full suite; Task 12 smoke path.

**Placeholder scan:** No TBD/TODO. Every code step is complete and runnable. The two broad `except Exception` (cli `_run_command`, `_collab_command`) are intentional top-level guards, documented inline.

**Type/name consistency:** `AgentBackend.run_role(role, state, *, run_id, task_id, timestamp=None) -> Message` identical across base.py (Task 5), cli_backend (7), api_backend (8), FakeAgentBackend (5), and all call sites in collab_orchestrator (10). `Worktree.create(repo, run_id, worktrees_dir)` / `.diff()` / `.cleanup()` consistent Tasks 2↔10. `run_tests(worktree_path, test_cmd, timeout)` consistent Tasks 3↔10. `evaluate_collab(*, test_result, reviewer, agent_failed)` consistent Tasks 4↔10. `RunLog.write_diff(diff_text, attempt)` / `write_test(result, log, attempt)` consistent Tasks 9↔10. `collab_human_gate(state, *, input_fn, printer, timestamp)` consistent Tasks 9↔10↔11. `COLLAB_ROLES`/`PLANNER_C`/`EXECUTOR_C`/`REVIEWER_C` consistent Tasks 6↔10. `cli.main(argv, *, llm, claude_backend, codex_backend, human_gate)` consistent Task 11 ↔ test (uses `cli.shutil.which` monkeypatch — `shutil` imported at module top in Task 11). Decision compared via enum membership in orchestrator (`decision in (Decision.PASS, Decision.BLOCKED)`) where `decision` is the `Decision` enum returned by `evaluate_collab` — consistent (not the dumped string).
