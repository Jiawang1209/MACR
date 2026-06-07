# MACR Stage C1 — 人可插话的 Claude↔Codex 三方讨论到共识 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage C1(对称双规划 → 人可插话的回合制讨论 → 共识 → 实现)
> 前置:V0、V1、Stage A(异构协作)、Stage B(嵌套 subagent + 可追踪)已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。
> 定位:**MACR 结构化内核 与 "agent-bridge 式实时围观/介入" 的融合 —— 第一步(灵魂)。** 双栏 live TUI(C2)在本 spec 之后单独做。

---

## 1. 目标与非目标

### 目标
- 新增 `macr discuss` 命令:用户给一个主题,**Claude 与 Codex 各自独立出计划**,然后**多轮回合制讨论**彼此方案,Claude **汇总成共识方案**,人工确认后**接入 Stage A 实现闭环**。
- **融合的灵魂**:让**人成为讨论的第三位参与者**——在**每一轮边界**,用户可以选择「继续 / 插话 / 提前定稿 / 中止」;插话作为 `human` 一条进入对话记录,**影响双方下一轮**。
- 用户在终端**逐轮实时看到**两个异构 agent(+ 自己)的讨论过程。
- 复用 Stage A 实现闭环与 Stage B 流式捕获/可追踪;不破坏 V1/Stage A/Stage B 现有行为与测试。纯 CLI、零 API key。

### 非目标(本阶段不做;C2 或更后)
- **不做双栏 live TUI**(`textual`/`rich.Live` 左右两栏)—— 那是 C2;本阶段单终端逐轮打印。
- 不做"agent 生成中途打断"(那需要持久交互式 TUI 会话,会丢结构化/可追踪);介入只在**回合边界**。
- 不做"立场字段提前停"(本阶段固定上限轮数 + 人可提前定稿);不做逐字真流式。
- 不做自定义 subagent(另一搁置方向);不做 Web/UI。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 起点 | **对称双规划**:Claude 与 Codex 各自从主题独立出计划(并行、互不可见) |
| 讨论 | **回合制**,`max_rounds` 默认 **3**;每步看到目前为止完整对话记录(含人的插话)后回应 |
| **人介入** | **第三方,回合边界介入**:每轮后 `[c]ontinue / [i]nterject / [e]nd(提前定稿) / [a]bort`;插话进 transcript 影响下一轮 |
| 介入默认 | **默认交互**(每轮暂停等一次按键,Enter=继续);`--auto` 全自动不暂停(等价无人值守) |
| 收场 | 轮数用完 **或** 人选 `end` → **Claude 汇总 `consensus.md`** → **人工门控①** 确认 |
| 实现 | 共识批准后接入 **Stage A 实现闭环** → **人工门控②** |
| 实时性 | **逐轮呈现**(每步完成即打印整段;复用 Stage B 流式捕获,无新流式 I/O) |
| 结构/复用 | **方案 A**:抽出共享 `_implementation_loop`,Stage A 与 Stage C 共用 |
| 讨论 cwd | 两个 agent 以 **worktree 为 cwd**,可**只读**目标代码来规划(Codex 讨论步 `--sandbox read-only`) |

---

## 3. 总体流程与命令

```
macr discuss "<主题>" --repo <path> --test-cmd "pytest -q"
              [--max-rounds 3] [--max-revisions 2] [--auto]
              [--claude-model M] [--codex-model M] [--no-subagents] [--timeout S]
  → 生成 run_id;从 target repo 建隔离 worktree;写 topic.md
  ── 讨论阶段(人为第三方)─────────────────────────────
  第0轮(对称双规划,互不可见):
      Claude 出 PlannerOutput(plan.claude)   Codex 出 PlannerOutput(plan.codex)
      ── 回合边界 ① ── 默认暂停:[c]/[i]/[e]/[a]
  第1..max_rounds 轮(顺序,共享对话记录递增):
      Claude 读 transcript(含人插话)→ DiscussionTurn   →(逐轮打印 + 落盘)
      Codex  读 transcript → DiscussionTurn               →(逐轮打印 + 落盘)
      ── 回合边界 ── 默认暂停:[c]继续 / [i]插话 / [e]提前定稿 / [a]中止
          [i]:你输入一段话 → 作为 {agent:"human"} 进 transcript → 下一轮双方可见
          [e]:跳过剩余轮次,直接进汇总
          [a]:保存现场,退出非 0,不进实现
  汇总:Claude 读完整 transcript → ConsensusPlan → 写 consensus.md
  ── 人工门控①(共识):approve / reject / edit ───────────
      reject → 不进实现,保留讨论记录与 worktree,退出非 0
  ── 实现阶段(复用 _implementation_loop,共识作为既定计划)──
      Codex 实现 → 跑测试 → Claude 审 diff → 规则判定 → 返工(≤ max_revisions)
  ── 人工门控②(最终):approve / reject / edit ──────────
  → final.md + state.json
```

`--auto` 时:跳过所有"回合边界暂停",讨论直接连跑到 max_rounds 再汇总(人仍在两个 human gate 处确认,除非未来加 `--yes`)。

---

## 4. 讨论机制(结构化 + 三方 + 可追踪)

### 4.1 角色与轮次
- **第0轮 计划**:复用 `PlannerOutput`。Claude、Codex 各自独立从主题出计划,**互不可见**(build_user 只含主题)。
- **讨论轮**:每轮 Claude 先、Codex 后(固定顺序)。每个 agent 的 `build_user` 含:主题 + **目前为止完整对话记录(含人的插话)**。
- 轮次上限 `max_rounds`(默认 3);人可在任一回合边界选 `end` 提前进入汇总。

### 4.2 新增 schema(`schemas.py`)
- `DiscussionTurn(BaseModel)`:`response: str`、`agreements: list[str] = []`、`concerns: list[str] = []`、`revised_steps: list[str] = []`。
- `ConsensusPlan(BaseModel)`:`summary: str`、`steps: list[str]`、`rationale: str`、`open_questions: list[str] = []`。
- 两者均不以 `Test` 开头,无需 `__test__ = False`。

### 4.3 共享对话记录(含人)
- 内存有序记录;每步追加 `{round: int, agent: "claude"|"codex"|"human", kind: "plan"|"turn"|"interjection", content: dict|str}`。
- `state.discussion` 聚合该记录;落盘 `discussion/transcript.md`(人类可读,按轮按参与者)+ 每步结构化 JSON。
- **人的插话**是其中 `agent:"human", kind:"interjection"` 的条目;后续 agent 的 build_user 会把它一并呈现。

### 4.4 回合边界介入控制(可注入)
- 抽象一个 `discussion_control(state, round, *, printer) -> ControlDecision`,默认实现为交互式终端提示(读一次输入)。
- `ControlDecision`:`action ∈ {continue, interject, end, abort}` + `interjection: str = ""`。
- `--auto` 时注入"始终 continue"的控制器。
- 测试时注入脚本化控制器(返回预设动作序列)。

### 4.5 共识与既定计划交接
- Claude 汇总产出 `ConsensusPlan`;其 `steps` 作为**既定计划**喂实现阶段(等价 Stage A 的 Planner steps)。
- 实现阶段不再重新规划;`_implementation_loop` 的 Executor 基于共识 steps + 上轮 review 反馈工作。

---

## 5. 终端逐轮呈现

- 每步(计划 / 讨论轮 / 人插话 / 共识)完成即打印带醒目标题整段,如:
  ```
  ━━━ Codex · 第 1 轮 ━━━
  [concerns] 计划 A 未考虑迁移回滚
  [response] 建议先加兼容层,分两步切换……
  [revised steps] 1. …  2. …
  ━━━ 你(human)· 第 1 轮后插话 ━━━
  请优先考虑零停机迁移。
  ```
- 通过编排器 `printer`(默认 `print`,测试可注入)输出;不引入实时流式 I/O。
- Stage B 原始事件流 / subagent 摘要照常落 `.macr/runs/<id>/subagents/`。

---

## 6. 结构与复用(方案 A:抽出共享实现循环)

- 从 `collab_orchestrator.py` 抽出 `_implementation_loop(...)`:封装 Stage A 的 `executor→diff→test→review→eval` 返工循环(含 TraceSink 接线、`state.decisions`/`state.subagents` 更新、AgentError→BLOCKED);**不含** worktree 创建与 human gate。
- `run_collab`(Stage A)重构为:建 worktree → Claude planner → `_implementation_loop` → human gate → finalize。**对外行为与签名不变**,Stage A 全部测试须保持绿。
- 新增 `discussion.py` 的 `run_discuss(...)`:建 worktree → 讨论阶段(含回合边界控制)→ 共识 → human gate① →(批准则)`_implementation_loop` → human gate② → finalize。
- 讨论/规划步两个 agent 以 worktree 为 cwd **只读**(Claude 只读工具白名单;Codex 讨论步 `--sandbox read-only`);仅实现步 Codex 用 `workspace-write`。
  - 需让 Codex 后端支持按调用指定 sandbox(构造参数或独立实例);讨论用 `read-only` 实例、实现用 `workspace-write` 实例,或加一个 `sandbox` 入参。

---

## 7. 数据模型扩展(`schemas.py`)

- 新增 `DiscussionTurn`、`ConsensusPlan`(§4.2)。
- `SharedState` 新增字段(向后兼容,默认值):`topic: str | None = None`、`discussion: list[dict] = []`、`consensus: dict | None = None`。

---

## 8. CLI(`cli.py`)

- 新增子命令 `discuss`:参数同 `collab` + `--max-rounds`(默认 3)+ `--auto`(跳过回合边界暂停)。
- `main(...)` 增加 `discuss` 分发;复用注入式 `claude_backend`/`codex_backend`/`human_gate`,并新增可注入 `discussion_control` 以便测试。
- 退出码:`0` = 最终 approve;非 0 = 任一门控 reject / 讨论 abort / 出错。
- 默认开启 subagent(沿用 Stage B),`--no-subagents` 可关。

---

## 9. run 目录新增

```
.macr/runs/<run_id>/
  topic.md
  discussion/
    plan.claude.md        plan.codex.md
    round1.claude.json     round1.codex.json
    round1.human.txt                          # 若该轮后有插话
    round2.* ...           round3.* ...
    transcript.md
  consensus.md
  (随后是 Stage A 实现阶段产物:executor.output.vN.md / diff.vN.patch / test.vN.* / reviewer.output.md / evaluator.output.json)
  subagents/   final.md   state.json
```

---

## 10. 错误处理

- 沿用 Stage A/B:CLI 缺失→退出 2;CLI 非零退出/解析失败→重试→BLOCKED;任意异常→`try/finally` 落 `state.json`→退出非 0。
- 讨论阶段某 agent 两次失败(AgentError):记 BLOCKED,跳过后续讨论,直接让 Claude 基于已有记录尝试汇总;汇总也失败→进人工门控①并标注。
- 人选 `abort`:保存 `discussion/` 与现场,退出非 0,不进实现。
- 共识 reject:不进实现,保留讨论记录与 worktree,退出非 0。

---

## 11. 测试策略(TDD)

- `DiscussionTurn` / `ConsensusPlan` schema 单测;`transcript.md` 拼装单测(顺序、按轮按参与者、含 human)。
- `_implementation_loop` 抽取后:Stage A 的 `test_collab_orchestrator.py` + `test_collab_orchestrator_subagents.py` **全部保持绿**(重构回归)。
- `discussion_control` 默认交互实现:用注入 `input_fn` 测 continue/interject/end/abort 解析。
- `run_discuss` 用 `FakeAgentBackend`(脚本化:双计划 + 各轮 DiscussionTurn + Claude 共识)+ 注入 `discussion_control`(脚本化动作)+ 真临时 git 仓库跑全程,断言:
  - 讨论记录顺序与 `state.discussion` 聚合正确;
  - **人插话进入 transcript,且后续 agent 的 build_user 能看到它**;
  - `end` 提前定稿 → 跳过剩余轮直接汇总;`abort` → 不进实现、退出语义正确;
  - `discussion/` 与 `consensus.md` 落盘;
  - 人工门控①:reject → 不进实现;approve → 进入实现并产出 `final.md`;
  - `printer` 被逐轮调用(注入假 printer,断言含轮次/参与者标题)。
- CLI `discuss` 子命令:注入后端 + 控制器 + 临时 git 仓库,断言 approve→0 / 共识 reject→非 0 / abort→非 0;`--auto` 不暂停。
- 真实 `claude`/`codex` 仅在冒烟脚本(`scripts/smoke_discuss.py`)。
- commit 无 AI 署名;依赖只在 `.venv`。

---

## 12. 完成标准(Definition of Done)

- [ ] `macr discuss "<主题>" --repo <p> --test-cmd "..."` 能跑完:双规划 → 含人插话的多轮讨论 → Claude 共识 → 人工门控① → Stage A 实现 → 人工门控② → `final.md`。
- [ ] **回合边界**可 `continue/interject/end/abort`;插话进 transcript 并影响后续轮次;`--auto` 跳过暂停。
- [ ] 终端逐轮打印各参与者(Claude/Codex/human)发言(带轮次/角色标题)。
- [ ] `discussion/`(双计划 + 各轮 JSON + 人插话 + `transcript.md`)与 `consensus.md` 落盘;`state.discussion`/`state.consensus` 入 `state.json`。
- [ ] 讨论/规划步两个 agent **只读** worktree;实现步 Codex 方可写。
- [ ] `_implementation_loop` 抽取完成,Stage A 全部测试与行为不变。
- [ ] 全部单元 + 集成测试通过(FakeAgentBackend + 注入控制器 + 真临时 git 仓库,不触真实 CLI);V1/Stage A/Stage B 零回归。
- [ ] 双栏 live TUI 明确不在本阶段(留作 C2)。
