# MACR Stage D — 共识后计划审查门 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage D(给 `discuss` 的共识与实现之间插入「计划审查门」—— 多角色入会)
> 前置:V0、V1、Stage A、Stage B、Stage C1、Stage C2 已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。
> 定位:**机制增量,不改视图也不改实现逻辑。** 在 Claude+Codex 讨论出共识后、进人工门之前,加一道由 Codex 扮演 Reviewer 的独立审查 + 确定性 Evaluator 判定;不过则把意见注回讨论、限次重试,耗尽升人工门。

---

## 1. 目标与非目标

### 目标
- 把架构图里已设计但 `discuss` 路径尚未落地的 **Reviewer / Evaluator** 角色引入讨论闭环。
- 在 `run_discuss` 的 **CONSENSUS 产出之后、`consensus_gate` 之前** 插入「计划审查门」:
  - **Codex** 扮演 Reviewer,独立审查 Claude 汇总的共识方案(审方案,不审代码),产出 `ReviewerOutput`。
  - **确定性 Evaluator** 规则把审查结果判为 `PASS / NEEDS_FIX / BLOCKED`,不调模型。
  - `NEEDS_FIX` 且有重试余额:把 findings 注回讨论 → 两 planner 再谈 1 轮 → 重跑 CONSENSUS → 再审;超过 `max_plan_revisions` 仍 `NEEDS_FIX` → 升级到人工门(不阻断,把未决意见暴露给人)。
- 不破坏 C1/C2/Stage A/B/V1 现有行为与测试。纯 CLI、零 API key 即可跑测试(用 fake backends)。

### 非目标(本阶段不做)
- **不做多方圆桌**(Reviewer/Evaluator 每轮实时参与讨论)—— 那是后续阶段。本阶段只在共识之后加一道门。
- **不起独立 Evaluator 模型角色** —— Evaluator 是确定性规则(复用 `evaluate_collab` 哲学)。
- 不改讨论展开、共识汇总、实现循环、final 人工门、worktree 生命周期的既有逻辑。
- 不加新的 Reviewer backend 参数(直接复用 `run_discuss` 已有的 `codex_backend`)。
- 不做 Web/UI;不改 `_implementation_loop`。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 入会方式 | **共识后的计划审查门**(不是多方圆桌) |
| Reviewer 人选 | **Codex** 审 Claude 汇总的共识(出方案的人不审方案,保独立) |
| Evaluator | **确定性规则**,不调模型(复用 `evaluate_collab` 哲学) |
| NEEDS_FIX 处理 | findings **注回讨论** → 再谈 **1 轮** → 重汇总 → 再审;限 `max_plan_revisions` 次,耗尽 **升人工门** |
| 重试粒度 | 每次修订固定 **1 轮**互评(最小有意义单元,成本可控),不做"每修订 N 轮"配置 |
| 默认重试次数 | `max_plan_revisions = 1`(范围 1–2;`0` = 纯咨询门,只审一次不修订) |
| 插入位置 | `run_discuss` 中 CONSENSUS 之后、`consensus_gate` 之前;其余流程不动 |

---

## 3. 角色:`DISCUSS_REVIEWER`

新增于 `macr/discuss_roles.py`,由 **codex_backend** 扮演:

```python
DISCUSS_REVIEWER = RoleSpec(
    name="discuss_reviewer", agent_id="discuss_reviewer", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 讨论中的独立审查者(由 Codex 扮演)。这份共识方案由对方(Claude)汇总,"
        "你没有参与汇总,请独立、严格地审查该【方案】(不是代码):是否覆盖主题、步骤是否可执行、"
        "有无遗漏/风险/不一致。把会导致方案不可行或偏离主题的问题标为 blocking。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_reviewer_user,
)
```

- 复用现有 schema `ReviewerOutput`(`summary` + `findings: list[Finding]` + `decision: "approve"|"needs_fix"`),`Finding` 带 `level: "blocking"|"non_blocking"`。**schemas.py 无需改动。**
- `_reviewer_user(state)` 构造:展示 `topic` + 当前 `state.consensus`(summary/steps/rationale/open_questions)+ 完整 `render_transcript(state.discussion)`,要求基于讨论上下文审查共识方案。

---

## 4. Evaluator:`evaluate_plan`

新增于 `macr/collab_evaluator.py`(与 `evaluate_collab` 并列),纯确定性、不调模型:

```python
def evaluate_plan(reviewer: dict | None) -> Decision:
    """Deterministic plan-review gate (Stage D). No model call."""
    if reviewer is None:               # 审查未产出(AgentError)
        return Decision.BLOCKED
    if reviewer.get("decision") == "needs_fix":
        return Decision.NEEDS_FIX
    findings = reviewer.get("findings", [])
    if any(f.get("level") == "blocking" for f in findings):
        return Decision.NEEDS_FIX
    return Decision.PASS
```

判定优先级:`None → BLOCKED`;`decision=="needs_fix"` 或 任一 blocking finding → `NEEDS_FIX`;否则 `PASS`。

---

## 5. 审查循环(`run_discuss` 内)

在 `discussion.py` 现有 CONSENSUS 块(产出 `state.consensus` 后)与 `consensus_gate` 调用之间,插入一个 helper `_plan_review_loop`。伪代码:

```python
def _plan_review_loop(state, *, run_path, disc, log, codex_backend, view,
                      max_plan_revisions, claude_backend, run_id, timeout):
    for attempt in range(max_plan_revisions + 1):
        # 1) Codex 审当前共识
        try:
            sink = TraceSink(run_path / "subagents", f"review.v{attempt}")
            rv_msg = codex_backend.run_role(DISCUSS_REVIEWER, state, run_id=run_id,
                                            task_id=run_id, trace=sink)
            reviewer = rv_msg.content
            _record_subagents(state, sink, f"review.v{attempt}", attempt)
        except AgentError as exc:
            view.note(f"[plan review blocked] {exc}")
            reviewer = None
        state.reviews.append(reviewer or {})
        state.agent_outputs["reviewer"].append(reviewer or {})
        if reviewer is not None:
            (disc / f"review.v{attempt}.json").write_text(
                json.dumps(reviewer, ensure_ascii=False, indent=2), encoding="utf-8")
            view.review(attempt, reviewer)

        # 2) 确定性判定
        decision = evaluate_plan(reviewer)
        state.decisions.append({"stage": "plan_review", "attempt": attempt,
                                "decision": decision.value})
        state.agent_outputs["evaluator"].append({"decision": decision.value})
        view.evaluation(attempt, decision)

        # 3) PASS / BLOCKED / 耗尽 → 出循环;否则注回 + 重谈 + 重汇总
        if decision != Decision.NEEDS_FIX:        # PASS 或 BLOCKED
            return
        if attempt == max_plan_revisions:          # 耗尽,升人工门
            return
        _inject_findings_and_revise(state, reviewer, attempt, ...)  # 见下
```

`_inject_findings_and_revise`:
1. 把 findings **预渲染成字符串**,以 `record(round_no, "codex_reviewer", "review", <字符串>)` 注回 `state.discussion`。
   - 用字符串内容是为了让既有 `render_transcript` 的 `isinstance(content, str)` 分支直接处理,**无需改 `render_transcript`**。
   - `round_no` 取当前讨论轮号之后递增(用 `len`-based 或独立计数,见实现计划)。
   - 同时 `view.interjection`-类提示或 `view.note("[plan review] 把 N 条意见注回讨论…")`。
2. 两个 planner 各跑 **1 轮** `DISCUSS_TURN`(回应 findings),`record(...)` + 写 `disc/review-round{attempt}.{agent}.json` + `view.turn(...)`。
3. 重跑 `CONSENSUS`(Claude)→ 更新 `state.consensus`;重写 `consensus.md`(或 `consensus.v{attempt+1}.md`)+ `view.consensus(...)`。
   - 重汇总若 `AgentError` → `view.note` 后保留上一版共识并跳出循环(`return`)。

循环结束后,`state.consensus` 为最终版,`state.reviews[-1]`/`state.decisions[-1]` 为最后一次审查结果,照常进入 `consensus_gate`。

---

## 6. View 扩展

`macr/discussion_view.py` 的 `DiscussionView` Protocol 与 4 个实现各加两个方法:

```python
def review(self, attempt: int, content: dict) -> None: ...      # Reviewer 审查结果
def evaluation(self, attempt: int, decision: Decision) -> None: ...  # Evaluator 判定
```

- `ConsoleView`:打印审查摘要 + blocking findings + 判定(新增格式,不影响既有方法的 C1 文案)。
- `SilentView`:no-op。
- `FakeView`:记录 `("review", attempt, content)` / `("evaluation", attempt, decision)`。
- `TwoPaneView`:审查与判定走 **底部状态面板**(`status_lines`),与人声/状态同区。

---

## 7. 人工门增强:`consensus_human_gate`

`macr/human_gate.py` 的 `consensus_human_gate` 增打印最新审查判定与 blocking findings,让人看到"方案过审 / 被升级上来":

```
--- Plan review ---
Reviewer decision: needs_fix  (evaluator: NEEDS_FIX, 已用尽 1 次修订)
Blocking:
  - <issue> → <recommendation>
```

从 `state.reviews[-1]` / `state.decisions[-1]` 读取;无审查记录时该段不打印(向后兼容,既有 consensus 测试不受影响)。

---

## 8. CLI

`macr/cli.py` 的 `discuss` 子命令:

- 新增 `--max-plan-revisions`(`type=int, default=1`)。
- `_discuss_command` 读取并传入 `run_discuss(..., max_plan_revisions=args.max_plan_revisions)`。
- `main(..., view=None)` 等注入点不变;Reviewer 复用既有 `codex_backend`,**不加新 backend 参数**。

`run_discuss` 新增形参:`max_plan_revisions: int = 1`(置于现有 `max_revisions` 旁,二者语义不同:`max_revisions` 是实现循环的修复次数,`max_plan_revisions` 是计划审查的修订次数)。

---

## 9. 状态与产物

| 写入位置 | 内容 |
|---|---|
| `state.reviews` | 每次 Reviewer 输出(dict;失败为 `{}`) |
| `state.decisions` | 每次 `{"stage":"plan_review","attempt":n,"decision":...}` |
| `state.agent_outputs["reviewer"]` / `["evaluator"]` | 桶一致性(既有空桶字段) |
| `state.discussion` | findings 以 `kind="review"`、字符串内容注回 |
| `disc/review.v{n}.json` | 每次审查原始输出 |
| `disc/review-round{n}.{agent}.json` | 修订轮的 planner 互评 |
| `consensus.md`(重写)| 重汇总后的最终共识 |

---

## 10. 错误处理与边界

- Reviewer `AgentError` → `reviewer=None` → `evaluate_plan` 判 `BLOCKED` → 跳出循环 → 照常进 `consensus_gate`(人工决定)。
- 重汇总 `AgentError` → 保留上一版共识,跳出循环。
- `max_plan_revisions=0` → 只审一次,不修订(纯咨询门);判定仍写入状态并在人工门展示。
- `aborted` 路径(讨论阶段中止)不进审查门,逻辑不变。
- 无共识(CONSENSUS 自身 `AgentError`,`state.consensus is None`)→ 不进审查门(沿用既有 `if state.consensus is not None` 守卫)。

---

## 11. 测试计划

- `evaluate_plan` 单测:`None→BLOCKED`、`decision="needs_fix"→NEEDS_FIX`、blocking finding→`NEEDS_FIX`、干净→`PASS`。
- `DISCUSS_REVIEWER`:`build_user` 含共识 + transcript;system prompt 含独立性措辞。
- `run_discuss` 审查循环(fake backends + `FakeView` + 自动 `discussion_control`/`consensus_gate`):
  - 首审 PASS → 不产生额外讨论轮,直达 `consensus_gate`。
  - 首审 NEEDS_FIX → 注回 + 1 轮 + 重汇总 → 再审 PASS。
  - NEEDS_FIX 耗尽(`max_plan_revisions=1`)→ 升级,仍到 `consensus_gate`,`state.decisions[-1]` 为 NEEDS_FIX。
  - Reviewer `AgentError` → BLOCKED 优雅降级,仍到 `consensus_gate`。
- 4 个 View 的 `review`/`evaluation` 行为(ConsoleView 文案、FakeView 事件、SilentView no-op、TwoPaneView 进 status_lines)。
- `consensus_human_gate` 在有/无审查记录两种情况下的打印(向后兼容)。
- CLI:`--max-plan-revisions` 解析与穿透到 `run_discuss`(注入 backends 断言)。
- 全套回归(`.venv/bin/pytest -q`)绿。

---

## 12. 影响文件清单

| 文件 | 改动 |
|---|---|
| `macr/discuss_roles.py` | 新增 `DISCUSS_REVIEWER` + `_reviewer_user` |
| `macr/collab_evaluator.py` | 新增 `evaluate_plan` |
| `macr/discussion.py` | 新增 `_plan_review_loop` + `_inject_findings_and_revise`;`run_discuss` 插入调用 + 新形参 `max_plan_revisions` |
| `macr/discussion_view.py` | Protocol + 4 实现各加 `review`/`evaluation` |
| `macr/human_gate.py` | `consensus_human_gate` 增打印审查段 |
| `macr/cli.py` | `discuss` 加 `--max-plan-revisions` + 穿透 |
| `README.md` | 追加 Stage D 段 |
| `docs/roadmap.md` | (可选)标注 Stage D |
| `tests/` | 新增/扩展上述测试 |

`macr/schemas.py` **不改**(复用 `ReviewerOutput`/`Finding`/`Decision`)。
