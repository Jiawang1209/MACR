# MACR Stage D — 共识后计划审查门 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `macr discuss` 的共识产出与人工门之间插入一道「计划审查门」:Codex 独立审查 Claude 汇总的共识方案,确定性 Evaluator 判定,NEEDS_FIX 则把意见注回讨论并限次重试,耗尽升人工门。

**Architecture:** 复用现有 `ReviewerOutput`/`Finding`/`Decision` schema。新增一个 Codex 扮演的 `DISCUSS_REVIEWER` 角色与一个纯确定性 `evaluate_plan` 函数;在 `run_discuss` 中 CONSENSUS 之后、`consensus_gate` 之前内联一个审查循环;`DiscussionView` 增 `review`/`evaluation` 两个事件;`consensus_human_gate` 增打印审查结果;CLI 加 `--max-plan-revisions`。

**Tech Stack:** Python 3.13, pydantic, pytest, `.venv` 本地虚拟环境(所有命令用 `.venv/bin/...`)。

> **设计依据:** `docs/superpowers/specs/2026-06-07-macr-stage-d-plan-review-gate-design.md`
>
> **重要约定(贯穿全程):**
> - `FakeAgentBackend` 按 **`role.name`** 取脚本响应;没有脚本会 `AssertionError`。新角色名 `discuss_reviewer` 必须在相关测试替身里有脚本。
> - 默认 `max_plan_revisions=1` ⇒ **每条 discuss 路径都会跑一次审查**。所以 Task 4/6 必须给现有 codex 测试替身补 `"discuss_reviewer"` 脚本,否则既有 discuss 测试回归失败。
> - 每个 Task 末尾都要跑该模块测试 + 全套回归 `.venv/bin/pytest -q`,绿了才提交。

---

## 文件结构(改动地图)

| 文件 | 责任 | 改动 |
|---|---|---|
| `macr/collab_evaluator.py` | 确定性质量门 | 新增 `evaluate_plan(reviewer)` |
| `macr/discuss_roles.py` | 讨论角色定义 | 新增 `DISCUSS_REVIEWER` + `_reviewer_user` |
| `macr/discussion_view.py` | 视图事件接口 | Protocol + 4 实现各加 `review`/`evaluation` |
| `macr/discussion.py` | discuss 编排 | 新增 `_render_findings`;`run_discuss` 内联审查循环 + 新形参 `max_plan_revisions` |
| `macr/human_gate.py` | 人工门 | `consensus_human_gate` 增打印审查段 |
| `macr/cli.py` | CLI 入口 | `discuss` 加 `--max-plan-revisions` + 穿透 |
| `README.md` / `docs/roadmap.md` | 文档 | 追加 Stage D 段 |
| `tests/test_collab_evaluator.py` 等 | 测试 | 新增/扩展 |

`macr/schemas.py` **不改**。

---

## Task 1: `evaluate_plan` 确定性判定

**Files:**
- Modify: `macr/collab_evaluator.py`
- Test: `tests/test_collab_evaluator.py`

- [ ] **Step 1: 追加失败测试** 到 `tests/test_collab_evaluator.py` 末尾

```python
from macr.collab_evaluator import evaluate_plan


def _plan_review(*, blocking=False, needs_fix=False):
    findings = [{"level": "blocking", "issue": "x", "evidence": "e", "recommendation": "r"}] if blocking else []
    return {"summary": "s", "findings": findings, "decision": "needs_fix" if needs_fix else "approve"}


def test_plan_review_none_is_blocked():
    assert evaluate_plan(None) is Decision.BLOCKED


def test_plan_review_needs_fix_decision():
    assert evaluate_plan(_plan_review(needs_fix=True)) is Decision.NEEDS_FIX


def test_plan_review_blocking_finding_is_needs_fix():
    assert evaluate_plan(_plan_review(blocking=True)) is Decision.NEEDS_FIX


def test_plan_review_clean_is_pass():
    assert evaluate_plan(_plan_review()) is Decision.PASS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_collab_evaluator.py -q`
Expected: FAIL — `ImportError: cannot import name 'evaluate_plan'`

- [ ] **Step 3: 实现** —— 在 `macr/collab_evaluator.py` 末尾追加

```python
def evaluate_plan(reviewer: dict | None) -> Decision:
    """Deterministic plan-review gate (Stage D). No model call."""
    if reviewer is None:
        return Decision.BLOCKED
    if reviewer.get("decision") == "needs_fix":
        return Decision.NEEDS_FIX
    if any(f.get("level") == "blocking" for f in reviewer.get("findings", [])):
        return Decision.NEEDS_FIX
    return Decision.PASS
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_collab_evaluator.py -q`
Expected: PASS(原有 5 + 新增 4 = 9 passed)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/collab_evaluator.py tests/test_collab_evaluator.py
git commit -m "feat: add deterministic evaluate_plan gate for plan review"
```

---

## Task 2: `DISCUSS_REVIEWER` 角色

**Files:**
- Modify: `macr/discuss_roles.py`
- Test: `tests/test_discuss_roles.py`

- [ ] **Step 1: 追加失败测试** 到 `tests/test_discuss_roles.py`

先把顶部 import 改为:

```python
from macr.discuss_roles import (
    CONSENSUS,
    DISCUSS_PLANNER,
    DISCUSS_REVIEWER,
    DISCUSS_TURN,
    render_transcript,
)
from macr.schemas import (
    ConsensusPlan,
    DiscussionTurn,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)
```

再追加两个测试:

```python
def test_reviewer_role_wiring():
    assert DISCUSS_REVIEWER.content_model is ReviewerOutput
    assert DISCUSS_REVIEWER.message_type is MessageType.REVIEW
    assert "独立" in DISCUSS_REVIEWER.system_prompt


def test_reviewer_user_has_consensus_and_transcript():
    s = SharedState(run_id="R1", user_query="t", topic="topic-rev")
    s.discussion.append({"round": 0, "agent": "claude", "kind": "plan",
                         "content": {"summary": "disc-sum", "steps": ["d1"]}})
    s.consensus = {"summary": "cons-sum", "steps": ["cs1"], "rationale": "why", "open_questions": ["oq"]}
    user = DISCUSS_REVIEWER.build_user(s)
    assert "topic-rev" in user          # 主题
    assert "cons-sum" in user and "cs1" in user  # 待审共识
    assert "disc-sum" in user           # 讨论记录上下文
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_discuss_roles.py -q`
Expected: FAIL — `ImportError: cannot import name 'DISCUSS_REVIEWER'`

- [ ] **Step 3: 实现** —— `macr/discuss_roles.py`

先把顶部 schema import 补上 `ReviewerOutput`:

```python
from macr.schemas import (
    ConsensusPlan,
    DiscussionTurn,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)
```

在 `_consensus_user` 之后、`DISCUSS_PLANNER` 定义之前追加 builder:

```python
def _reviewer_user(state: SharedState) -> str:
    c = state.consensus or {}
    steps = "\n".join(f"  - {s}" for s in c.get("steps", []))
    return (
        f"主题 / Topic:\n{state.topic}\n\n"
        f"待审查的共识方案(由对方 / Claude 汇总):\n"
        f"summary: {c.get('summary', '')}\nsteps:\n{steps}\n"
        f"rationale: {c.get('rationale', '')}\n"
        f"open_questions: {', '.join(c.get('open_questions', []))}\n\n"
        f"完整讨论记录:\n{render_transcript(state.discussion)}\n\n"
        "请独立审查该【方案】(不是代码):summary(总体判断)、"
        "findings(每条 level / issue / evidence / recommendation)、decision(approve / needs_fix)。"
        "会导致方案不可行或偏离主题的问题请标 level=blocking。"
    )
```

在 `CONSENSUS` 定义之后追加角色:

```python
DISCUSS_REVIEWER = RoleSpec(
    name="discuss_reviewer", agent_id="discuss_reviewer", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 讨论中的独立审查者(由 Codex 扮演)。这份共识方案由对方(Claude)汇总,你未参与汇总。"
        "请独立、严格地审查该【方案】(不是代码):是否覆盖主题、步骤是否可执行、有无遗漏/风险/不一致。"
        "把会导致方案不可行或偏离主题的问题标为 blocking。输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_reviewer_user,
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_discuss_roles.py -q`
Expected: PASS(原有 + 新增 2 全绿)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/discuss_roles.py tests/test_discuss_roles.py
git commit -m "feat: add DISCUSS_REVIEWER role (Codex reviews the consensus plan)"
```

---

## Task 3: View 增 `review` / `evaluation` 事件

**Files:**
- Modify: `macr/discussion_view.py`
- Test: `tests/test_discussion_view.py`

- [ ] **Step 1: 追加失败测试** 到 `tests/test_discussion_view.py`

```python
from macr.discussion_view import ConsoleView, FakeView, SilentView, TwoPaneView
from macr.schemas import Decision


def _review():
    return {"summary": "rev-sum",
            "findings": [{"level": "blocking", "issue": "missing X", "evidence": "e", "recommendation": "add X"}],
            "decision": "needs_fix"}


def test_console_view_review_and_evaluation_output():
    out = []
    v = ConsoleView(out=out.append)
    v.review(0, _review())
    v.evaluation(0, Decision.NEEDS_FIX)
    joined = "\n".join(out)
    assert "rev-sum" in joined and "missing X" in joined
    assert "NEEDS_FIX" in joined


def test_silent_view_review_evaluation_noop():
    v = SilentView()
    v.review(0, _review())
    v.evaluation(0, Decision.PASS)  # must not raise


def test_fake_view_records_review_and_evaluation():
    v = FakeView()
    v.review(1, _review())
    v.evaluation(1, Decision.PASS)
    assert ("review", 1, _review()) == v.events[0]
    assert v.events[1] == ("evaluation", 1, Decision.PASS)


def test_two_pane_view_review_goes_to_status_lines():
    v = TwoPaneView(enabled=False)
    v.review(0, _review())
    v.evaluation(0, Decision.NEEDS_FIX)
    joined = "\n".join(v.status_lines)
    assert "rev-sum" in joined and "NEEDS_FIX" in joined
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_discussion_view.py -q`
Expected: FAIL — `AttributeError: 'ConsoleView' object has no attribute 'review'`

- [ ] **Step 3: 实现** —— `macr/discussion_view.py`

(a) Protocol(在 `consensus` 与 `note` 之间加两行):

```python
    def consensus(self, content: dict) -> None: ...
    def review(self, attempt: int, content: dict) -> None: ...
    def evaluation(self, attempt: int, decision) -> None: ...
    def note(self, text: str) -> None: ...
```

(b) `ConsoleView`(加两个方法):

```python
    def review(self, attempt: int, content: dict) -> None:
        self._out(f"\n━━━ 计划审查 (Codex) · 第 {attempt} 次 ━━━\n{content.get('summary', '')}")
        for f in content.get("findings", []):
            self._out(f"  - ({f.get('level')}) {f.get('issue')} → {f.get('recommendation')}")

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self._out(f"[评估] 第 {attempt} 次审查判定:{val}")
```

(c) `SilentView`(加两个 no-op):

```python
    def review(self, attempt: int, content: dict) -> None: ...
    def evaluation(self, attempt: int, decision) -> None: ...
```

(d) `FakeView`(加两个记录):

```python
    def review(self, attempt: int, content: dict) -> None:
        self.events.append(("review", attempt, content))

    def evaluation(self, attempt: int, decision) -> None:
        self.events.append(("evaluation", attempt, decision))
```

(e) `TwoPaneView`(加两个,进底部状态面板):

```python
    def review(self, attempt: int, content: dict) -> None:
        self.status_lines.append(f"计划审查#{attempt}: {content.get('summary', '')}")
        for f in content.get("findings", []):
            self.status_lines.append(f"  ({f.get('level')}) {f.get('issue')}")
        self._refresh()

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self.status_lines.append(f"评估#{attempt}: {val}")
        self._refresh()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_discussion_view.py -q`
Expected: PASS(含既有 `test_fake_view_records_events_in_order` 仍绿——它只调旧 4 方法)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/discussion_view.py tests/test_discussion_view.py
git commit -m "feat: add review/evaluation events to DiscussionView and all views"
```

---

## Task 4: `run_discuss` 内联审查循环

**Files:**
- Modify: `macr/discussion.py`
- Test: `tests/test_discussion.py`

> 本 Task 是核心。先改测试替身防回归,再写新行为测试,最后实现。

- [ ] **Step 1: 给现有测试替身补 `discuss_reviewer` 脚本(防回归)** —— `tests/test_discussion.py` 的 `_build` 内,把 `codex_discuss` 改为:

```python
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")],
        "discuss_turn": [_turn("x1"), _turn("x2"), _turn("x3")],
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 2,
    })
```

- [ ] **Step 2: 追加新行为测试** 到 `tests/test_discussion.py` 末尾

```python
def _needs_fix_review():
    return {"summary": "needs work",
            "findings": [{"level": "blocking", "issue": "no error handling",
                          "evidence": "step list", "recommendation": "add try/except"}],
            "decision": "needs_fix"}


def _approve_review():
    return {"summary": "ok", "findings": [], "decision": "approve"}


def _build_with_review(tmp_path, *, reviews, max_plan_revisions, max_rounds=1):
    """Run discuss with a scripted Codex reviewer sequence; discussion ends immediately."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")],
        "discuss_turn": [_turn("c1"), _turn("c2"), _turn("c3"), _turn("c4")],
        "consensus": [_consensus(), _consensus(), _consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 3,
    })
    codex_discuss = FakeAgentBackend({
        "discuss_planner": [_plan("x")],
        "discuss_turn": [_turn("x1"), _turn("x2"), _turn("x3"), _turn("x4")],
        "discuss_reviewer": list(reviews),
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    view = FakeView()
    state = run_discuss(
        "build a thing", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex_discuss, impl_codex_backend=codex_impl,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=max_rounds, max_revisions=2, max_plan_revisions=max_plan_revisions,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=view, today="20260607",
    )
    return state, view, codex_discuss


def test_plan_review_pass_first_try_no_extra_rounds(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_approve_review()], max_plan_revisions=1)
    # exactly one review call, decision PASS recorded
    assert codex.calls.count("discuss_reviewer") == 1
    assert state.decisions[-1]["decision"] == "PASS"
    assert ("evaluation", 0, Decision.PASS) in view.events
    # no revision turn was injected into the transcript
    assert not any(e.get("agent") == "codex_reviewer" for e in state.discussion)


def test_plan_review_needs_fix_then_revise_then_pass(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_needs_fix_review(), _approve_review()], max_plan_revisions=1)
    assert codex.calls.count("discuss_reviewer") == 2
    assert [d["decision"] for d in state.decisions] == ["NEEDS_FIX", "PASS"]
    # findings were injected back into the discussion as a 'review' record
    assert any(e.get("kind") == "review" and e.get("agent") == "codex_reviewer"
               for e in state.discussion)
    # re-consensus happened (claude consensus called twice)


def test_plan_review_exhausts_then_escalates(tmp_path):
    state, view, codex = _build_with_review(
        tmp_path, reviews=[_needs_fix_review(), _needs_fix_review()], max_plan_revisions=1)
    assert state.decisions[-1]["decision"] == "NEEDS_FIX"
    # still reached consensus gate + implementation (final approved → reaches final gate)
    assert state.human_feedback is not None


def test_plan_review_reviewer_error_is_blocked(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend({
        "discuss_planner": [_plan("c")], "discuss_turn": [_turn("c1")],
        "consensus": [_consensus()],
        "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
    })

    class _CodexNoReviewer(FakeAgentBackend):
        def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None):
            if role.name == "discuss_reviewer":
                from macr.agent import AgentError
                raise AgentError("reviewer down")
            return super().run_role(role, state, run_id=run_id, task_id=task_id,
                                    timestamp=timestamp, trace=trace)

    codex = _CodexNoReviewer({
        "discuss_planner": [_plan("x")], "discuss_turn": [_turn("x1")],
    })
    codex_impl = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)
    state = run_discuss(
        "t", repo=repo, test_cmd=["true"], claude_backend=claude, codex_backend=codex,
        impl_codex_backend=codex_impl, runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_rounds=1, max_revisions=2, max_plan_revisions=1,
        consensus_gate=_approve, human_gate=_approve,
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        view=SilentView(), today="20260607",
    )
    assert state.decisions[-1]["decision"] == "BLOCKED"
    assert state.human_feedback is not None  # gracefully reached the gates
```

确保该文件顶部已 import `Decision`:

```python
from macr.schemas import Decision, HumanFeedback
```

- [ ] **Step 3: 跑新测试确认失败**

Run: `.venv/bin/pytest tests/test_discussion.py -q`
Expected: FAIL — `TypeError: run_discuss() got an unexpected keyword argument 'max_plan_revisions'`

- [ ] **Step 4: 实现** —— `macr/discussion.py`

(a) 顶部 import 调整:

```python
from macr.collab_orchestrator import _build_final, _implementation_loop, _record_subagents
from macr.collab_evaluator import evaluate_plan
from macr.discuss_roles import CONSENSUS, DISCUSS_PLANNER, DISCUSS_REVIEWER, DISCUSS_TURN, render_transcript
```

并把 schema import 改为带 `Decision`:

```python
from macr.schemas import Decision, HumanFeedback, SharedState
```

(b) 在 `_disc_dir` 之后加 module-level helper:

```python
def _render_findings(reviewer: dict) -> str:
    lines = [f"[计划审查意见] {reviewer.get('summary', '')}"]
    for f in reviewer.get("findings", []):
        lines.append(f"  - ({f.get('level')}) {f.get('issue')} → {f.get('recommendation')}")
    return "\n".join(lines)
```

(c) `run_discuss` 签名加形参(放在 `max_revisions` 后):

```python
    max_rounds: int = 3,
    max_revisions: int = 2,
    max_plan_revisions: int = 1,
```

(d) 在 `if state.consensus is not None:` 块内、`fb1 = consensus_gate(...)` 这一行**之前**插入审查循环。即把现有:

```python
            if state.consensus is not None:
                fb1 = consensus_gate(state, printer=view.note)
```

改成:

```python
            if state.consensus is not None:
                # Stage D: post-consensus plan review gate (Codex reviews; deterministic evaluator)
                for attempt in range(max_plan_revisions + 1):
                    try:
                        rsink = TraceSink(run_path / "subagents", f"review.v{attempt}")
                        rmsg = codex_backend.run_role(
                            DISCUSS_REVIEWER, state, run_id=run_id, task_id=run_id, trace=rsink)
                        reviewer = rmsg.content
                        _record_subagents(state, rsink, f"review.v{attempt}", attempt)
                    except AgentError as exc:
                        view.note(f"[plan review blocked] {exc}")
                        reviewer = None
                    state.reviews.append(reviewer or {})
                    state.agent_outputs["reviewer"].append(reviewer or {})
                    if reviewer is not None:
                        (disc / f"review.v{attempt}.json").write_text(
                            json.dumps(reviewer, ensure_ascii=False, indent=2), encoding="utf-8")
                        view.review(attempt, reviewer)

                    decision = evaluate_plan(reviewer)
                    state.decisions.append(
                        {"stage": "plan_review", "attempt": attempt, "decision": decision.value})
                    state.agent_outputs["evaluator"].append({"decision": decision.value})
                    view.evaluation(attempt, decision)

                    if decision is not Decision.NEEDS_FIX:
                        break
                    if attempt == max_plan_revisions:
                        break  # exhausted → escalate to human gate with unresolved findings

                    # NEEDS_FIX with budget left: inject findings, re-discuss one round, re-consensus
                    rround = max_rounds + 1 + attempt
                    findings_text = _render_findings(reviewer)
                    record(rround, "codex_reviewer", "review", findings_text)
                    (disc / f"review-round{attempt}.findings.txt").write_text(
                        findings_text + "\n", encoding="utf-8")
                    view.note(
                        f"[plan review] needs_fix → 注回 {len(reviewer.get('findings', []))} 条意见,再谈一轮")
                    try:
                        for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                            tsink = TraceSink(run_path / "subagents", f"review-turn.{agent}.v{attempt}")
                            tmsg = backend.run_role(
                                DISCUSS_TURN, state, run_id=run_id, task_id=run_id, trace=tsink)
                            record(rround, agent, "turn", tmsg.content)
                            _record_subagents(state, tsink, f"review-turn.{agent}", attempt)
                            (disc / f"review-round{attempt}.{agent}.json").write_text(
                                json.dumps(tmsg.content, ensure_ascii=False, indent=2), encoding="utf-8")
                            view.turn(agent, rround, tmsg.content)
                        csink = TraceSink(run_path / "subagents", f"consensus.v{attempt + 1}")
                        cmsg = claude_backend.run_role(
                            CONSENSUS, state, run_id=run_id, task_id=run_id, trace=csink)
                        state.consensus = cmsg.content
                        _record_subagents(state, csink, f"consensus.v{attempt + 1}", attempt + 1)
                        c2 = cmsg.content
                        log._write(
                            "consensus.md",
                            f"# Consensus (rev {attempt + 1})\n\n{c2.get('summary', '')}\n\n## Steps\n"
                            + "\n".join(f"{i}. {s}" for i, s in enumerate(c2.get('steps', []), 1))
                            + f"\n\n## Rationale\n{c2.get('rationale', '')}\n")
                        view.consensus(c2)
                    except AgentError as exc:
                        view.note(f"[consensus blocked] {exc}")
                        break

                fb1 = consensus_gate(state, printer=view.note)
```

> 注意:循环之后**保持** `fb1 = consensus_gate(...)` 及其后的所有现有代码(approve→implementation_loop→final gate)**完全不变**,只是缩进位置不变(`fb1` 行已是上面替换块的最后一行)。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_discussion.py -q`
Expected: PASS(既有 + 新增 4 全绿)

- [ ] **Step 6: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿(若 `tests/test_cli_discuss.py` 红,留到 Task 6 修——但本步它应仍绿,因为 Task 6 之前 cli 默认 `max_plan_revisions` 还没接,`run_discuss` 默认 1 会让 cli discuss 测试触发一次 reviewer。**所以 cli 测试此刻可能红**)。

> **预期红点处理:** 若 `.venv/bin/pytest -q` 在此处因 `tests/test_cli_discuss.py` 缺 `discuss_reviewer` 脚本而红,这是已知的、由 Task 6 修复的回归。可先只确认 `tests/test_discussion.py` 与其余模块绿,然后继续 Task 6;**Task 6 完成后全套必须绿**。为避免中途红,推荐:本 Step 先临时只跑 `.venv/bin/pytest -q --deselect tests/test_cli_discuss.py` 确认其余全绿,提交,再做 Task 6。

- [ ] **Step 7: 提交**

```bash
git add macr/discussion.py tests/test_discussion.py
git commit -m "feat: insert post-consensus plan review loop into run_discuss"
```

---

## Task 5: `consensus_human_gate` 增打印审查段

**Files:**
- Modify: `macr/human_gate.py`
- Test: `tests/test_consensus_gate.py`

- [ ] **Step 1: 追加失败测试** 到 `tests/test_consensus_gate.py`

```python
def _state_with_review(decision="needs_fix", eval_decision="NEEDS_FIX"):
    s = _state()
    s.reviews.append({"summary": "rev", "decision": decision,
                      "findings": [{"level": "blocking", "issue": "missing rollback",
                                    "evidence": "e", "recommendation": "add rollback step"}]})
    s.decisions.append({"stage": "plan_review", "attempt": 0, "decision": eval_decision})
    return s


def test_consensus_gate_shows_plan_review_when_present():
    out = []
    consensus_human_gate(_state_with_review(), input_fn=lambda p: "a",
                         printer=out.append, timestamp="t")
    joined = "\n".join(out)
    assert "Plan review" in joined or "计划审查" in joined
    assert "missing rollback" in joined
    assert "NEEDS_FIX" in joined


def test_consensus_gate_no_review_is_backward_compatible():
    out = []
    consensus_human_gate(_state(), input_fn=lambda p: "a", printer=out.append, timestamp="t")
    joined = "\n".join(out)
    assert "agreed plan" in joined
    assert "Plan review" not in joined and "计划审查" not in joined
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_consensus_gate.py -q`
Expected: FAIL — `assert "missing rollback" in joined`(未打印审查段)

- [ ] **Step 3: 实现** —— `macr/human_gate.py` 的 `consensus_human_gate`,在 `if c.get("open_questions"):` 块之后、`return _prompt_decision(...)` 之前插入:

```python
    if state.reviews:
        rv = state.reviews[-1]
        ev = state.decisions[-1].get("decision") if state.decisions else "?"
        printer(f"\n--- Plan review / 计划审查 ---")
        printer(f"Reviewer decision: {rv.get('decision', '?')}  (evaluator: {ev})")
        blocking = [f for f in rv.get("findings", []) if f.get("level") == "blocking"]
        if blocking:
            printer("Blocking:")
            for f in blocking:
                printer(f"  - {f.get('issue')} → {f.get('recommendation')}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_consensus_gate.py -q`
Expected: PASS(既有 2 + 新增 2 全绿)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q --deselect tests/test_cli_discuss.py`(若 Task 4 已临时排除)或确认仅 cli_discuss 待 Task 6 修
Expected: 除 cli_discuss 外全绿

- [ ] **Step 6: 提交**

```bash
git add macr/human_gate.py tests/test_consensus_gate.py
git commit -m "feat: surface latest plan-review result in consensus human gate"
```

---

## Task 6: CLI `--max-plan-revisions` + 修复 cli_discuss 测试

**Files:**
- Modify: `macr/cli.py`
- Test: `tests/test_cli_discuss.py`

- [ ] **Step 1: 修复现有 cli_discuss 测试替身(防回归)** —— `tests/test_cli_discuss.py` 的 `_codex_discuss()`:

```python
def _codex_discuss():
    return FakeAgentBackend({
        "discuss_planner": [{"summary": "p2", "steps": ["s2"], "tools_needed": [], "risks": []}],
        "discuss_turn": [{"response": "r2", "agreements": [], "concerns": [], "revised_steps": []}] * 4,
        "discuss_reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}] * 2,
    })
```

- [ ] **Step 2: 追加新测试** 到 `tests/test_cli_discuss.py` 末尾

```python
def test_discuss_max_plan_revisions_threaded(tmp_path, monkeypatch):
    """--max-plan-revisions reaches run_discuss; reviewer runs and zero exit on approve."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    codex = _codex_discuss()
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true",
         "--max-rounds", "1", "--max-plan-revisions", "0"],
        claude_backend=_claude(), codex_backend=codex, impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        consensus_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    # max_plan_revisions=0 ⇒ exactly one review, no revision rounds
    assert codex.calls.count("discuss_reviewer") == 1
```

- [ ] **Step 3: 跑新测试确认失败**

Run: `.venv/bin/pytest tests/test_cli_discuss.py::test_discuss_max_plan_revisions_threaded -q`
Expected: FAIL — `unrecognized arguments: --max-plan-revisions`

- [ ] **Step 4: 实现** —— `macr/cli.py`

(a) 在 discuss 子解析器(`--max-revisions` 那行之后)加:

```python
    discuss_p.add_argument("--max-revisions", type=int, default=2)
    discuss_p.add_argument("--max-plan-revisions", type=int, default=1,
                           help="共识后计划审查的最大修订次数(0=只审一次不修订)")
```

(b) `_discuss_command` 里 `run_discuss(...)` 调用加参数(在 `max_revisions=args.max_revisions,` 那行后):

```python
                max_rounds=args.max_rounds, max_revisions=args.max_revisions,
                max_plan_revisions=args.max_plan_revisions,
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_cli_discuss.py -q`
Expected: PASS(既有 4 + 新增 1 全绿)

- [ ] **Step 6: 全套回归(现在必须全绿)**

Run: `.venv/bin/pytest -q`
Expected: 全部绿(无 deselect)

- [ ] **Step 7: 提交**

```bash
git add macr/cli.py tests/test_cli_discuss.py
git commit -m "feat: add --max-plan-revisions to macr discuss and thread it through"
```

---

## Task 7: 文档(README + roadmap)

**Files:**
- Modify: `README.md`(仅追加)
- Modify: `docs/roadmap.md`(仅追加)

- [ ] **Step 1: 在 `README.md` 末尾追加**

```markdown

#### 共识后计划审查门 (Stage D) / Post-consensus plan review gate

`macr discuss` 在 Claude+Codex 谈出共识方案后、进人工门之前,自动让 **Codex 独立审查**该共识方案(审方案不审代码);确定性 Evaluator 判 `PASS/NEEDS_FIX/BLOCKED`。`NEEDS_FIX` 会把审查意见注回讨论、两方再谈一轮、重新汇总后再审,限 `--max-plan-revisions` 次;耗尽仍不过则把未决意见呈给人工门。

```bash
.venv/bin/macr discuss "为模块加 hello() 函数" --repo /path/to/repo --test-cmd "pytest -q" --max-plan-revisions 1
```

`--max-plan-revisions 0` 表示只审一次、不自动修订(纯咨询门)。
```

- [ ] **Step 2: 在 `docs/roadmap.md` 的 Stage 序列处补一行 Stage D**(若有对应小节;否则在 V1 描述末尾追加一句)

```markdown
- Stage D:`discuss` 共识后插入 Codex 计划审查门(独立审查 + 确定性评估 + 限次修订,耗尽升人工门)。
```

- [ ] **Step 3: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 4: 提交**

```bash
git add README.md docs/roadmap.md
git commit -m "docs: document Stage D post-consensus plan review gate"
```

---

## Self-Review(plan 作者已完成)

**Spec coverage:**
- §3 `DISCUSS_REVIEWER` + `_reviewer_user`(Codex,复用 ReviewerOutput)→ Task 2。
- §4 `evaluate_plan` 确定性规则 → Task 1。
- §5 审查循环(审→判→注回→1 轮→重汇总→限次→耗尽升级;字符串注回走 render_transcript str 分支;重汇总 AgentError 跳出)→ Task 4。
- §6 View `review`/`evaluation`(4 实现)→ Task 3。
- §7 `consensus_human_gate` 增打印(向后兼容)→ Task 5。
- §8 CLI `--max-plan-revisions` + 穿透 + reviewer 复用 codex_backend → Task 6。
- §9 状态产物(reviews/decisions/agent_outputs/discussion/disc 文件/consensus 重写)→ Task 4 实现块覆盖。
- §10 错误处理(reviewer AgentError→BLOCKED;重汇总 AgentError→跳出;max=0;aborted 不进;无共识守卫沿用)→ Task 4(BLOCKED 测试)+ 既有 `if state.consensus is not None` 守卫。
- §11 测试 → 每 Task 的测试步;§12 文件清单 → 各 Task。

**Placeholder scan:** 无 TBD/TODO。所有代码步均给出完整代码。Task 6 Step 2 注释里两次出现 `reviews=` 的旧参数风险——已核对 `_build_with_review` 在 Task 4 定义、Task 6 不引用它,无跨任务符号缺失。

**Type/name consistency:**
- 角色名 `discuss_reviewer`(`role.name`)在 Task 2 定义,与 Task 4/6 测试替身的脚本 key、`codex.calls.count("discuss_reviewer")` 断言一致。
- `evaluate_plan(reviewer: dict|None) -> Decision`(Task 1)在 Task 4 以 `evaluate_plan(reviewer)` 调用,返回值 `Decision` 与 `.value`(写 state)、`is not Decision.NEEDS_FIX` 比较一致;`discussion.py` 顶部新 import `Decision`。
- `view.review(attempt, content)` / `view.evaluation(attempt, decision)`(Task 3)与 Task 4 调用 `view.review(attempt, reviewer)` / `view.evaluation(attempt, decision)`、FakeView 事件断言 `("review", 0, ...)` / `("evaluation", 0, Decision.PASS)` 一致。
- `run_discuss(..., max_plan_revisions=1)`(Task 4 签名)与 Task 4/6 测试调用、CLI 穿透(Task 6)一致;与既有 `max_revisions`(实现循环)语义区分、并存。
- `_render_findings(reviewer)`(Task 4)产出字符串,注回 `record(rround, "codex_reviewer", "review", <str>)`,由既有 `render_transcript` 的 `isinstance(content, str)` 分支处理——无需改 `render_transcript`,与 spec §5 一致。
- `consensus_human_gate` 读 `state.reviews[-1]` / `state.decisions[-1]`(Task 5),其写入由 Task 4 保证;调用时点(consensus_gate)早于 implementation_loop,故 `[-1]` 即计划审查结果。

**已知执行顺序坑(已在 Task 4 Step 6 / Task 6 标注):** Task 4 实现后、Task 6 之前,`tests/test_cli_discuss.py` 会因默认 `max_plan_revisions=1` 触发一次未脚本化的 reviewer 而红;按 Task 4 Step 6 用 `--deselect tests/test_cli_discuss.py` 暂避,Task 6 完成后全套必绿。
