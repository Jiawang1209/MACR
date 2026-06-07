# MACR Stage C1 — Human-Interjectable Discussion-to-Consensus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `macr discuss "<topic>" --repo <p> --test-cmd "..."`: Claude and Codex each plan from the topic, discuss over rounds (the human can interject at each round boundary), Claude synthesizes a consensus, the human confirms it, then the existing Stage A implementation loop runs — all printed turn-by-turn.

**Architecture:** Extract Stage A's implementation loop into a reusable `_implementation_loop`. A new `discussion.py` orchestrates dual-planning → human-interjectable rounds → Claude consensus → human gate① → `_implementation_loop` → human gate②. Discussion uses new role specs (`discuss_roles.py`) whose `build_user` reads the topic + a growing transcript (including human interjections). A `discussion_control` callable (injectable) drives the per-round `continue/interject/end/abort` choice.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest. **Isolation:** `.venv/bin/...` only. Commits: plain, NO Co-Authored-By / AI attribution. One git command at a time.

**Spec:** `docs/superpowers/specs/2026-06-07-macr-stage-c-discussion-consensus-design.md`.

**Current interfaces (verified, do not break):**
- `macr/collab_orchestrator.py`: `run_collab(...)`, `_build_final`, `_record_subagents`. The loop body is lines ~89-135 (executor→diff→test→review→eval + `except AgentError`).
- `macr/collab_roles.py`: `PLANNER_C`, `EXECUTOR_C`, `REVIEWER_C`, `_latest`.
- `macr/agents/base.py`: `FakeAgentBackend(scripted, on_run=None, subagents=None)`, `run_role(..., trace=None)`.
- `macr/agents/cli_backend.py`: `CodexCliBackend(..., sandbox="workspace-write", ..., enable_subagents=True)`.
- `macr/human_gate.py`: `collab_human_gate`, `_prompt_decision(input_fn, printer, ts)`.
- `macr/runlog.py`: `RunLog(run_path)` with `self.run_path`, `_write`, `write_input/write_planner/.../write_state`.
- `macr/schemas.py`: `SharedState(run_id, user_query, ...)` (has `run_id`, `agent_outputs`, `diffs`, `test_results`, `subagents`, `decisions`, `reviews`, `human_feedback`, `final_output`); `PlannerOutput`, `MessageType`, `HumanFeedback`. `MessageType` has `PROPOSAL`, `CRITIQUE`, `DECISION`.
- `macr/utils.py`: `next_run_id`. `macr/worktree.py`: `Worktree`.

**Conventions:** TDD per task (red → green → commit). 117 tests currently pass; keep them green.

---

### Task 1: Refactor — extract `_implementation_loop` from `run_collab`

**Files:** Modify `macr/collab_orchestrator.py`. (No new test; Stage A's `tests/test_collab_orchestrator.py` + `tests/test_collab_orchestrator_subagents.py` are the regression gate.)

- [ ] **Step 1: Replace the body of `run_collab` and add `_implementation_loop`.** Keep `_record_subagents` and `_build_final` unchanged. Replace everything from `def run_collab(` to the end of the file with:
```python
def _implementation_loop(
    state: SharedState,
    *,
    run_path: Path,
    log: RunLog,
    worktree: Worktree,
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,
    test_cmd: list[str],
    max_revisions: int,
    timeout: int,
    printer: Callable[..., None],
) -> None:
    """Shared executor→diff→test→review→eval revision loop (Stage A + Stage C)."""
    try:
        total_attempts = max_revisions + 1
        for attempt in range(1, total_attempts + 1):
            exec_sink = TraceSink(run_path / "subagents", f"executor.v{attempt}")
            exec_msg = codex_backend.run_role(
                EXECUTOR_C, state, run_id=state.run_id, task_id=state.run_id, trace=exec_sink)
            state.agent_outputs["executor"].append(exec_msg.content)
            log.write_executor(exec_msg.content, attempt)
            _record_subagents(state, exec_sink, "executor", attempt)

            diff = worktree.diff()
            state.diffs.append(diff)
            log.write_diff(diff, attempt)

            tr: TestResult = run_tests(worktree.path, test_cmd, timeout)
            state.test_results.append(tr.model_dump())
            log.write_test(tr.model_dump(), tr.log, attempt)
            printer(f"[tests #{attempt}] passed={tr.passed}")

            review_sink = TraceSink(run_path / "subagents", f"reviewer.v{attempt}")
            review_msg = claude_backend.run_role(
                REVIEWER_C, state, run_id=state.run_id, task_id=state.run_id, trace=review_sink)
            state.agent_outputs["reviewer"].append(review_msg.content)
            state.reviews.append(review_msg.content)
            log.write_reviewer(review_msg.content)
            _record_subagents(state, review_sink, "reviewer", attempt)
            printer(f"[reviewer] {review_msg.content.get('decision', '')}")

            decision = evaluate_collab(test_result=tr, reviewer=review_msg.content, agent_failed=False)
            state.decisions.append({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
            log.write_evaluator({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
            printer(f"[evaluator] {decision.value}")

            if decision in (Decision.PASS, Decision.BLOCKED):
                break
            if attempt >= total_attempts:
                break
    except AgentError as exc:
        record = {
            "attempt": len(state.decisions) + 1,
            "decision": Decision.BLOCKED.value,
            "test_passed": False,
            "error": str(exc),
        }
        state.decisions.append(record)
        log.write_evaluator(record)
        printer(f"[blocked] {exc}")


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
            planner_sink = TraceSink(run_path / "subagents", "planner.v1")
            planner_msg = claude_backend.run_role(
                PLANNER_C, state, run_id=run_id, task_id=run_id, trace=planner_sink)
            state.agent_outputs["planner"].append(planner_msg.content)
            state.task_plan = list(planner_msg.content.get("steps", []))
            log.write_planner(planner_msg.content)
            _record_subagents(state, planner_sink, "planner", 1)
            printer(f"[planner] {planner_msg.content.get('summary', '')}")
        except AgentError as exc:
            record = {
                "attempt": len(state.decisions) + 1,
                "decision": Decision.BLOCKED.value,
                "test_passed": False,
                "error": str(exc),
            }
            state.decisions.append(record)
            log.write_evaluator(record)
            printer(f"[blocked] {exc}")
        else:
            _implementation_loop(
                state, run_path=run_path, log=log, worktree=worktree,
                claude_backend=claude_backend, codex_backend=codex_backend,
                test_cmd=test_cmd, max_revisions=max_revisions, timeout=timeout, printer=printer)

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

- [ ] **Step 2: Run the Stage A regression suites, expect ALL PASS** — `.venv/bin/pytest tests/test_collab_orchestrator.py tests/test_collab_orchestrator_subagents.py -v`. If any fail, the refactor changed behavior — fix before committing.

- [ ] **Step 3: Run FULL suite** — `.venv/bin/pytest -q` (expect 117 passed).

- [ ] **Step 4: Commit**
```bash
git add macr/collab_orchestrator.py
git commit -m "refactor: extract shared _implementation_loop from run_collab"
```

---

### Task 2: `schemas.py` — DiscussionTurn, ConsensusPlan, SharedState fields

**Files:** Modify `macr/schemas.py`; Create `tests/test_schemas_discussion.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_schemas_discussion.py`:
```python
from macr.schemas import ConsensusPlan, DiscussionTurn, SharedState


def test_discussion_turn_defaults():
    t = DiscussionTurn(response="I disagree about X")
    assert t.agreements == [] and t.concerns == [] and t.revised_steps == []


def test_consensus_plan():
    c = ConsensusPlan(summary="do it", steps=["a", "b"], rationale="because")
    assert c.open_questions == []


def test_shared_state_discussion_fields_default():
    s = SharedState(run_id="R1", user_query="q")
    assert s.topic is None
    assert s.discussion == []
    assert s.consensus is None


def test_shared_state_discussion_roundtrip():
    s = SharedState(run_id="R1", user_query="q", topic="build X")
    s.discussion.append({"round": 0, "agent": "claude", "kind": "plan", "content": {"steps": ["a"]}})
    s.consensus = {"summary": "c", "steps": ["a"]}
    d = s.model_dump()
    assert d["topic"] == "build X"
    assert d["discussion"][0]["agent"] == "claude"
    assert d["consensus"]["steps"] == ["a"]
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_schemas_discussion.py -v`.

- [ ] **Step 3: Modify `macr/schemas.py`** — add two models (place after `ConsensusPlan`'s logical home, e.g. after `EvaluatorOutput` or near `TestResult`; `Field` is imported):
```python
class DiscussionTurn(BaseModel):
    response: str
    agreements: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    revised_steps: list[str] = Field(default_factory=list)


class ConsensusPlan(BaseModel):
    summary: str
    steps: list[str]
    rationale: str
    open_questions: list[str] = Field(default_factory=list)
```
and add three fields to `SharedState` (after the existing `subagents` field, keep all others unchanged):
```python
    topic: str | None = None
    discussion: list[dict] = Field(default_factory=list)
    consensus: dict | None = None
```

- [ ] **Step 4: Run new + regression** — `.venv/bin/pytest tests/test_schemas_discussion.py tests/test_schemas.py tests/test_schemas_collab.py tests/test_schemas_subagents.py -v` (all pass).

- [ ] **Step 5: Commit**
```bash
git add macr/schemas.py tests/test_schemas_discussion.py
git commit -m "feat: add DiscussionTurn, ConsensusPlan schemas and SharedState discussion fields"
```

---

### Task 3: `discuss_roles.py` — discussion role specs + transcript renderer

**Files:** Create `macr/discuss_roles.py`, `tests/test_discuss_roles.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_discuss_roles.py`:
```python
from macr.discuss_roles import (
    CONSENSUS,
    DISCUSS_PLANNER,
    DISCUSS_TURN,
    render_transcript,
)
from macr.schemas import ConsensusPlan, DiscussionTurn, MessageType, PlannerOutput, SharedState


def test_role_wiring():
    assert DISCUSS_PLANNER.content_model is PlannerOutput
    assert DISCUSS_TURN.content_model is DiscussionTurn
    assert CONSENSUS.content_model is ConsensusPlan
    assert CONSENSUS.message_type is MessageType.DECISION


def test_planner_user_has_topic_only():
    s = SharedState(run_id="R1", user_query="t", topic="build a parser")
    s.discussion.append({"round": 0, "agent": "claude", "kind": "plan",
                         "content": {"summary": "secret", "steps": ["x"]}})
    user = DISCUSS_PLANNER.build_user(s)
    assert "build a parser" in user
    assert "secret" not in user  # planner is independent; does not see transcript


def test_turn_user_has_topic_and_transcript():
    s = SharedState(run_id="R1", user_query="t", topic="topic-z")
    s.discussion.append({"round": 0, "agent": "codex", "kind": "plan",
                         "content": {"summary": "plan-b", "steps": ["step-b"]}})
    user = DISCUSS_TURN.build_user(s)
    assert "topic-z" in user and "plan-b" in user and "step-b" in user


def test_turn_user_includes_human_interjection():
    s = SharedState(run_id="R1", user_query="t", topic="z")
    s.discussion.append({"round": 1, "agent": "human", "kind": "interjection",
                         "content": "please prioritize zero downtime"})
    assert "zero downtime" in DISCUSS_TURN.build_user(s)


def test_render_transcript_orders_and_renders_kinds():
    disc = [
        {"round": 0, "agent": "claude", "kind": "plan", "content": {"summary": "s", "steps": ["a"]}},
        {"round": 1, "agent": "codex", "kind": "turn",
         "content": {"response": "r", "agreements": ["x"], "concerns": ["y"], "revised_steps": ["z"]}},
        {"round": 1, "agent": "human", "kind": "interjection", "content": "hi"},
    ]
    text = render_transcript(disc)
    assert "claude" in text and "codex" in text and "human" in text
    assert "a" in text and "r" in text and "hi" in text
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discuss_roles.py -v`.

- [ ] **Step 3: Implement `macr/discuss_roles.py`:**
```python
from __future__ import annotations

from macr.roles import RoleSpec
from macr.schemas import (
    ConsensusPlan,
    DiscussionTurn,
    MessageType,
    PlannerOutput,
    SharedState,
)


def render_transcript(discussion: list[dict]) -> str:
    """Render the ordered discussion records into human-readable text."""
    blocks: list[str] = []
    for e in discussion:
        head = f"[round {e.get('round')} · {e.get('agent')} · {e.get('kind')}]"
        content = e.get("content")
        if isinstance(content, str):
            body = content
        elif e.get("kind") == "plan":
            steps = "\n".join(f"  - {s}" for s in (content or {}).get("steps", []))
            body = f"summary: {(content or {}).get('summary', '')}\nsteps:\n{steps}"
        else:  # turn
            c = content or {}
            agreements = ", ".join(c.get("agreements", []))
            concerns = ", ".join(c.get("concerns", []))
            revised = "\n".join(f"  - {s}" for s in c.get("revised_steps", []))
            body = (
                f"response: {c.get('response', '')}\n"
                f"agreements: {agreements}\nconcerns: {concerns}\nrevised_steps:\n{revised}"
            )
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def _planner_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        "目标代码仓库已在工作目录就绪(只读)。请【独立】基于该主题制定你的实现方案:"
        "summary / steps / tools_needed / risks。只出方案,不写代码,不要参考他人方案。"
    )


def _turn_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        f"目前为止的完整讨论记录(含对方方案、历轮发言、以及人的插话):\n"
        f"{render_transcript(state.discussion)}\n\n"
        "请基于以上给出你这一轮:response(论点/回应)、agreements(认同对方哪些点)、"
        "concerns(对对方方案的异议)、revised_steps(综合后你更新的计划步骤)。"
    )


def _consensus_user(state: SharedState) -> str:
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        f"完整讨论记录:\n{render_transcript(state.discussion)}\n\n"
        "请综合双方讨论(并尊重人的插话),产出共识实现方案:summary / steps / rationale / open_questions。"
    )


DISCUSS_PLANNER = RoleSpec(
    name="discuss_planner", agent_id="discuss_planner", tool_name="submit_plan",
    message_type=MessageType.PROPOSAL, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 讨论中的规划者。独立地、只基于主题给出你自己的实现方案。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_planner_user,
)

DISCUSS_TURN = RoleSpec(
    name="discuss_turn", agent_id="discuss_turn", tool_name="submit_turn",
    message_type=MessageType.CRITIQUE, content_model=DiscussionTurn,
    system_prompt=(
        "你是 MACR 讨论中的一位参与者。基于完整讨论记录,真诚地与对方讨论:认同、质疑、补充、修订。"
        "目标是把方案谈得更好,而非迎合。输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_turn_user,
)

CONSENSUS = RoleSpec(
    name="consensus", agent_id="consensus", tool_name="submit_consensus",
    message_type=MessageType.DECISION, content_model=ConsensusPlan,
    system_prompt=(
        "你是 MACR 的共识汇总者(由 Claude 扮演)。综合整场讨论,产出一份双方认可、可执行的共识方案。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_consensus_user,
)
```

- [ ] **Step 4: Run, expect PASS (5 passed)** — `.venv/bin/pytest tests/test_discuss_roles.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/discuss_roles.py tests/test_discuss_roles.py
git commit -m "feat: add discussion role specs and transcript renderer"
```

---

### Task 4: `discussion_control` + `consensus_human_gate`

**Files:** Create `macr/discussion_control.py`; Modify `macr/human_gate.py`; Create `tests/test_discussion_control.py`, `tests/test_consensus_gate.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_discussion_control.py`:
```python
from macr.discussion_control import (
    ControlDecision,
    auto_discussion_control,
    interactive_discussion_control,
)
from macr.schemas import SharedState


def _state():
    return SharedState(run_id="R1", user_query="q", topic="z")


def test_auto_always_continue():
    d = auto_discussion_control(_state(), 1, printer=lambda *_: None)
    assert d.action == "continue" and d.interjection == ""


def test_interactive_continue():
    d = interactive_discussion_control(_state(), 1, input_fn=lambda p: "c", printer=lambda *_: None)
    assert d.action == "continue"


def test_interactive_interject():
    answers = iter(["i", "please add rollback"])
    d = interactive_discussion_control(_state(), 1, input_fn=lambda p: next(answers), printer=lambda *_: None)
    assert d.action == "interject" and d.interjection == "please add rollback"


def test_interactive_end_and_abort():
    assert interactive_discussion_control(_state(), 1, input_fn=lambda p: "e", printer=lambda *_: None).action == "end"
    assert interactive_discussion_control(_state(), 1, input_fn=lambda p: "a", printer=lambda *_: None).action == "abort"


def test_control_decision_default():
    assert ControlDecision(action="continue").interjection == ""
```

`tests/test_consensus_gate.py`:
```python
from macr.human_gate import consensus_human_gate
from macr.schemas import SharedState


def _state():
    s = SharedState(run_id="R1", user_query="q", topic="z")
    s.consensus = {"summary": "agreed plan", "steps": ["s1", "s2"], "rationale": "r", "open_questions": []}
    return s


def test_consensus_gate_shows_consensus_and_approves():
    out = []
    hf = consensus_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    assert hf.decision == "approve"
    assert any("agreed plan" in line for line in out)


def test_consensus_gate_reject():
    answers = iter(["r", "not good"])
    hf = consensus_human_gate(_state(), input_fn=lambda p: next(answers), printer=lambda *_: None, timestamp="t")
    assert hf.decision == "reject" and hf.feedback == "not good"
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discussion_control.py tests/test_consensus_gate.py -v`.

- [ ] **Step 3a: Implement `macr/discussion_control.py`:**
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from macr.schemas import SharedState


@dataclass
class ControlDecision:
    action: str  # "continue" | "interject" | "end" | "abort"
    interjection: str = ""


def interactive_discussion_control(
    state: SharedState,
    round_no: int,
    *,
    input_fn: Callable[[str], str] = input,
    printer: Callable[..., None] = print,
) -> ControlDecision:
    printer(f"\n── 回合 {round_no} 边界 ── [c]继续 / [i]插话 / [e]提前定稿 / [a]中止")
    choice = input_fn("> ").strip().lower()
    if choice.startswith("i"):
        text = input_fn("你的插话 / Your message: ").strip()
        return ControlDecision(action="interject", interjection=text)
    if choice.startswith("e"):
        return ControlDecision(action="end")
    if choice.startswith("a"):
        return ControlDecision(action="abort")
    return ControlDecision(action="continue")


def auto_discussion_control(
    state: SharedState, round_no: int, *, printer: Callable[..., None] = print
) -> ControlDecision:
    return ControlDecision(action="continue")
```

- [ ] **Step 3b: Add `consensus_human_gate` to `macr/human_gate.py`** (reuse the existing `_prompt_decision`; append this function):
```python
def consensus_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] = input,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    ts = timestamp or now_iso()
    c = state.consensus or {}
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(c.get("steps", []), 1))
    printer("\n===== Human Gate (consensus) =====")
    printer(f"Topic: {state.topic}")
    printer(f"\n--- Consensus ---\n{c.get('summary', '')}\n{steps}")
    if c.get("open_questions"):
        printer("Open questions: " + "; ".join(c.get("open_questions", [])))
    return _prompt_decision(input_fn, printer, ts)
```

- [ ] **Step 4: Run new + regression** — `.venv/bin/pytest tests/test_discussion_control.py tests/test_consensus_gate.py tests/test_human_gate.py tests/test_human_gate_collab.py -v` (new pass; existing gate tests still pass).

- [ ] **Step 5: Commit**
```bash
git add macr/discussion_control.py macr/human_gate.py tests/test_discussion_control.py tests/test_consensus_gate.py
git commit -m "feat: add discussion round-boundary control and consensus human gate"
```

---

### Task 5: `discussion.py` — the `run_discuss` orchestrator

**Files:** Create `macr/discussion.py`, `tests/test_discussion.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_discussion.py`:
```python
import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.discussion import run_discuss
from macr.discussion_control import ControlDecision
from macr.schemas import HumanFeedback


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _plan(tag):
    return {"summary": f"plan-{tag}", "steps": [f"step-{tag}"], "tools_needed": [], "risks": []}


def _turn(tag):
    return {"response": f"resp-{tag}", "agreements": [], "concerns": [], "revised_steps": [f"rev-{tag}"]}


def _consensus():
    return {"summary": "agreed", "steps": ["do-1", "do-2"], "rationale": "r", "open_questions": []}


def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path) / "a.txt").write_text("changed\n")


def _approve(state, **kw):
    return HumanFeedback(decision="approve", feedback="", timestamp="t")


def _build(tmp_path, *, control_actions, max_rounds=2, consensus_gate=_approve, final_gate=_approve):
    repo = tmp_path / "repo"
    _init_repo(repo)
    # claude: dual-plan + each round turn + consensus + reviewer
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1"), _turn("c2"), _turn("c3")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")],
        "discuss_turn": [_turn("x1"), _turn("x2"), _turn("x3")],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    actions = iter(control_actions)
    def control(state, round_no, **kw):
        return next(actions)
    return run_discuss(
        "build a thing", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=max_rounds, max_revisions=2,
        consensus_gate=consensus_gate, human_gate=final_gate, discussion_control=control,
        printer=lambda *_: None, today="20260607",
    )


def test_full_flow_to_implementation(tmp_path):
    # round0 boundary -> continue; round1 boundary -> end (skip to consensus)
    state = _build(tmp_path, control_actions=[ControlDecision("continue"), ControlDecision("end")])
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "discussion" / "plan.claude.md").exists()
    assert (run_path / "discussion" / "plan.codex.md").exists()
    assert (run_path / "discussion" / "transcript.md").exists()
    assert (run_path / "consensus.md").exists()
    # consensus steps fed implementation; reviewer approved -> PASS
    assert state.consensus["steps"] == ["do-1", "do-2"]
    assert state.decisions[-1]["decision"] == "PASS"
    assert state.human_feedback.decision == "approve"
    assert "changed" in (run_path / "diff.v1.patch").read_text()
    saved = json.loads((run_path / "state.json").read_text())
    assert any(e["agent"] == "claude" and e["kind"] == "plan" for e in saved["discussion"])


def test_human_interjection_enters_transcript(tmp_path):
    state = _build(tmp_path, control_actions=[
        ControlDecision("interject", "please prioritize rollback"),
        ControlDecision("end"),
    ], max_rounds=2)
    assert any(e["agent"] == "human" and "rollback" in e["content"] for e in state.discussion)
    run_path = tmp_path / "runs" / "R20260607_001"
    assert "rollback" in (run_path / "discussion" / "transcript.md").read_text()


def test_abort_skips_implementation(tmp_path):
    state = _build(tmp_path, control_actions=[ControlDecision("abort")])
    # no consensus reached, no implementation, no approval
    assert state.consensus is None
    assert state.human_feedback is None
    assert state.decisions == []


def test_consensus_reject_skips_implementation(tmp_path):
    def reject(state, **kw):
        return HumanFeedback(decision="reject", feedback="no", timestamp="t")
    state = _build(tmp_path, control_actions=[ControlDecision("end")], consensus_gate=reject)
    assert state.consensus is not None
    assert state.human_feedback.decision == "reject"
    assert state.decisions == []  # implementation never ran
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_discussion.py -v`.

- [ ] **Step 3: Implement `macr/discussion.py`:**
```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import AgentBackend
from macr.agents.trace import TraceSink
from macr.collab_orchestrator import _build_final, _implementation_loop, _record_subagents
from macr.discuss_roles import CONSENSUS, DISCUSS_PLANNER, DISCUSS_TURN, render_transcript
from macr.discussion_control import ControlDecision, interactive_discussion_control
from macr.human_gate import collab_human_gate, consensus_human_gate
from macr.runlog import RunLog
from macr.schemas import HumanFeedback, SharedState
from macr.utils import next_run_id
from macr.worktree import Worktree

HumanGate = Callable[..., HumanFeedback]
DiscussionControl = Callable[..., ControlDecision]


def _disc_dir(run_path: Path) -> Path:
    d = run_path / "discussion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _print_plan(printer, agent: str, content: dict) -> None:
    printer(f"\n━━━ {agent} · 第 0 轮(计划)━━━")
    printer(content.get("summary", ""))
    for s in content.get("steps", []):
        printer(f"  - {s}")


def _print_turn(printer, agent: str, round_no: int, content: dict) -> None:
    printer(f"\n━━━ {agent} · 第 {round_no} 轮 ━━━")
    if content.get("concerns"):
        printer("[concerns] " + "; ".join(content["concerns"]))
    printer("[response] " + content.get("response", ""))
    if content.get("revised_steps"):
        printer("[revised steps] " + "; ".join(content["revised_steps"]))


def run_discuss(
    topic: str,
    *,
    repo: Path,
    test_cmd: list[str],
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,        # discussion-side Codex (read-only in real use)
    impl_codex_backend: AgentBackend,   # implementation-side Codex (workspace-write)
    runs_dir: Path,
    worktrees_dir: Path,
    max_rounds: int = 3,
    max_revisions: int = 2,
    consensus_gate: HumanGate = consensus_human_gate,
    human_gate: HumanGate = collab_human_gate,
    discussion_control: DiscussionControl = interactive_discussion_control,
    printer: Callable[..., None] = print,
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=topic, topic=topic, target_repo=str(repo))
    log._write("topic.md", f"{topic}\n")
    disc = _disc_dir(run_path)
    worktree: Worktree | None = None
    aborted = False

    def record(round_no, agent, kind, content):
        state.discussion.append({"round": round_no, "agent": agent, "kind": kind, "content": content})

    try:
        worktree = Worktree.create(repo, run_id, worktrees_dir)
        state.worktree_path = str(worktree.path)
        try:
            # --- Round 0: symmetric independent planning ---
            for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                sink = TraceSink(run_path / "subagents", f"plan.{agent}")
                msg = backend.run_role(DISCUSS_PLANNER, state, run_id=run_id, task_id=run_id, trace=sink)
                record(0, agent, "plan", msg.content)
                _record_subagents(state, sink, f"plan.{agent}", 0)
                (disc / f"plan.{agent}.md").write_text(
                    f"# {agent} plan\n\n{msg.content.get('summary','')}\n\n"
                    + "\n".join(f"- {s}" for s in msg.content.get("steps", [])) + "\n",
                    encoding="utf-8")
                _print_plan(printer, agent, msg.content)

            # --- Discussion rounds with human-in-the-loop control ---
            for round_no in range(0, max_rounds + 1):
                if round_no >= 1:
                    for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                        sink = TraceSink(run_path / "subagents", f"turn.{agent}.v{round_no}")
                        msg = backend.run_role(DISCUSS_TURN, state, run_id=run_id, task_id=run_id, trace=sink)
                        record(round_no, agent, "turn", msg.content)
                        _record_subagents(state, sink, f"turn.{agent}", round_no)
                        (disc / f"round{round_no}.{agent}.json").write_text(
                            json.dumps(msg.content, ensure_ascii=False, indent=2), encoding="utf-8")
                        _print_turn(printer, agent, round_no, msg.content)

                decision = discussion_control(state, round_no, printer=printer)
                if decision.action == "abort":
                    aborted = True
                    break
                if decision.action == "interject" and decision.interjection:
                    record(round_no, "human", "interjection", decision.interjection)
                    (disc / f"round{round_no}.human.txt").write_text(decision.interjection + "\n", encoding="utf-8")
                    printer(f"\n━━━ 你(human)· 第 {round_no} 轮后插话 ━━━\n{decision.interjection}")
                if decision.action == "end":
                    break
        except AgentError as exc:
            printer(f"[discussion blocked] {exc}")

        # --- Transcript ---
        (disc / "transcript.md").write_text(render_transcript(state.discussion) + "\n", encoding="utf-8")

        if not aborted:
            # --- Consensus (Claude) ---
            try:
                sink = TraceSink(run_path / "subagents", "consensus")
                cons_msg = claude_backend.run_role(CONSENSUS, state, run_id=run_id, task_id=run_id, trace=sink)
                state.consensus = cons_msg.content
                _record_subagents(state, sink, "consensus", 0)
                c = cons_msg.content
                log._write("consensus.md",
                           f"# Consensus\n\n{c.get('summary','')}\n\n## Steps\n"
                           + "\n".join(f"{i}. {s}" for i, s in enumerate(c.get('steps', []), 1))
                           + f"\n\n## Rationale\n{c.get('rationale','')}\n")
                printer(f"\n━━━ 共识 / Consensus ━━━\n{c.get('summary','')}")
            except AgentError as exc:
                printer(f"[consensus blocked] {exc}")

            # --- Human Gate ① (consensus) ---
            if state.consensus is not None:
                fb1 = consensus_gate(state, printer=printer)
                state.human_feedback = fb1
                printer(f"[human·consensus] {fb1.decision}")
                if fb1.decision == "approve":
                    # feed consensus steps to the implementation loop as the planner output
                    state.agent_outputs["planner"].append({
                        "summary": state.consensus.get("summary", ""),
                        "steps": list(state.consensus.get("steps", [])),
                        "tools_needed": [], "risks": [],
                    })
                    state.task_plan = list(state.consensus.get("steps", []))
                    _implementation_loop(
                        state, run_path=run_path, log=log, worktree=worktree,
                        claude_backend=claude_backend, codex_backend=impl_codex_backend,
                        test_cmd=test_cmd, max_revisions=max_revisions, timeout=timeout, printer=printer)
                    # --- Human Gate ② (final) ---
                    fb2 = human_gate(state, printer=printer)
                    state.human_feedback = fb2
                    printer(f"[human·final] {fb2.decision}")

        final = _build_final(state)
        state.final_output = final
        log.write_final(final)

        if worktree is not None and (
            aborted or (state.human_feedback is not None and state.human_feedback.decision == "reject")
        ):
            worktree.cleanup()
            state.worktree_path = None
    finally:
        log.write_state(state)
    return state
```

- [ ] **Step 4: Run, expect PASS (4 passed)** — `.venv/bin/pytest tests/test_discussion.py -v`.

- [ ] **Step 5: Commit**
```bash
git add macr/discussion.py tests/test_discussion.py
git commit -m "feat: add run_discuss orchestrator with human-interjectable rounds"
```

---

### Task 6: `cli.py` — `macr discuss` subcommand

**Files:** Modify `macr/cli.py`; Create `tests/test_cli_discuss.py`.

- [ ] **Step 1: Write the failing test** — `tests/test_cli_discuss.py`:
```python
import subprocess
from pathlib import Path

from macr import cli
from macr.agents.base import FakeAgentBackend
from macr.discussion_control import ControlDecision
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
        "discuss_planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
        "discuss_turn": [{"response": "r", "agreements": [], "concerns": [], "revised_steps": []}] * 4,
        "consensus": [{"summary": "c", "steps": ["s"], "rationale": "r", "open_questions": []}],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })


def _codex_discuss():
    return FakeAgentBackend({
        "discuss_planner": [{"summary": "p2", "steps": ["s2"], "tools_needed": [], "risks": []}],
        "discuss_turn": [{"response": "r2", "agreements": [], "concerns": [], "revised_steps": []}] * 4,
    })


def _codex_impl():
    def on_run(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")
    return FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=on_run)


def test_discuss_approve_returns_zero(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_discuss_abort_returns_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("abort"),
    )
    assert rc == 1
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_cli_discuss.py -v`.

- [ ] **Step 3: Modify `macr/cli.py`:**

(i) Add the `discuss` subparser inside `_parse_args` (after the `collab` subparser block):
```python
    discuss_p = sub.add_parser("discuss", help="Claude+Codex discuss to consensus, then implement (CLI-only)")
    discuss_p.add_argument("task", help="the topic")
    discuss_p.add_argument("--repo", required=True)
    discuss_p.add_argument("--test-cmd", required=True)
    discuss_p.add_argument("--max-rounds", type=int, default=3)
    discuss_p.add_argument("--max-revisions", type=int, default=2)
    discuss_p.add_argument("--claude-model", default=None)
    discuss_p.add_argument("--codex-model", default=None)
    discuss_p.add_argument("--timeout", type=int, default=1800)
    discuss_p.add_argument("--auto", action="store_true", help="skip round-boundary pauses")
    discuss_p.add_argument("--no-subagents", action="store_true")
```

(ii) Add `_discuss_command` (after `_collab_command`):
```python
def _discuss_command(args, *, claude_backend, codex_backend, impl_codex_backend,
                     discussion_control, consensus_gate, human_gate) -> int:
    from macr.discussion import run_discuss
    from macr.discussion_control import auto_discussion_control, interactive_discussion_control

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

    if discussion_control is None:
        discussion_control = auto_discussion_control if args.auto else interactive_discussion_control

    try:
        state = run_discuss(
            args.task,
            repo=Path(args.repo).resolve(),
            test_cmd=shlex.split(args.test_cmd),
            claude_backend=claude_backend, codex_backend=codex_backend, impl_codex_backend=impl_codex_backend,
            runs_dir=Path(".macr/runs").resolve(), worktrees_dir=Path(".macr/worktrees").resolve(),
            max_rounds=args.max_rounds, max_revisions=args.max_revisions,
            discussion_control=discussion_control, consensus_gate=consensus_gate, human_gate=human_gate,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1
```

(iii) Update `main` to accept the new injectables and dispatch `discuss`. Replace the `main` function with:
```python
def main(argv: list[str] | None = None, *, llm=None,
         claude_backend=None, codex_backend=None, impl_codex_backend=None,
         human_gate=None, discussion_control=None, consensus_gate=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "collab":
        gate = human_gate or collab_human_gate
        return _collab_command(args, claude_backend=claude_backend, codex_backend=codex_backend, human_gate=gate)
    if args.command == "discuss":
        from macr.human_gate import consensus_human_gate
        return _discuss_command(
            args, claude_backend=claude_backend, codex_backend=codex_backend,
            impl_codex_backend=impl_codex_backend,
            discussion_control=discussion_control,
            consensus_gate=consensus_gate or consensus_human_gate,
            human_gate=human_gate or collab_human_gate)
    gate = human_gate or interactive_human_gate
    return _run_command(args, llm=llm, human_gate=gate)
```

- [ ] **Step 4: Run new + V1/Stage A/B cli regressions + FULL suite** — `.venv/bin/pytest tests/test_cli_discuss.py tests/test_cli.py tests/test_cli_collab.py tests/test_cli_subagents.py -v`, then `.venv/bin/pytest -q`. All pass; fix regressions before committing.

- [ ] **Step 5: Commit**
```bash
git add macr/cli.py tests/test_cli_discuss.py
git commit -m "feat: add macr discuss subcommand wiring the discussion orchestrator"
```

---

### Task 7: Smoke script + README

**Files:** Create `scripts/smoke_discuss.py`; Modify `README.md` (append only).

- [ ] **Step 1: Create `scripts/smoke_discuss.py`:**
```python
"""Manual smoke test for `macr discuss` against the real claude + codex CLIs.

Usage:
    .venv/bin/python scripts/smoke_discuss.py /path/to/repo "pytest -q" "add a hello() function"
Requires `claude` and `codex` on PATH (logged in), and a clean git target repo.
Not part of the pytest suite.
"""
from __future__ import annotations

import sys

from macr.cli import main

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: smoke_discuss.py <repo> <test-cmd> <topic>", file=sys.stderr)
        raise SystemExit(2)
    repo, test_cmd, topic = sys.argv[1], sys.argv[2], sys.argv[3]
    raise SystemExit(main(["discuss", topic, "--repo", repo, "--test-cmd", test_cmd]))
```

- [ ] **Step 2: Append to the END of `README.md`** (keep all existing content):
```markdown

### 讨论到共识 (Stage C1) / Discuss-to-consensus

`macr discuss` 让 Claude 与 Codex 各自从主题出计划、多轮讨论、Claude 汇总共识,**你可在每轮边界插话**(成为讨论第三方),确认共识后接入实现闭环。

```bash
.venv/bin/macr discuss "为模块加一个 hello() 函数" --repo /path/to/repo --test-cmd "pytest -q"
# 每轮后:[c]继续 / [i]插话 / [e]提前定稿 / [a]中止;--auto 跳过暂停
```

产物在 `.macr/runs/<run_id>/`:`discussion/`(双计划、各轮 JSON、人插话、`transcript.md`)、`consensus.md`,随后是实现阶段的 diff/test/review/final。讨论步两个 agent 只读 worktree,仅实现步 Codex 可写。
```

- [ ] **Step 3: Verify smoke script parses (do NOT run it)** — `.venv/bin/python -c "import ast; ast.parse(open('scripts/smoke_discuss.py').read()); print('parse ok')"`.

- [ ] **Step 4: Full suite green** — `.venv/bin/pytest -q`.

- [ ] **Step 5: Commit**
```bash
git add scripts/smoke_discuss.py README.md
git commit -m "docs: add discuss smoke script and README usage"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §3 flow + `discuss` command + `--auto`/`--max-rounds` → Task 6; round0 dual-plan + rounds + control + consensus + gate① + impl + gate② → Task 5.
- §4 dual-planning independent (planner build_user topic-only) → Task 3; discussion turns read transcript incl. human → Task 3/5; control (continue/interject/end/abort) → Task 4; consensus → steps fed to impl loop → Task 5 (`state.agent_outputs["planner"].append(...)`).
- §5 turn-by-turn printing → Task 5 (`_print_plan`/`_print_turn`/printer).
- §6 extract `_implementation_loop`, Stage A unchanged → Task 1; Codex read-only discussion vs write impl → Task 6 (two CodexCliBackend instances, `sandbox="read-only"` vs default).
- §7 schemas + SharedState fields → Task 2.
- §9 run-dir (`topic.md`, `discussion/*`, `consensus.md`) → Task 5.
- §10 errors: AgentError in discussion/consensus caught and printed, still finalize+state.json (try/finally) → Task 5; abort/reject skip implementation → Task 5 (tests assert `decisions == []`).
- §11 tests: schema/roles/control/gate/orchestrator/cli + Stage A regression re-run → Tasks 2–7.

**Placeholder scan:** No TBD/TODO. All code complete. `__import__("json")` in Task 5 avoids an extra import line but is explicit; acceptable (or the implementer may add `import json` at top — either is fine, note it).

**Type/name consistency:** `_implementation_loop(state, *, run_path, log, worktree, claude_backend, codex_backend, test_cmd, max_revisions, timeout, printer)` defined Task 1, called identically in Task 5. `run_discuss(...)` signature (claude_backend / codex_backend / impl_codex_backend / consensus_gate / human_gate / discussion_control) consistent Task 5 ↔ Task 6 call site. `ControlDecision(action, interjection="")` consistent Tasks 4↔5↔6 tests. `render_transcript`, `DISCUSS_PLANNER/DISCUSS_TURN/CONSENSUS` consistent Tasks 3↔5. `consensus_human_gate(state, *, input_fn, printer, timestamp)` consistent Tasks 4↔5↔6. `DiscussionTurn`/`ConsensusPlan`/`SharedState.{topic,discussion,consensus}` consistent Tasks 2↔3↔5. `cli.main(..., claude_backend, codex_backend, impl_codex_backend, human_gate, discussion_control, consensus_gate)` consistent Task 6 ↔ test. `RunLog._write` used for `topic.md`/`consensus.md` (private but same-package use, acceptable).
```
