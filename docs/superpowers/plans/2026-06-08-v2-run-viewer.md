# V2 Run Viewer (sub-project ①) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local read-only web viewer that lists past `.macr/runs/` and renders each run as a structured stage timeline.

**Architecture:** A FastAPI backend (`macr/web/`) reads each run's `state.json` (the single data source) and normalizes it into a `RunDetail` with an ordered `stages[]` list. A Vite+React SPA (`frontend/`) fetches the REST API and renders a run list + per-run timeline. A new `macr web` CLI subcommand serves the API and the built SPA. Read-only only; live driving / multi-run are later sub-projects.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, Pydantic v2 (backend); Vite + React + TypeScript + Vitest + React Testing Library (frontend). Spec: `docs/superpowers/specs/2026-06-08-v2-run-viewer-design.md`.

---

## File Structure

**Backend (Python, part of `macr` package):**
- `macr/web/__init__.py` — package marker.
- `macr/web/models.py` — Pydantic API models: `Stage`, `Artifact`, `RunSummary`, `RunDetail`.
- `macr/web/runs.py` — reads + normalizes run dirs: `list_runs`, `load_run`, `read_artifact`, plus `infer_command_type`/`build_stages` and `RunNotFound`/`RunCorrupt`/`ArtifactError`.
- `macr/web/app.py` — `create_app(runs_dir)` → FastAPI with 3 endpoints + optional static SPA mount.
- `macr/cli.py` — add `web` subcommand (modify existing file).

**Backend tests (flat, matching repo convention):**
- `tests/test_web_models.py`, `tests/test_web_runs.py`, `tests/test_web_app.py`, `tests/test_cli_web.py`.

**Frontend (Vite+React+TS):**
- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`.
- `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`.
- `frontend/src/RunList.tsx`, `frontend/src/RunDetail.tsx`, `frontend/src/StageCard.tsx`.
- `frontend/src/RunList.test.tsx`, `frontend/src/RunDetail.test.tsx`, `frontend/src/setupTests.ts`.

---

## Phase A — Backend data layer

### Task 1: Backend scaffold + dependencies

**Files:**
- Create: `macr/web/__init__.py`
- Modify: `pyproject.toml:16-17`

- [ ] **Step 1: Create the package marker**

Create `macr/web/__init__.py`:

```python
"""MACR web console — read-only run viewer (V2 sub-project 1)."""
```

- [ ] **Step 2: Add web + dev dependencies to pyproject.toml**

Replace the `[project.optional-dependencies]` block (`pyproject.toml:16-17`) with:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]
web = ["fastapi>=0.110", "uvicorn>=0.27"]
```

- [ ] **Step 3: Install the new deps into the project venv**

Run: `.venv/bin/pip install -e ".[web,dev]"`
Expected: installs fastapi + uvicorn; ends with "Successfully installed ...".

- [ ] **Step 4: Verify imports**

Run: `.venv/bin/python -c "import fastapi, uvicorn, macr.web; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add macr/web/__init__.py pyproject.toml
git commit -m "build: add web extra (fastapi+uvicorn) and macr.web package"
```

---

### Task 2: API models

**Files:**
- Create: `macr/web/models.py`
- Test: `tests/test_web_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_models.py`:

```python
import json

from macr.web.models import Artifact, RunDetail, RunSummary, Stage


def test_run_summary_defaults():
    s = RunSummary(run_id="R1", command_type="collab", task="do it")
    assert s.decision is None and s.broken is False


def test_run_detail_round_trips_json():
    detail = RunDetail(
        run_id="R1", command_type="collab", task="do it",
        repo="/tmp/r", worktree="/tmp/wt", decision="approve",
        stages=[Stage(kind="plan", label="Planner", agent="claude",
                      body={"summary": "s", "steps": ["a"]})],
        artifacts=[Artifact(name="diff.v1.patch", kind="diff")],
    )
    raw = json.loads(detail.model_dump_json())
    assert raw["stages"][0]["kind"] == "plan"
    assert raw["stages"][0]["status"] is None
    assert raw["artifacts"][0]["kind"] == "diff"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.web.models'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/web/models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Stage(BaseModel):
    """One row in a run's normalized timeline."""
    kind: str          # plan|turn|consensus|plan_review|executor|tests|reviewer|evaluator|gate
    label: str
    agent: str | None = None   # claude|codex|human|None
    status: str | None = None  # approve|reject|PASS|NEEDS_FIX|BLOCKED|passed|failed|None
    body: dict = Field(default_factory=dict)


class Artifact(BaseModel):
    """A downloadable raw file in the run dir."""
    name: str
    kind: str          # diff|test_log|final


class RunSummary(BaseModel):
    run_id: str
    command_type: str  # run|collab|discuss
    task: str
    decision: str | None = None
    broken: bool = False


class RunDetail(BaseModel):
    run_id: str
    command_type: str
    task: str
    repo: str | None = None
    worktree: str | None = None
    decision: str | None = None
    stages: list[Stage] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_models.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/models.py tests/test_web_models.py
git commit -m "feat(web): API models — Stage/Artifact/RunSummary/RunDetail"
```

---

### Task 3: Normalizer — command-type inference + linear (run/collab) stages

**Files:**
- Create: `macr/web/runs.py`
- Test: `tests/test_web_runs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_runs.py`:

```python
import json
from pathlib import Path

import pytest

from macr.web.runs import (
    RunCorrupt, RunNotFound, infer_command_type, load_run,
)


def _write_run(runs_dir: Path, run_id: str, state: dict) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _collab_state():
    return {
        "run_id": "R1", "user_query": "add add()", "target_repo": "/tmp/repo",
        "worktree_path": "/tmp/wt",
        "agent_outputs": {
            "planner": [{"summary": "plan it", "steps": ["read", "append"]}],
            "executor": [{"artifact": "def add", "notes": "done"}],
            "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
            "evaluator": [],
        },
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS", "test_passed": True}],
        "test_results": [{"command": "python check.py", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["diff --git a/mymod.py b/mymod.py\n+def add(): ..."],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def _run_state():
    return {
        "run_id": "R1", "user_query": "write a poem", "target_repo": None,
        "agent_outputs": {
            "planner": [{"summary": "plan", "steps": ["s"]}],
            "executor": [{"artifact": "poem", "notes": ""}],
            "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
            "evaluator": [{"decision": "PASS", "reasons": [], "confidence": 0.9}],
        },
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS"}],
        "test_results": [], "diffs": [],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def test_infer_command_type():
    assert infer_command_type(_collab_state()) == "collab"
    assert infer_command_type(_run_state()) == "run"
    assert infer_command_type({"discussion": [{"round": 0}], "consensus": None}) == "discuss"
    assert infer_command_type({"discussion": [], "consensus": {"summary": "x"}}) == "discuss"


def test_load_run_collab_stage_sequence(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "collab"
    assert detail.task == "add add()"
    assert detail.decision == "approve"
    kinds = [s.kind for s in detail.stages]
    assert kinds == ["plan", "executor", "tests", "reviewer", "evaluator", "gate"]
    tests_stage = next(s for s in detail.stages if s.kind == "tests")
    assert tests_stage.status == "passed"
    assert detail.stages[-1].kind == "gate" and detail.stages[-1].status == "approve"


def test_load_run_run_has_no_tests_or_diff(tmp_path):
    _write_run(tmp_path, "R1", _run_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "run"
    kinds = [s.kind for s in detail.stages]
    assert kinds == ["plan", "executor", "reviewer", "evaluator", "gate"]
    assert all(s.kind != "tests" for s in detail.stages)


def test_load_run_missing_raises_not_found(tmp_path):
    with pytest.raises(RunNotFound):
        load_run(tmp_path, "nope")


def test_load_run_corrupt_state_raises(tmp_path):
    d = tmp_path / "R1"
    d.mkdir()
    (d / "state.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(RunCorrupt):
        load_run(tmp_path, "R1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.web.runs'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/web/runs.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from macr.web.models import Artifact, RunDetail, RunSummary, Stage


class RunNotFound(Exception):
    """Run id has no directory / no state.json."""


class RunCorrupt(Exception):
    """state.json exists but cannot be parsed."""


class ArtifactError(Exception):
    """Requested artifact name is invalid or not in the run dir."""


def _load_state(runs_dir: Path, run_id: str) -> dict:
    state_path = Path(runs_dir) / run_id / "state.json"
    if not state_path.is_file():
        raise RunNotFound(run_id)
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RunCorrupt(f"{run_id}: {exc}") from exc


def infer_command_type(state: dict) -> str:
    if state.get("discussion") or state.get("consensus"):
        return "discuss"
    if state.get("target_repo"):
        return "collab"
    return "run"


def _task_text(state: dict) -> str:
    return state.get("topic") or state.get("user_query") or ""


def _final_decision(state: dict) -> str | None:
    hf = state.get("human_feedback")
    return hf.get("decision") if hf else None


def _planner_stage(state: dict, agent: str | None) -> Stage | None:
    items = state.get("agent_outputs", {}).get("planner", [])
    if not items:
        return None
    p = items[0]
    return Stage(kind="plan", label="Planner", agent=agent,
                 body={"summary": p.get("summary", ""), "steps": p.get("steps", [])})


def _impl_loop_stages(state: dict, *, with_tests: bool, exec_agent: str | None,
                      review_agent: str | None, reviewer_offset: int = 0) -> list[Stage]:
    ao = state.get("agent_outputs", {})
    execs = ao.get("executor", [])
    reviewers = ao.get("reviewer", [])[reviewer_offset:]
    tests = state.get("test_results", [])
    impl_decisions = [d for d in state.get("decisions", []) if d.get("stage") != "plan_review"]
    stages: list[Stage] = []
    for i, ex in enumerate(execs):
        n = i + 1
        stages.append(Stage(kind="executor", label=f"Executor #{n}", agent=exec_agent,
                            body={"artifact": ex.get("artifact", ""), "notes": ex.get("notes", "")}))
        if with_tests and i < len(tests):
            tr = tests[i]
            stages.append(Stage(kind="tests", label=f"Tests #{n}",
                                status="passed" if tr.get("passed") else "failed",
                                body={"command": tr.get("command", ""),
                                      "exit_code": tr.get("exit_code"), "log": tr.get("log", "")}))
        if i < len(reviewers):
            rv = reviewers[i]
            stages.append(Stage(kind="reviewer", label=f"Reviewer #{n}", agent=review_agent,
                                status=rv.get("decision"),
                                body={"summary": rv.get("summary", ""), "findings": rv.get("findings", [])}))
        if i < len(impl_decisions):
            stages.append(Stage(kind="evaluator", label=f"Evaluator #{n}",
                                status=impl_decisions[i].get("decision")))
    return stages


def _gate_stage(state: dict) -> Stage | None:
    hf = state.get("human_feedback")
    if not hf:
        return None
    return Stage(kind="gate", label="Human Gate", status=hf.get("decision"),
                 body={"feedback": hf.get("feedback", "")})


def _stages_linear(state: dict, command_type: str) -> list[Stage]:
    is_collab = command_type == "collab"
    plan_agent = "claude" if is_collab else None
    exec_agent = "codex" if is_collab else None
    review_agent = "claude" if is_collab else None
    stages: list[Stage] = []
    p = _planner_stage(state, plan_agent)
    if p:
        stages.append(p)
    stages += _impl_loop_stages(state, with_tests=is_collab, exec_agent=exec_agent,
                                review_agent=review_agent)
    g = _gate_stage(state)
    if g:
        stages.append(g)
    return stages


def build_stages(state: dict) -> list[Stage]:
    command_type = infer_command_type(state)
    if command_type == "discuss":
        return _stages_discuss(state)
    return _stages_linear(state, command_type)


ARTIFACT_KINDS = (("diff.", "diff"), ("test.", "test_log"), ("final.md", "final"))


def list_artifacts(run_dir: Path) -> list[Artifact]:
    out: list[Artifact] = []
    for f in sorted(run_dir.iterdir()):
        if not f.is_file():
            continue
        for prefix, kind in ARTIFACT_KINDS:
            if f.name.startswith(prefix) or f.name == prefix:
                out.append(Artifact(name=f.name, kind=kind))
                break
    return out


def load_run(runs_dir: Path, run_id: str) -> RunDetail:
    state = _load_state(runs_dir, run_id)
    command_type = infer_command_type(state)
    return RunDetail(
        run_id=state.get("run_id", run_id),
        command_type=command_type,
        task=_task_text(state),
        repo=state.get("target_repo"),
        worktree=state.get("worktree_path"),
        decision=_final_decision(state),
        stages=build_stages(state),
        artifacts=list_artifacts(Path(runs_dir) / run_id),
    )
```

NOTE: `_stages_discuss` is added in Task 4. To make Task 3's tests pass now, add a temporary stub at the bottom of the file (Task 4 replaces it):

```python
def _stages_discuss(state: dict) -> list[Stage]:
    return []  # replaced in Task 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/runs.py tests/test_web_runs.py
git commit -m "feat(web): run normalizer — infer command type + linear run/collab timeline"
```

---

### Task 4: Normalizer — discuss timeline

**Files:**
- Modify: `macr/web/runs.py` (replace the `_stages_discuss` stub)
- Test: `tests/test_web_runs.py` (add a discuss test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_runs.py`:

```python
def _discuss_state():
    return {
        "run_id": "R1", "user_query": "build add()", "topic": "build add()",
        "target_repo": "/tmp/repo", "worktree_path": "/tmp/wt",
        "agent_outputs": {
            "planner": [], "executor": [{"artifact": "def add", "notes": ""}],
            "reviewer": [
                {"summary": "plan-rv", "findings": [], "decision": "approve"},  # plan review
                {"summary": "impl-rv", "findings": [], "decision": "approve"},  # impl review
            ],
            "evaluator": [],
        },
        "reviews": [
            {"summary": "plan-rv", "findings": [], "decision": "approve"},
            {"summary": "impl-rv", "findings": [], "decision": "approve"},
        ],
        "decisions": [
            {"stage": "plan_review", "attempt": 0, "decision": "PASS"},
            {"attempt": 1, "decision": "PASS", "test_passed": True},
        ],
        "test_results": [{"command": "python check.py", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["diff ..."],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [
            {"round": 0, "agent": "claude", "kind": "plan", "content": {"summary": "c-plan", "steps": ["s"]}},
            {"round": 0, "agent": "codex", "kind": "plan", "content": {"summary": "x-plan", "steps": ["s"]}},
            {"round": 1, "agent": "claude", "kind": "turn",
             "content": {"response": "r", "concerns": [], "revised_steps": []}},
        ],
        "consensus": {"summary": "agreed", "steps": ["do-1"], "rationale": "r", "open_questions": []},
    }


def test_load_run_discuss_stage_sequence(tmp_path):
    _write_run(tmp_path, "R1", _discuss_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "discuss"
    kinds = [s.kind for s in detail.stages]
    # two plans + one turn + consensus + one plan_review + impl loop (exec/tests/reviewer/eval) + gate
    assert kinds == ["plan", "plan", "turn", "consensus", "plan_review",
                     "executor", "tests", "reviewer", "evaluator", "gate"]
    # the impl reviewer must be the SECOND reviewer entry (plan review consumed the first)
    impl_review = next(s for s in detail.stages if s.kind == "reviewer")
    assert impl_review.body["summary"] == "impl-rv"
    pr = next(s for s in detail.stages if s.kind == "plan_review")
    assert pr.status == "PASS" and pr.body["summary"] == "plan-rv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py::test_load_run_discuss_stage_sequence -q`
Expected: FAIL — the stub returns `[]`, so `kinds == []` ≠ expected.

- [ ] **Step 3: Replace the stub with the real implementation**

In `macr/web/runs.py`, replace the temporary `_stages_discuss` stub with:

```python
def _stages_discuss(state: dict) -> list[Stage]:
    stages: list[Stage] = []
    # 1. discussion: plans / turns / human interjections (injected "review" entries are
    #    skipped here — they surface as plan_review stages below).
    for e in state.get("discussion", []):
        kind = e.get("kind")
        agent = e.get("agent")
        content = e.get("content", {}) if isinstance(e.get("content"), dict) else {}
        if kind == "plan":
            stages.append(Stage(kind="plan", label=f"Plan ({agent})", agent=agent,
                                body={"summary": content.get("summary", ""),
                                      "steps": content.get("steps", [])}))
        elif kind == "turn":
            stages.append(Stage(kind="turn", label=f"Turn r{e.get('round')} ({agent})", agent=agent,
                                body={"response": content.get("response", ""),
                                      "concerns": content.get("concerns", []),
                                      "revised_steps": content.get("revised_steps", [])}))
        elif kind == "interjection":
            stages.append(Stage(kind="turn", label=f"Human interjection r{e.get('round')}",
                                agent="human", body={"text": e.get("content", "")}))
    # 2. consensus
    c = state.get("consensus")
    if c:
        stages.append(Stage(kind="consensus", label="Consensus",
                            body={"summary": c.get("summary", ""), "steps": c.get("steps", []),
                                  "rationale": c.get("rationale", "")}))
    # 3. plan-review loop (codex reviews the consensus plan)
    plan_reviews = [d for d in state.get("decisions", []) if d.get("stage") == "plan_review"]
    reviews = state.get("reviews", [])
    for d in plan_reviews:
        att = d.get("attempt", 0)
        rv = reviews[att] if att < len(reviews) else {}
        stages.append(Stage(kind="plan_review", label=f"Plan Review #{att}", agent="codex",
                            status=d.get("decision"),
                            body={"summary": rv.get("summary", ""), "findings": rv.get("findings", [])}))
    # 4. implementation loop — impl reviewers start after the plan reviewers in agent_outputs.reviewer
    stages += _impl_loop_stages(state, with_tests=True, exec_agent="codex",
                                review_agent="claude", reviewer_offset=len(plan_reviews))
    # 5. final human gate
    g = _gate_stage(state)
    if g:
        stages.append(g)
    return stages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/runs.py tests/test_web_runs.py
git commit -m "feat(web): discuss timeline normalization (plan/turn/consensus/plan-review + impl loop)"
```

---

### Task 5: list_runs + read_artifact (with path-traversal guard)

**Files:**
- Modify: `macr/web/runs.py` (add `list_runs`, `read_artifact`)
- Test: `tests/test_web_runs.py` (add tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_runs.py`:

```python
from macr.web.runs import ArtifactError, list_runs, read_artifact


def test_list_runs_newest_first_and_marks_broken(tmp_path):
    _write_run(tmp_path, "R20260607_001", _collab_state())
    _write_run(tmp_path, "R20260607_002", _run_state())
    broken = tmp_path / "R20260607_003"
    broken.mkdir()
    (broken / "state.json").write_text("{ broken", encoding="utf-8")
    summaries = list_runs(tmp_path)
    ids = [s.run_id for s in summaries]
    assert ids == ["R20260607_003", "R20260607_002", "R20260607_001"]  # newest first
    assert summaries[0].broken is True
    assert summaries[1].command_type == "run"
    assert summaries[2].command_type == "collab" and summaries[2].decision == "approve"


def test_list_runs_empty_dir(tmp_path):
    assert list_runs(tmp_path) == []


def test_read_artifact_returns_text(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    (tmp_path / "R1" / "diff.v1.patch").write_text("the diff", encoding="utf-8")
    assert read_artifact(tmp_path, "R1", "diff.v1.patch") == "the diff"


def test_read_artifact_rejects_traversal(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    for bad in ("../R1/state.json", "/etc/passwd", "sub/../../x", "a/b"):
        with pytest.raises(ArtifactError):
            read_artifact(tmp_path, "R1", bad)


def test_read_artifact_missing_run_raises_not_found(tmp_path):
    with pytest.raises(RunNotFound):
        read_artifact(tmp_path, "nope", "diff.v1.patch")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py -q`
Expected: FAIL with `ImportError: cannot import name 'list_runs'`.

- [ ] **Step 3: Add the implementation**

Append to `macr/web/runs.py`:

```python
def list_runs(runs_dir: Path) -> list[RunSummary]:
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    out: list[RunSummary] = []
    for d in sorted((p for p in runs_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        run_id = d.name
        try:
            state = _load_state(runs_dir, run_id)
        except RunNotFound:
            continue
        except RunCorrupt:
            out.append(RunSummary(run_id=run_id, command_type="unknown", task="", broken=True))
            continue
        out.append(RunSummary(
            run_id=state.get("run_id", run_id),
            command_type=infer_command_type(state),
            task=_task_text(state),
            decision=_final_decision(state),
        ))
    return out


def read_artifact(runs_dir: Path, run_id: str, name: str) -> str:
    run_dir = Path(runs_dir) / run_id
    if not (run_dir / "state.json").is_file():
        raise RunNotFound(run_id)
    # name must be a bare filename that resolves to a file directly inside run_dir.
    if name != Path(name).name or name in ("", ".", ".."):
        raise ArtifactError(f"invalid artifact name: {name!r}")
    target = (run_dir / name).resolve()
    if target.parent != run_dir.resolve() or not target.is_file():
        raise ArtifactError(f"artifact not found: {name!r}")
    return target.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_runs.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/runs.py tests/test_web_runs.py
git commit -m "feat(web): list_runs (newest-first, broken-tolerant) + read_artifact with traversal guard"
```

---

## Phase B — FastAPI app

### Task 6: FastAPI endpoints

**Files:**
- Create: `macr/web/app.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_app.py`:

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from macr.web.app import create_app


def _write_run(runs_dir: Path, run_id: str, state: dict) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _state():
    return {
        "run_id": "R1", "user_query": "do it", "target_repo": "/tmp/repo",
        "agent_outputs": {"planner": [{"summary": "p", "steps": ["s"]}],
                          "executor": [{"artifact": "a", "notes": ""}],
                          "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
                          "evaluator": []},
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS", "test_passed": True}],
        "test_results": [{"command": "t", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["d"], "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def _client(tmp_path):
    return TestClient(create_app(runs_dir=tmp_path))


def test_list_runs_endpoint(tmp_path):
    _write_run(tmp_path, "R1", _state())
    r = _client(tmp_path).get("/api/runs")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["run_id"] == "R1" and body[0]["command_type"] == "collab"


def test_run_detail_endpoint(tmp_path):
    _write_run(tmp_path, "R1", _state())
    r = _client(tmp_path).get("/api/runs/R1")
    assert r.status_code == 200
    assert [s["kind"] for s in r.json()["stages"]] == \
        ["plan", "executor", "tests", "reviewer", "evaluator", "gate"]


def test_run_detail_missing_is_404(tmp_path):
    assert _client(tmp_path).get("/api/runs/nope").status_code == 404


def test_run_detail_corrupt_is_422(tmp_path):
    d = tmp_path / "R1"
    d.mkdir()
    (d / "state.json").write_text("{ broken", encoding="utf-8")
    assert _client(tmp_path).get("/api/runs/R1").status_code == 422


def test_artifact_endpoint_and_traversal(tmp_path):
    _write_run(tmp_path, "R1", _state())
    (tmp_path / "R1" / "final.md").write_text("the final", encoding="utf-8")
    c = _client(tmp_path)
    assert c.get("/api/runs/R1/artifacts/final.md").text == "the final"
    assert c.get("/api/runs/R1/artifacts/..%2F..%2Fetc%2Fpasswd").status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'macr.web.app'`.

- [ ] **Step 3: Write minimal implementation**

Create `macr/web/app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from macr.web.runs import (
    ArtifactError, RunCorrupt, RunNotFound, list_runs, load_run, read_artifact,
)


def create_app(runs_dir: Path) -> FastAPI:
    runs_dir = Path(runs_dir)
    app = FastAPI(title="MACR Run Viewer")

    @app.get("/api/runs")
    def get_runs():
        return list_runs(runs_dir)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return load_run(runs_dir, run_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        except RunCorrupt as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/runs/{run_id}/artifacts/{name}", response_class=PlainTextResponse)
    def get_artifact(run_id: str, name: str):
        try:
            return read_artifact(runs_dir, run_id, name)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        except ArtifactError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/app.py tests/test_web_app.py
git commit -m "feat(web): FastAPI endpoints — runs list / detail / artifact with status codes"
```

---

### Task 7: Static SPA mount

**Files:**
- Modify: `macr/web/app.py`
- Test: `tests/test_web_app.py` (add a static-serving test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_app.py`:

```python
def test_spa_index_served_when_dist_present(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    app = create_app(runs_dir=tmp_path, spa_dist=dist)
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "spa" in r.text


def test_no_spa_mount_when_dist_absent(tmp_path):
    # create_app must not crash when no built SPA is present
    app = create_app(runs_dir=tmp_path, spa_dist=tmp_path / "missing")
    assert TestClient(app).get("/api/runs").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: FAIL with `TypeError: create_app() got an unexpected keyword argument 'spa_dist'`.

- [ ] **Step 3: Update create_app to mount the SPA**

In `macr/web/app.py`, change the import line to add `StaticFiles`, update the signature, and mount static at the end (after the routes, before `return app`):

Change `def create_app(runs_dir: Path) -> FastAPI:` to:

```python
def create_app(runs_dir: Path, spa_dist: Path | None = None) -> FastAPI:
```

Add this import near the top (with the other fastapi imports):

```python
from fastapi.staticfiles import StaticFiles
```

Insert before `return app`:

```python
    if spa_dist is not None and Path(spa_dist).is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dist), html=True), name="spa")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add macr/web/app.py tests/test_web_app.py
git commit -m "feat(web): serve built SPA from spa_dist (html fallback), tolerate absent dist"
```

---

## Phase C — CLI

### Task 8: `macr web` subcommand

**Files:**
- Modify: `macr/cli.py`
- Test: `tests/test_cli_web.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_web.py`:

```python
from macr import cli


def test_web_command_builds_app_without_serving(tmp_path, monkeypatch):
    """`macr web` parses args and hands a FastAPI app to the injected serve fn (no real server)."""
    served = {}

    def fake_serve(app, *, host, port):
        served["host"], served["port"] = host, port
        served["has_routes"] = any(r.path == "/api/runs" for r in app.routes)
        return 0

    rc = cli.main(
        ["web", "--runs-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "9123"],
        serve=fake_serve,
    )
    assert rc == 0
    assert served["host"] == "127.0.0.1" and served["port"] == 9123
    assert served["has_routes"] is True


def test_web_command_help_lists_flags(capsys):
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["web", "--help"])
    out = capsys.readouterr().out
    assert "--runs-dir" in out and "--port" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_web.py -q`
Expected: FAIL — `web` is not a valid subcommand (argparse SystemExit) / `main()` has no `serve` kwarg.

- [ ] **Step 3: Add the subcommand and dispatch**

In `macr/cli.py`, inside `_parse_args`, after the `discuss_p` block (before `return parser.parse_args(argv)`), add:

```python
    web_p = sub.add_parser("web", help="serve the read-only run viewer (V2)")
    web_p.add_argument("--runs-dir", default=".macr/runs",
                       help="directory of run records to browse (default: .macr/runs)")
    web_p.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    web_p.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
```

Add this function above `main` in `macr/cli.py`:

```python
def _default_serve(app, *, host: str, port: int) -> int:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
    return 0


def _web_command(args, *, serve) -> int:
    from macr.web.app import create_app

    runs_dir = Path(args.runs_dir).resolve()
    spa_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    app = create_app(runs_dir=runs_dir, spa_dist=spa_dist)
    print(f"MACR run viewer → http://{args.host}:{args.port}  (runs: {runs_dir})")
    return serve(app, host=args.host, port=args.port)
```

Change the `main` signature to add a `serve` parameter and dispatch `web`. Update the signature line:

```python
def main(argv: list[str] | None = None, *, llm=None,
         claude_backend=None, codex_backend=None, impl_codex_backend=None,
         human_gate=None, discussion_control=None, consensus_gate=None, view=None,
         serve=None) -> int:
```

Immediately after `if invalid is not None: return invalid`, add:

```python
    if args.command == "web":
        return _web_command(args, serve=serve or _default_serve)
```

NOTE: `_validate_args` accesses `args.task`. The `web` subcommand has no `task`, so guard it. In `_validate_args`, change the first line `if not args.task.strip():` to:

```python
    task = getattr(args, "task", None)
    if task is not None and not task.strip():
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_web.py tests/test_cli.py -q`
Expected: PASS (existing CLI tests unaffected; 2 new pass).

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all green, including the new web tests).

- [ ] **Step 6: Commit**

```bash
git add macr/cli.py tests/test_cli_web.py
git commit -m "feat(cli): macr web subcommand serving the run viewer (injectable serve fn)"
```

---

## Phase D — Frontend

### Task 9: Vite + React + TS scaffold with Vitest

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/setupTests.ts`, `frontend/.gitignore`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "macr-run-viewer",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: Create config files**

`frontend/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts" },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>MACR Run Viewer</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/setupTests.ts`:

```typescript
import "@testing-library/jest-dom";
```

`frontend/.gitignore`:

```
node_modules/
dist/
```

- [ ] **Step 3: Create `frontend/src/main.tsx` (placeholder mount; App added in Task 10)**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <div>MACR Run Viewer</div>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Install deps and verify the test runner boots**

Run: `cd frontend && npm install`
Expected: installs without errors (creates `node_modules/`).

Run: `cd frontend && npm test`
Expected: Vitest runs and reports "No test files found" (exit 0 or the no-tests message) — confirms the runner is wired.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/src/main.tsx frontend/src/setupTests.ts frontend/.gitignore
git commit -m "build(frontend): Vite + React + TS scaffold with Vitest"
```

---

### Task 10: API client + types + router shell

**Files:**
- Create: `frontend/src/api.ts`, `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create `frontend/src/api.ts` (types mirror the backend models)**

```typescript
export interface Stage {
  kind: string;
  label: string;
  agent: string | null;
  status: string | null;
  body: Record<string, unknown>;
}
export interface Artifact { name: string; kind: string; }
export interface RunSummary {
  run_id: string;
  command_type: string;
  task: string;
  decision: string | null;
  broken: boolean;
}
export interface RunDetail {
  run_id: string;
  command_type: string;
  task: string;
  repo: string | null;
  worktree: string | null;
  decision: string | null;
  stages: Stage[];
  artifacts: Artifact[];
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const fetchRuns = () => getJSON<RunSummary[]>("/api/runs");
export const fetchRun = (id: string) => getJSON<RunDetail>(`/api/runs/${id}`);
```

- [ ] **Step 2: Create `frontend/src/App.tsx` (router shell; RunList/RunDetail added next tasks)**

```tsx
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";

export function App() {
  return (
    <BrowserRouter>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd" }}>
        <Link to="/" style={{ fontWeight: 600, textDecoration: "none" }}>MACR Run Viewer</Link>
      </header>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:id" element={<RunDetail />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
```

- [ ] **Step 3: Update `frontend/src/main.tsx` to render App**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors (RunList/RunDetail are created in the next tasks; if tsc fails on missing modules, proceed — they are created in Tasks 11–12 and the build is verified in Task 13).

NOTE: If `tsc -b` fails here because `./RunList` / `./RunDetail` do not yet exist, that is expected — they are created in Tasks 11 and 12. Do not add stubs; just proceed. The end-to-end build is verified in Task 13.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat(frontend): API client + typed models + router shell"
```

---

### Task 11: RunList component + test

**Files:**
- Create: `frontend/src/RunList.tsx`, `frontend/src/RunList.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/RunList.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RunList } from "./RunList";
import type { RunSummary } from "./api";

function mockFetch(data: RunSummary[]) {
  globalThis.fetch = (() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(data) })) as unknown as typeof fetch;
}

test("renders run rows with type badge and decision", async () => {
  mockFetch([
    { run_id: "R20260607_002", command_type: "discuss", task: "build add()", decision: "approve", broken: false },
    { run_id: "R20260607_001", command_type: "collab", task: "do it", decision: null, broken: false },
  ]);
  render(<MemoryRouter><RunList /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("R20260607_002")).toBeInTheDocument());
  expect(screen.getByText("discuss")).toBeInTheDocument();
  expect(screen.getByText("build add()")).toBeInTheDocument();
  expect(screen.getByText("approve")).toBeInTheDocument();
});

test("shows empty state when there are no runs", async () => {
  mockFetch([]);
  render(<MemoryRouter><RunList /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText(/no runs/i)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/RunList.test.tsx`
Expected: FAIL — cannot resolve `./RunList`.

- [ ] **Step 3: Create `frontend/src/RunList.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRuns, type RunSummary } from "./api";

export function RunList() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>Failed to load runs: {error}</p>;
  if (runs === null) return <p>Loading…</p>;
  if (runs.length === 0) return <p>No runs yet.</p>;

  return (
    <table style={{ borderCollapse: "collapse", width: "100%" }}>
      <tbody>
        {runs.map((r) => (
          <tr key={r.run_id} style={{ borderBottom: "1px solid #eee", opacity: r.broken ? 0.5 : 1 }}>
            <td style={{ padding: "8px 12px", fontFamily: "monospace" }}>
              <Link to={`/runs/${r.run_id}`}>{r.run_id}</Link>
            </td>
            <td style={{ padding: "8px 12px" }}>
              <span style={{ background: "#eef", borderRadius: 4, padding: "2px 8px" }}>
                {r.command_type}
              </span>
            </td>
            <td style={{ padding: "8px 12px" }}>{r.task}</td>
            <td style={{ padding: "8px 12px" }}>{r.broken ? "(broken)" : r.decision ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/RunList.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/RunList.tsx frontend/src/RunList.test.tsx
git commit -m "feat(frontend): RunList — newest-first run table with type badge + empty/error states"
```

---

### Task 12: RunDetail timeline + StageCard + test

**Files:**
- Create: `frontend/src/StageCard.tsx`, `frontend/src/RunDetail.tsx`, `frontend/src/RunDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/RunDetail.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { RunDetail } from "./RunDetail";
import type { RunDetail as RunDetailT } from "./api";

function mockFetch(data: RunDetailT) {
  globalThis.fetch = (() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(data) })) as unknown as typeof fetch;
}

const detail: RunDetailT = {
  run_id: "R1", command_type: "collab", task: "add add()", repo: "/tmp/r",
  worktree: "/tmp/wt", decision: "approve",
  stages: [
    { kind: "plan", label: "Planner", agent: "claude", status: null, body: { summary: "plan it", steps: ["read"] } },
    { kind: "executor", label: "Executor #1", agent: "codex", status: null, body: { artifact: "def add", notes: "" } },
    { kind: "tests", label: "Tests #1", agent: null, status: "passed", body: { command: "t", exit_code: 0, log: "OK" } },
    { kind: "gate", label: "Human Gate", agent: null, status: "approve", body: { feedback: "" } },
  ],
  artifacts: [{ name: "diff.v1.patch", kind: "diff" }],
};

test("renders each stage label and the task", async () => {
  mockFetch(detail);
  render(
    <MemoryRouter initialEntries={["/runs/R1"]}>
      <Routes><Route path="/runs/:id" element={<RunDetail />} /></Routes>
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("add add()")).toBeInTheDocument());
  expect(screen.getByText("Planner")).toBeInTheDocument();
  expect(screen.getByText("Executor #1")).toBeInTheDocument();
  expect(screen.getByText("Tests #1")).toBeInTheDocument();
  expect(screen.getByText("Human Gate")).toBeInTheDocument();
  expect(screen.getByText("passed")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/RunDetail.test.tsx`
Expected: FAIL — cannot resolve `./RunDetail`.

- [ ] **Step 3: Create `frontend/src/StageCard.tsx`**

```tsx
import type { Stage } from "./api";

function Body({ stage }: { stage: Stage }) {
  const b = stage.body as Record<string, unknown>;
  if (stage.kind === "plan" || stage.kind === "consensus") {
    return (
      <div>
        <p>{String(b.summary ?? "")}</p>
        <ol>{(b.steps as string[] | undefined)?.map((s, i) => <li key={i}>{s}</li>)}</ol>
      </div>
    );
  }
  if (stage.kind === "executor") return <pre>{String(b.artifact ?? "")}</pre>;
  if (stage.kind === "tests") return <pre>{String(b.log ?? "")}</pre>;
  if (stage.kind === "reviewer" || stage.kind === "plan_review") return <p>{String(b.summary ?? "")}</p>;
  if (stage.kind === "turn") return <p>{String(b.response ?? b.text ?? "")}</p>;
  if (stage.kind === "gate") return <p>{String(b.feedback ?? "")}</p>;
  return null;
}

export function StageCard({ stage }: { stage: Stage }) {
  return (
    <div style={{ borderLeft: "3px solid #88a", margin: "0 0 12px 8px", padding: "4px 0 4px 16px" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
        <strong>{stage.label}</strong>
        {stage.agent && <span style={{ color: "#666", fontSize: 12 }}>{stage.agent}</span>}
        {stage.status && (
          <span style={{ marginLeft: "auto", background: "#efe", borderRadius: 4, padding: "1px 8px" }}>
            {stage.status}
          </span>
        )}
      </div>
      <Body stage={stage} />
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/RunDetail.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchRun, type RunDetail as RunDetailT } from "./api";
import { StageCard } from "./StageCard";

export function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    fetchRun(id).then(setRun).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <p style={{ color: "crimson" }}>Failed to load run: {error}</p>;
  if (run === null) return <p>Loading…</p>;

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>
        <span style={{ fontFamily: "monospace" }}>{run.run_id}</span>{" "}
        <span style={{ background: "#eef", borderRadius: 4, padding: "2px 8px", fontSize: 14 }}>
          {run.command_type}
        </span>{" "}
        {run.decision && <span>· {run.decision}</span>}
      </h2>
      <p style={{ color: "#444" }}>{run.task}</p>
      <div style={{ marginTop: 16 }}>
        {run.stages.map((s, i) => <StageCard key={i} stage={s} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/RunDetail.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/StageCard.tsx frontend/src/RunDetail.tsx frontend/src/RunDetail.test.tsx
git commit -m "feat(frontend): RunDetail stage timeline + StageCard renderer"
```

---

### Task 13: Build + end-to-end smoke

**Files:** none new (verification task)

- [ ] **Step 1: Typecheck + build the SPA**

Run: `cd frontend && npm run build`
Expected: `tsc -b` passes and Vite writes `frontend/dist/index.html` + assets.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all component tests pass (RunList + RunDetail).

- [ ] **Step 3: Create a synthetic run dir for the smoke check**

```bash
mkdir -p /tmp/macr-view/.macr/runs/R20260608_001
cat > /tmp/macr-view/.macr/runs/R20260608_001/state.json <<'JSON'
{"run_id":"R20260608_001","user_query":"smoke","target_repo":"/tmp/r",
 "agent_outputs":{"planner":[{"summary":"p","steps":["s"]}],"executor":[{"artifact":"a","notes":""}],
 "reviewer":[{"summary":"ok","findings":[],"decision":"approve"}],"evaluator":[]},
 "reviews":[{"summary":"ok","findings":[],"decision":"approve"}],
 "decisions":[{"attempt":1,"decision":"PASS","test_passed":true}],
 "test_results":[{"command":"t","passed":true,"exit_code":0,"log":"OK\n"}],
 "diffs":["d"],"human_feedback":{"decision":"approve","feedback":"","timestamp":"t"},
 "discussion":[],"consensus":null}
JSON
```

- [ ] **Step 4: Start the server (background) and curl the API + SPA**

Run (background):

```bash
.venv/bin/python -m macr.cli web --runs-dir /tmp/macr-view/.macr/runs --port 8011 &
sleep 2
```

Run: `curl -s http://127.0.0.1:8011/api/runs`
Expected: JSON array containing `"run_id":"R20260608_001"` and `"command_type":"collab"`.

Run: `curl -s http://127.0.0.1:8011/api/runs/R20260608_001 | head -c 200`
Expected: JSON with a `stages` array.

Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8011/`
Expected: `200` (the built SPA index is served).

Stop the server: `kill %1` (or `pkill -f "macr.cli web"`).

- [ ] **Step 5: Final full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit (gitignore built assets, add a README note)**

Ensure `frontend/dist/` is gitignored (already in `frontend/.gitignore` from Task 9). Add a short run note to the repo README or a `macr/web/README.md`:

Create `macr/web/README.md`:

```markdown
# MACR Run Viewer (V2 sub-project 1)

Read-only web viewer for `.macr/runs/`.

## Run

```bash
# 1. build the SPA once
cd frontend && npm install && npm run build && cd ..
# 2. serve API + SPA
macr web --runs-dir .macr/runs --port 8000
# open http://127.0.0.1:8000
```

Dev mode (hot reload): `cd frontend && npm run dev` (proxies /api to :8000).
```

```bash
git add macr/web/README.md
git commit -m "docs(web): run viewer usage; verified end-to-end (api + SPA + macr web)"
```

---

## Self-Review

**Spec coverage:**
- Stack (FastAPI + Vite/React, `macr web`): Tasks 1, 6–13 ✓
- `state.json` single source + normalized `RunDetail`/`Stage`: Tasks 2–4 ✓
- 3 endpoints (list/detail/artifact) + status codes: Task 6 ✓
- command_type inference (run/collab/discuss): Task 3 (`infer_command_type`) ✓
- stage reconstruction for all 3 command types: Tasks 3 (linear) + 4 (discuss) ✓
- list newest-first + broken-tolerant: Task 5 ✓
- path-traversal guard: Tasks 5 + 6 ✓
- SPA served by FastAPI: Task 7 ✓
- frontend run list + timeline + states: Tasks 11–12 ✓
- TDD backend + light frontend tests: every task ✓
- YAGNI exclusions (no live/multi-run/auth/DAG): respected — no such tasks ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. The two `tsc -b` "may fail because module created later" notes are intentional ordering guidance, not placeholders.

**Type consistency:** `Stage`/`Artifact`/`RunSummary`/`RunDetail` field names identical between `macr/web/models.py` (Task 2), `frontend/src/api.ts` (Task 10), and all consumers. `create_app(runs_dir, spa_dist=None)` signature consistent between Tasks 6, 7, 8. `infer_command_type`/`load_run`/`list_runs`/`read_artifact` names consistent across Tasks 3–6 and 8.
