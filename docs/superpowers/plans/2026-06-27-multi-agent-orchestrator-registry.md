# Multi-Agent Orchestrator Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `docs/multi_agent_orchestrator_design.md` into the next concrete MACR milestone: an explicit workflow / agent / policy registry plus run manifest metadata, so MACR is no longer only a set of commands but a queryable orchestration layer.

**Architecture:** Keep the existing execution paths (`run`, `collab`, `discuss`, `--worker-runtime tmux`) unchanged. Add typed registry models for `TaskSpec`, `AgentSpec`, `PolicySpec`, and `WorkflowTemplate`; expose built-in workflow templates through `macr workflow list/show`; write a `manifest.json` into every run artifact directory with workflow, agent, policy, repo, test command, and runtime metadata. This makes the design document's "external orchestration layer" visible and auditable without introducing SQLite, queues, or new execution semantics yet.

**Tech Stack:** Python 3.11+, pydantic v2, argparse, pytest. No network, no real Claude/Codex/tmux in tests. Source design: `docs/multi_agent_orchestrator_design.md`; existing contracts: `macr/schemas.py`, `macr/cli.py`, `macr/runlog.py`, `docs/workflow_templates.md`.

---

## File Structure

- Modify: `macr/schemas.py` — add typed orchestration registry models.
- Create: `macr/workflows.py` — built-in workflow template registry and lookup helpers.
- Modify: `macr/runlog.py` — write `manifest.json` for every run.
- Modify: `macr/orchestrator.py` — write a manifest for `run`.
- Modify: `macr/collab_orchestrator.py` — write a manifest for `collab`.
- Modify: `macr/discussion.py` — write a manifest for `discuss`.
- Modify: `macr/cli.py` — add `macr workflow list/show`; pass workflow/runtime metadata into manifests.
- Tests: `tests/test_schemas.py`, `tests/test_workflows.py`, `tests/test_runlog.py`, `tests/test_cli_workflow.py`, targeted additions to `tests/test_cli.py`, `tests/test_collab_orchestrator.py`, and `tests/test_discussion.py`.
- Docs: update `README.md`, `docs/workflow_templates.md`, and `CHANGELOG.md` after implementation commits.

## Phase 1 — Typed Registry Models

### Task 1: Add Task / Agent / Policy / Workflow schemas

**Files:**
- Modify: `macr/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_schemas.py`:

```python
from macr.schemas import AgentSpec, PolicySpec, TaskSpec, WorkflowStep, WorkflowTemplate


def test_task_spec_defaults_and_acceptance_criteria():
    task = TaskSpec(goal="fix tests", repo="/tmp/repo", acceptance=["pytest passes"])
    assert task.goal == "fix tests"
    assert task.inputs == []
    assert task.constraints == []
    assert task.acceptance == ["pytest passes"]


def test_agent_spec_records_backend_and_role():
    agent = AgentSpec(agent_id="codex-worker", role="executor", backend="codex_cli")
    assert agent.agent_id == "codex-worker"
    assert agent.role == "executor"
    assert agent.backend == "codex_cli"
    assert agent.capabilities == []


def test_policy_spec_has_gates_and_validation_commands():
    policy = PolicySpec(
        name="code-change",
        required_gates=["tests", "review", "human"],
        validation_commands=["pytest -q"],
    )
    assert policy.required_gates == ["tests", "review", "human"]
    assert policy.validation_commands == ["pytest -q"]


def test_workflow_template_roundtrip():
    wf = WorkflowTemplate(
        workflow_id="execute-review",
        name="Execute Review Revise",
        description="Planner to executor to reviewer",
        steps=[
            WorkflowStep(stage="plan", role="planner", agent_id="claude-planner"),
            WorkflowStep(stage="execute", role="executor", agent_id="codex-worker"),
        ],
        default_policy="code-change",
    )
    assert wf.workflow_id == "execute-review"
    assert wf.steps[1].stage == "execute"
    assert wf.default_policy == "code-change"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schemas.py -q`

Expected: FAIL with `ImportError: cannot import name 'AgentSpec'`.

- [ ] **Step 3: Add the minimal implementation**

Append this block in `macr/schemas.py` before `Message`:

```python
class TaskSpec(BaseModel):
    goal: str
    repo: str | None = None
    inputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)


class AgentSpec(BaseModel):
    agent_id: str
    role: str
    backend: str
    model: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class PolicySpec(BaseModel):
    name: str
    required_gates: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    max_revisions: int = 2
    human_approval_required: bool = True


class WorkflowStep(BaseModel):
    stage: str
    role: str
    agent_id: str
    description: str = ""


class WorkflowTemplate(BaseModel):
    workflow_id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    default_policy: str
    tags: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add orchestration registry models"
```

## Phase 2 — Built-In Workflow Registry

### Task 2: Add built-in workflow templates

**Files:**
- Create: `macr/workflows.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflows.py`:

```python
import pytest

from macr.workflows import WorkflowNotFound, get_workflow, list_workflows


def test_list_workflows_includes_existing_command_shapes():
    ids = [w.workflow_id for w in list_workflows()]
    assert ids == sorted(ids)
    assert "minimal-loop" in ids
    assert "execute-review-revise" in ids
    assert "discussion-consensus" in ids
    assert "tmux-worker" in ids


def test_get_workflow_returns_template():
    wf = get_workflow("discussion-consensus")
    assert wf.default_policy == "code-change"
    assert [s.stage for s in wf.steps] == [
        "independent-plan",
        "discussion",
        "consensus",
        "plan-review",
        "human-consensus-gate",
        "execute",
        "test",
        "code-review",
        "human-final-gate",
    ]


def test_get_workflow_rejects_unknown_id():
    with pytest.raises(WorkflowNotFound) as exc:
        get_workflow("missing")
    assert "missing" in str(exc.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_workflows.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'macr.workflows'`.

- [ ] **Step 3: Add the implementation**

Create `macr/workflows.py`:

```python
from __future__ import annotations

from macr.schemas import WorkflowStep, WorkflowTemplate


class WorkflowNotFound(KeyError):
    pass


_WORKFLOWS = {
    "minimal-loop": WorkflowTemplate(
        workflow_id="minimal-loop",
        name="Minimal Loop",
        description="Single-model planner/executor/reviewer/evaluator loop.",
        default_policy="code-change",
        tags=["v1", "single-model"],
        steps=[
            WorkflowStep(stage="plan", role="planner", agent_id="api-planner"),
            WorkflowStep(stage="execute", role="executor", agent_id="api-executor"),
            WorkflowStep(stage="review", role="reviewer", agent_id="api-reviewer"),
            WorkflowStep(stage="evaluate", role="evaluator", agent_id="deterministic-evaluator"),
            WorkflowStep(stage="human-gate", role="human", agent_id="human"),
        ],
    ),
    "execute-review-revise": WorkflowTemplate(
        workflow_id="execute-review-revise",
        name="Execute Review Revise",
        description="Claude plans/reviews while Codex executes in an isolated worktree.",
        default_policy="code-change",
        tags=["v1", "collab", "code"],
        steps=[
            WorkflowStep(stage="plan", role="planner", agent_id="claude-planner"),
            WorkflowStep(stage="execute", role="executor", agent_id="codex-worker"),
            WorkflowStep(stage="test", role="tester", agent_id="local-test-runner"),
            WorkflowStep(stage="review", role="reviewer", agent_id="claude-reviewer"),
            WorkflowStep(stage="evaluate", role="evaluator", agent_id="deterministic-evaluator"),
            WorkflowStep(stage="human-final-gate", role="human", agent_id="human"),
        ],
    ),
    "discussion-consensus": WorkflowTemplate(
        workflow_id="discussion-consensus",
        name="Discussion To Consensus",
        description="Claude and Codex independently plan, debate, reach consensus, then execute.",
        default_policy="code-change",
        tags=["v1", "discussion", "code"],
        steps=[
            WorkflowStep(stage="independent-plan", role="planner", agent_id="claude-and-codex"),
            WorkflowStep(stage="discussion", role="discussant", agent_id="claude-and-codex"),
            WorkflowStep(stage="consensus", role="consensus", agent_id="claude"),
            WorkflowStep(stage="plan-review", role="reviewer", agent_id="codex"),
            WorkflowStep(stage="human-consensus-gate", role="human", agent_id="human"),
            WorkflowStep(stage="execute", role="executor", agent_id="codex-worker"),
            WorkflowStep(stage="test", role="tester", agent_id="local-test-runner"),
            WorkflowStep(stage="code-review", role="reviewer", agent_id="claude"),
            WorkflowStep(stage="human-final-gate", role="human", agent_id="human"),
        ],
    ),
    "tmux-worker": WorkflowTemplate(
        workflow_id="tmux-worker",
        name="Observable Tmux Worker",
        description="The Worker runs inside a tmux pane through TmuxExecutorBackend.",
        default_policy="code-change",
        tags=["v3", "tmux", "observable"],
        steps=[
            WorkflowStep(stage="spawn-pane", role="runtime", agent_id="tmux-runtime"),
            WorkflowStep(stage="execute", role="executor", agent_id="codex-worker-pane"),
            WorkflowStep(stage="observe", role="observer", agent_id="agent-observer"),
            WorkflowStep(stage="snapshot", role="artifact", agent_id="tmux-runtime"),
            WorkflowStep(stage="validate", role="evaluator", agent_id="deterministic-evaluator"),
        ],
    ),
}


def list_workflows() -> list[WorkflowTemplate]:
    return [_WORKFLOWS[k] for k in sorted(_WORKFLOWS)]


def get_workflow(workflow_id: str) -> WorkflowTemplate:
    try:
        return _WORKFLOWS[workflow_id]
    except KeyError as exc:
        raise WorkflowNotFound(f"unknown workflow: {workflow_id}") from exc
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_workflows.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/workflows.py tests/test_workflows.py
git commit -m "feat(workflows): add built-in orchestration registry"
```

## Phase 3 — CLI Introspection

### Task 3: Add `macr workflow list/show`

**Files:**
- Modify: `macr/cli.py`
- Test: `tests/test_cli_workflow.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_workflow.py`:

```python
from macr import cli


def test_workflow_list_prints_builtin_ids(capsys):
    rc = cli.main(["workflow", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "minimal-loop" in out
    assert "discussion-consensus" in out
    assert "tmux-worker" in out


def test_workflow_show_prints_json(capsys):
    rc = cli.main(["workflow", "show", "discussion-consensus"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"workflow_id": "discussion-consensus"' in out
    assert '"stage": "plan-review"' in out


def test_workflow_show_unknown_returns_two(capsys):
    rc = cli.main(["workflow", "show", "missing"])
    assert rc == 2
    assert "unknown workflow" in capsys.readouterr().err
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_workflow.py -q`

Expected: FAIL because `workflow` is not a known command.

- [ ] **Step 3: Add CLI parsing and command handler**

Modify `_parse_args` in `macr/cli.py` after the `web` parser:

```python
    workflow_p = sub.add_parser("workflow", help="inspect built-in orchestration workflows")
    workflow_sub = workflow_p.add_subparsers(dest="workflow_command", required=True)
    workflow_sub.add_parser("list", help="list built-in workflow templates")
    workflow_show = workflow_sub.add_parser("show", help="show a workflow template as JSON")
    workflow_show.add_argument("workflow_id", help="workflow id, e.g. discussion-consensus")
```

Add this function near `_web_command`:

```python
def _workflow_command(args) -> int:
    from macr.workflows import WorkflowNotFound, get_workflow, list_workflows

    if args.workflow_command == "list":
        for wf in list_workflows():
            print(f"{wf.workflow_id}\t{wf.name}\t{','.join(wf.tags)}")
        return 0
    try:
        wf = get_workflow(args.workflow_id)
    except WorkflowNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(wf.model_dump_json(indent=2))
    return 0
```

Modify `main` before the `web` branch:

```python
    if args.command == "workflow":
        return _workflow_command(args)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_workflow.py tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/cli.py tests/test_cli_workflow.py
git commit -m "feat(cli): add workflow registry introspection"
```

## Phase 4 — Run Manifest Metadata

### Task 4: Add `RunLog.write_manifest`

**Files:**
- Modify: `macr/runlog.py`
- Test: `tests/test_runlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runlog.py`:

```python
import json


def test_write_manifest_records_workflow_and_runtime(tmp_path):
    log = RunLog(tmp_path / "R1")
    log.write_manifest({
        "workflow_id": "discussion-consensus",
        "worker_runtime": "tmux",
        "agents": ["claude", "codex"],
    })
    data = json.loads((tmp_path / "R1" / "manifest.json").read_text())
    assert data["workflow_id"] == "discussion-consensus"
    assert data["worker_runtime"] == "tmux"
    assert data["agents"] == ["claude", "codex"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runlog.py -q`

Expected: FAIL with `AttributeError: 'RunLog' object has no attribute 'write_manifest'`.

- [ ] **Step 3: Add implementation**

Append to `RunLog` in `macr/runlog.py`:

```python
    def write_manifest(self, content: dict) -> None:
        self._write("manifest.json", json.dumps(content, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runlog.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/runlog.py tests/test_runlog.py
git commit -m "feat(runlog): write run manifest metadata"
```

### Task 5: Write manifests from `run`, `collab`, and `discuss`

**Files:**
- Modify: `macr/orchestrator.py`
- Modify: `macr/collab_orchestrator.py`
- Modify: `macr/discussion.py`
- Test: `tests/test_cli.py`, `tests/test_collab_orchestrator.py`, `tests/test_discussion.py`

- [ ] **Step 1: Write the failing tests**

Add a manifest assertion to an existing successful `run` CLI test in `tests/test_cli.py`:

```python
import json


def test_run_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "build a thing", "--yes"],
        llm=_scripted_llm(),
    )
    assert rc == 0
    manifest = next((tmp_path / ".macr" / "runs").glob("*/manifest.json"))
    data = json.loads(manifest.read_text())
    assert data["command"] == "run"
    assert data["workflow_id"] == "minimal-loop"
    assert data["agents"] == ["anthropic-api"]
```

Add equivalent assertions to the existing happy-path collab and discuss tests:

```python
manifest = json.loads((run_path / "manifest.json").read_text())
assert manifest["workflow_id"] == "execute-review-revise"
assert manifest["command"] == "collab"
assert manifest["worker_runtime"] == "cli"
```

```python
manifest = json.loads((run_path / "manifest.json").read_text())
assert manifest["workflow_id"] == "discussion-consensus"
assert manifest["command"] == "discuss"
assert manifest["worker_runtime"] == "cli"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py::test_run_writes_manifest tests/test_collab_orchestrator.py tests/test_discussion.py -q
```

Expected: FAIL because `manifest.json` is not written.

- [ ] **Step 3: Add manifest writes**

In `macr/orchestrator.py`, after `log.write_input(task)`, add:

```python
    log.write_manifest({
        "command": "run",
        "workflow_id": "minimal-loop",
        "task": task,
        "agents": ["anthropic-api"],
        "policy": "code-change",
    })
```

In `macr/collab_orchestrator.py`, after `log.write_input(task)`, add:

```python
    log.write_manifest({
        "command": "collab",
        "workflow_id": "execute-review-revise",
        "task": task,
        "repo": str(repo),
        "test_cmd": test_cmd,
        "agents": [getattr(claude_backend, "name", "claude"), getattr(codex_backend, "name", "codex")],
        "worker_runtime": getattr(worker_backend, "name", "cli") if worker_backend is not None else "cli",
        "policy": "code-change",
    })
```

In `macr/discussion.py`, after `log._write("topic.md", f"{topic}\n")`, add:

```python
    log.write_manifest({
        "command": "discuss",
        "workflow_id": "discussion-consensus",
        "task": topic,
        "repo": str(repo),
        "test_cmd": test_cmd,
        "agents": [
            getattr(claude_backend, "name", "claude"),
            getattr(codex_backend, "name", "codex"),
            getattr(impl_codex_backend, "name", "codex"),
        ],
        "worker_runtime": getattr(worker_backend, "name", "cli") if worker_backend is not None else "cli",
        "policy": "code-change",
    })
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_collab_orchestrator.py tests/test_discussion.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macr/orchestrator.py macr/collab_orchestrator.py macr/discussion.py tests/test_cli.py tests/test_collab_orchestrator.py tests/test_discussion.py
git commit -m "feat(runs): write orchestration manifest for each run"
```

## Phase 5 — Documentation And Changelog

### Task 6: Document registry and manifest behavior

**Files:**
- Modify: `README.md`
- Modify: `docs/workflow_templates.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add doc assertions**

Append to `tests/test_smoke.py`:

```python
def test_docs_mention_workflow_registry_and_manifest():
    readme = Path("README.md").read_text(encoding="utf-8")
    workflows = Path("docs/workflow_templates.md").read_text(encoding="utf-8")
    assert "macr workflow list" in readme
    assert "manifest.json" in readme
    assert "workflow_id" in workflows
```

- [ ] **Step 2: Run red**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -q`

Expected: FAIL until docs mention the new surfaces.

- [ ] **Step 3: Update docs**

Add to `README.md` under "现在能做什么":

```markdown
| `workflow` | 查看内置编排模板: `macr workflow list` / `macr workflow show discussion-consensus` | 无 |
```

Add to `README.md` under "产物":

```text
manifest.json             # command / workflow_id / agents / policy / runtime metadata
```

Add to `docs/workflow_templates.md` near the top:

```markdown
每个模板都有稳定的 `workflow_id`, 可通过 `macr workflow list` 与
`macr workflow show <workflow_id>` 查看。每次运行都会把所用模板与运行时元数据写入
`.macr/runs/<run_id>/manifest.json`, 便于审计和后续 Web/SQLite 投影。
```

Append to `CHANGELOG.md` `[Unreleased]`:

```markdown
### Added
- 新增编排注册表模型、内置 workflow 模板查询命令与 run `manifest.json` 元数据,
  让 MACR 的 Task/Agent/Policy/Workflow 抽象可查询、可追溯。`(commit 待填)`
  依据 `docs/multi_agent_orchestrator_design.md` 与
  `docs/superpowers/plans/2026-06-27-multi-agent-orchestrator-registry.md`。
```

- [ ] **Step 4: Run full verification**

Run:

```bash
.venv/bin/python -m pytest
cd frontend && npm test -- --run
```

Expected: backend and frontend tests pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/workflow_templates.md CHANGELOG.md tests/test_smoke.py
git commit -m "docs: document workflow registry and run manifests"
```

## Self-Review

- **Spec coverage:** This plan implements the design doc's durable abstractions (`Task`, `Agent`, `State`, `Policy`, workflow lifecycle) as queryable metadata while preserving the already-working execution loops. It intentionally leaves SQLite, async queues, LangGraph/CrewAI adapters, and scientific workflow execution templates for later milestones.
- **Placeholder scan:** No task depends on "TBD" implementation. Every task has exact files, tests, implementation snippets, commands, and commit messages.
- **Type consistency:** `WorkflowTemplate`, `WorkflowStep`, `AgentSpec`, `TaskSpec`, and `PolicySpec` are defined once in `macr/schemas.py` and reused from `macr/workflows.py`. `manifest.json` is plain JSON dict content written by `RunLog.write_manifest`.
- **Risk:** The only user-facing behavior change is a new `workflow` subcommand and extra `manifest.json` files in run artifacts. Existing `run`/`collab`/`discuss` behavior must remain byte-for-byte compatible except for the added artifact.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-27-multi-agent-orchestrator-registry.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh worker per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, with checkpoints after each phase.
