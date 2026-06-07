# MACR Stage C — Claude↔Codex 讨论到共识 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage C(对称双规划 → 回合制讨论 → 共识 → 实现)
> 前置:V0、V1、Stage A(异构协作)、Stage B(嵌套 subagent + 可追踪)已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。

---

## 1. 目标与非目标

### 目标
- 新增 `macr discuss` 命令:用户给一个主题,**Claude 与 Codex 各自独立出计划**,然后**多轮回合制讨论**彼此的方案,Claude **汇总成共识方案**,人工确认后**接入 Stage A 的实现闭环**。
- 用户能在终端**逐轮实时看到**两个异构 agent 的讨论过程(谁在第几轮说了什么、如何互相回应)。
- 复用 Stage A 的实现闭环与 Stage B 的流式捕获/可追踪;不破坏 V1/Stage A/Stage B 现有行为与测试。
- 纯 CLI、零 API key(沿用 Stage A/B)。

### 非目标(YAGNI / 留待后续)
- 不做"立场字段提前停"(本阶段固定轮数);不做交互式"你来掌舵"(本阶段不处理讨论中途的终端输入)。
- 不做逐字/逐行真流式(本阶段逐轮呈现整段)。
- 不做自定义 subagent(那是另一个已搁置的方向)。
- 不做 Web/UI。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 起点 | **对称双规划**:Claude 与 Codex 各自独立从主题出计划(并行、互不可见) |
| 讨论 | **回合制**,`max_rounds` 默认 **3**;每步看到目前为止的完整对话记录后回应 |
| 收场 | 固定轮数后 **Claude 汇总 `consensus.md`** → **人工门控①** 确认 |
| 实现 | 共识批准后接入 **Stage A 实现闭环**(executor→test→review→eval→返工)→ **人工门控②** |
| 实时性 | **逐轮呈现**(每步完成即打印整段;复用 Stage B 流式捕获,无新流式 I/O) |
| 结构/复用 | **方案 A**:抽出共享 `_implementation_loop`,Stage A 与 Stage C 共用 |
| 讨论 cwd | 两个 agent 以 **worktree 为 cwd**,可**只读**目标代码来规划 |

---

## 3. 总体流程与命令

```
macr discuss "<主题>" --repo <path> --test-cmd "pytest -q" [--max-rounds 3] [--max-revisions 2]
                      [--claude-model M] [--codex-model M] [--no-subagents] [--timeout S]
  → 生成 run_id;从 target repo 建隔离 worktree;写 topic.md
  ── 讨论阶段 ──────────────────────────────────────────
  第0轮(对称双规划,互不可见):
      Claude 出 PlannerOutput(plan.claude)   Codex 出 PlannerOutput(plan.codex)
  第1..max_rounds 轮(顺序,共享对话记录递增):
      Claude 读 transcript → DiscussionTurn   →(逐轮打印 + 落盘)
      Codex  读 transcript → DiscussionTurn   →(逐轮打印 + 落盘)
  汇总:Claude 读完整 transcript → ConsensusPlan → 写 consensus.md
  ── 人工门控①(共识)──────────────────────────────────
      collab_human_gate 风格:展示 consensus + transcript 摘要;approve/reject/edit
      reject → 不进实现,保留讨论记录与 worktree,退出非 0
  ── 实现阶段(复用 _implementation_loop,共识作为既定计划)──
      Codex 实现 → 跑测试 → Claude 审 diff → 规则判定 → 返工(≤ max_revisions)
  ── 人工门控②(最终)──────────────────────────────────
      展示最终 diff + 测试 + 决策轨迹;approve/reject/edit
  → final.md + state.json
```

---

## 4. 讨论机制(结构化 + 可追踪)

每步通过现有 CLI 后端(Stage B 的 stream-json/`--json` + tool-use/JSON)产出结构化内容并解析校验。

### 4.1 角色与轮次
- **第0轮 计划**:复用 `PlannerOutput`(`summary / steps / tools_needed / risks`)。Claude、Codex **各自独立**从主题出计划,**互不可见**(各自的 build_user 只含主题,不含对方)。
- **讨论轮**:每轮 Claude 先、Codex 后(固定顺序)。每个 agent 的 `build_user` 含:主题 + **目前为止的完整对话记录**(双方初始计划 + 此前所有讨论轮)。
- 轮次:`1 .. max_rounds`(默认 3)。总讨论 agent 调用 = 2(规划) + 2×max_rounds(讨论) + 1(共识汇总)。

### 4.2 新增 schema(`schemas.py`)
- `DiscussionTurn(BaseModel)`:
  - `response: str`(自由文本:这一轮的论点/回应——对话细节)
  - `agreements: list[str] = []`(认同对方的点)
  - `concerns: list[str] = []`(对对方方案的异议)
  - `revised_steps: list[str] = []`(综合后更新的计划步骤)
- `ConsensusPlan(BaseModel)`:
  - `summary: str`
  - `steps: list[str]`
  - `rationale: str`(为何这样定)
  - `open_questions: list[str] = []`(尚未谈拢/留待实现期注意的点)

### 4.3 共享对话记录
- 内存中维护一份有序记录;每步追加 `{round, agent, kind(plan/turn), content}`。
- 落盘为人类可读的 `discussion/transcript.md`(按轮次、按 agent 拼装),以及每步的结构化 JSON。

### 4.4 共识与既定计划交接
- Claude 汇总产出 `ConsensusPlan`;其 `steps` 作为**既定计划**喂给实现阶段(等价于 Stage A 里 Planner 的 `steps`)。
- 实现阶段不再重新规划;`_implementation_loop` 的 Executor 直接基于共识 steps + 上轮 review 反馈工作。

---

## 5. 终端逐轮呈现

- 每步(每个计划、每个讨论轮、共识)**完成即打印**带醒目标题的整段,例如:
  ```
  ━━━ Codex · 第 1 轮 ━━━
  [concerns] 计划 A 未考虑迁移回滚
  [response] 建议先加兼容层,分两步切换……
  [revised steps] 1. …  2. …
  ```
- 通过编排器的 `printer`(默认 `print`,测试可注入)输出;不引入实时流式 I/O。
- Stage B 的原始事件流/subagent 摘要照常落 `.macr/runs/<id>/subagents/`(可追踪不丢)。

---

## 6. 结构与复用(方案 A:抽出共享实现循环)

- 从 `collab_orchestrator.py` 抽出 `_implementation_loop(...)`:封装 Stage A 的 `executor→diff→test→review→eval` 返工循环(含 TraceSink 接线、`state.decisions`/`state.subagents` 更新、AgentError→BLOCKED)。**不含** worktree 创建与 human gate。
- `run_collab`(Stage A)重构为:建 worktree → Claude planner → `_implementation_loop` → human gate → finalize。**对外行为与签名不变**,Stage A 全部测试须保持绿。
- 新增 `discussion.py` 的 `run_discuss(...)`:建 worktree → 讨论阶段 → 共识 → human gate① →(批准则)`_implementation_loop` → human gate② → finalize。
- 实现阶段以 worktree 为作业目录;讨论阶段两个 agent 以 worktree 为 cwd(**只读**;Claude 后端用只读工具白名单,Codex 讨论步以 `--sandbox read-only` 防止其在讨论期改文件)。

> 注:Codex 在"讨论/规划"步必须**只读**(`--sandbox read-only`),仅在"实现"步用 `workspace-write`。这是与 Stage A/B 的一处差异,需在 Codex 后端支持按调用指定 sandbox(或讨论用独立后端实例)。

---

## 7. 数据模型扩展(`schemas.py`)

- 新增 `DiscussionTurn`、`ConsensusPlan`(见 §4.2)。两者均不以 `Test` 开头,故无需 `__test__ = False`(pytest 不会误收集)。
- `SharedState` 新增字段(向后兼容,默认值):
  - `topic: str | None = None`
  - `discussion: list[dict] = []`(有序记录:`{round, agent, kind, content}`)
  - `consensus: dict | None = None`

---

## 8. CLI(`cli.py`)

- 新增子命令 `discuss`:参数同 `collab` + `--max-rounds`(默认 3)。
- `main(...)` 增加 `discuss` 分发;复用注入式 `claude_backend`/`codex_backend`/`human_gate` 以便测试。
- 退出码:`0` = 最终 approve;非 0 = 任一门控 reject 或出错。
- 默认开启 subagent(沿用 Stage B),`--no-subagents` 可关。

---

## 9. run 目录新增

```
.macr/runs/<run_id>/
  topic.md
  discussion/
    plan.claude.md        plan.codex.md
    round1.claude.json     round1.codex.json
    round2.claude.json     round2.codex.json
    round3.claude.json     round3.codex.json
    transcript.md
  consensus.md
  (随后是 Stage A 实现阶段产物:executor.output.vN.md / diff.vN.patch / test.vN.* / reviewer.output.md / evaluator.output.json)
  subagents/   final.md   state.json
```

---

## 10. 错误处理

- 沿用 Stage A/B:CLI 缺失→退出 2;CLI 非零退出/解析失败→重试→BLOCKED;任意异常→`try/finally` 落 `state.json`→退出非 0。
- 讨论阶段某 agent 两次失败(AgentError):记 BLOCKED,跳过后续讨论,直接让 Claude 基于已有记录尝试汇总;若汇总也失败→进人工门控①并标注。
- 共识 reject:不进实现,保留 `discussion/` 与 worktree,退出非 0。

---

## 11. 测试策略(TDD)

- `DiscussionTurn` / `ConsensusPlan` schema 单测。
- `transcript.md` 拼装单测(顺序、按轮按 agent)。
- `_implementation_loop` 抽取后:Stage A 的 `tests/test_collab_orchestrator.py` + `test_collab_orchestrator_subagents.py` **全部保持绿**(重构回归)。
- `run_discuss` 用 `FakeAgentBackend`(脚本化:claude/codex 各出计划 + 各轮 DiscussionTurn + Claude 共识)+ 真临时 git 仓库跑全程,断言:
  - 讨论记录顺序与 `state.discussion` 聚合正确;
  - `discussion/` 与 `consensus.md` 落盘;
  - 人工门控①:reject → 不进实现、退出语义正确;approve → 进入实现并最终产出 `final.md`;
  - `printer` 被逐轮调用(注入假 printer 收集输出,断言含轮次标题)。
- CLI `discuss` 子命令:注入后端 + 临时 git 仓库,断言 approve→0 / 共识 reject→非 0。
- 真实 `claude`/`codex` 仅在冒烟脚本(扩展 `scripts/smoke_collab.py` 或新增 `scripts/smoke_discuss.py`)。
- commit 无 AI 署名;依赖只在 `.venv`。

---

## 12. 完成标准(Definition of Done)

- [ ] `macr discuss "<主题>" --repo <p> --test-cmd "..."` 能跑完:双规划 → 3 轮讨论 → Claude 共识 → 人工门控① → Stage A 实现 → 人工门控② → `final.md`。
- [ ] 终端逐轮打印两个 agent 的发言(带轮次/角色标题)。
- [ ] `discussion/`(双计划 + 各轮 JSON + `transcript.md`)与 `consensus.md` 落盘;`state.discussion`/`state.consensus` 入 `state.json`。
- [ ] 讨论/规划步两个 agent **只读** worktree;实现步 Codex 方可写。
- [ ] `_implementation_loop` 抽取完成,Stage A 全部测试与行为不变。
- [ ] 全部单元 + 集成测试通过(FakeAgentBackend + 真临时 git 仓库,不触真实 CLI);V1/Stage A/Stage B 零回归。
