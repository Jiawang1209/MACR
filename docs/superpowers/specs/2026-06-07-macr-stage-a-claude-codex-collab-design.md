# MACR 阶段 A — Claude⟷Codex 异构代码协作 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage A(异构两 agent 协作;嵌套 subagent 留到 Stage B)
> 前置:V0 文档 + V1 CLI MVP 已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。

---

## 1. 目标与非目标

### 目标
- 让 **Claude(claude CLI)** 与 **Codex(codex CLI)** 作为两个**真实的异构 agent**,在 MACR 协议下协作完成一个软件开发任务。
- 形态:Codex 在隔离 git worktree 中**真实改代码**,框架**运行测试**,Claude 综合 **git diff + 测试结果**审查,按"改—测—审—返工"线性闭环迭代,最终经 **Human Gate** 人工确认。
- 复用 V1 的 SharedState / RunLog / Message schema / 角色概念;只在"Agent 后端"与"带 worktree+测试"上分叉。
- **纯 CLI 运行,不需要任何 API key。** 同时保留 API 后端作为休眠的预留实现。

### 非目标(YAGNI / 留待后续)
- 不做嵌套 subagent(Claude/Codex 各自派生子 agent)—— Stage B。
- 不做"共识优先回合制"(双方都出方案并互审)—— 线性流水之后的增量。
- 不自动 merge worktree 回 target repo(人工合并)。
- 不在本阶段实际调用 API 后端(仅保留接口与休眠实现)。
- 不做 Web/UI;不做 tmux 多窗格编排(子进程足够)。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 范围 | 仅 Stage A:Claude⟷Codex 异构两 agent;嵌套留 Stage B |
| 驱动通道 | CLI 子进程,**对称**:Claude=`claude -p`,Codex=`codex exec` |
| 作业对象 | 真实代码,在隔离 **git worktree** 中改文件 |
| 测试 | **包含**:框架在 worktree 跑 `--test-cmd`,测试结果作为证据 |
| 协作形状 | **线性流水**(Claude 规划/审查/判定,Codex 实现/修复) |
| 代码结构 | 方案 A:扩展 `macr` 包,泛化 `AgentBackend` 抽象 |
| Evaluator | **确定性规则**(测试全过 + Reviewer 非 blocking → PASS) |
| approve 后 | **不自动 merge**,保留 worktree + diff 供人工合并 |
| Claude 后端 | 走 `claude -p`(对称 CLI),非 API |
| API 后端 | **留位不启用**:`ApiBackend` 作休眠预留实现,经同一接口未来可切 |

---

## 3. 角色落位与协作流(线性)

```
Claude(claude -p)  : Planner(出方案) / Reviewer(审 diff+测试) / [Evaluator 见 §6 为规则]
Codex(codex exec)  : Executor(在 worktree 改代码) / 按反馈修复
框架(Python)       : worktree 管理 + 跑测试 + 编排 + Evaluator 规则 + Human Gate
```

```
macr collab "<task>" --repo <path> --test-cmd "pytest -q"
  → 生成 run_id;从 target repo 切隔离 worktree;写 input.md
  → Claude Planner 出方案                       → planner.output.md,存入 state
  → 返工循环(≤ max_revisions,默认 2):
       Codex Executor 按方案(+上轮 review 反馈)在 worktree 改文件
                                                 → 捕获 git diff → diff.vN.patch
       框架 在 worktree 跑 --test-cmd            → TestResult → test.vN.log + test.vN.json
       Claude Reviewer 综合 diff + 测试结果审查   → reviewer.output.md
       Evaluator(规则)判定 PASS/NEEDS_FIX/BLOCKED → evaluator.output.json,记入 decisions
       若 PASS / BLOCKED / 额度耗尽 → 跳出
  → Human Gate:展示最终 diff + 测试结论 + 决策轨迹;approve / reject / edit
  → final.md + state.json;approve 后保留 worktree 供人工 merge(不自动合并)
```

---

## 4. 模块结构(扩展 `macr/`)

```
macr/
  agents/
    __init__.py
    base.py            # AgentBackend 协议:run_role(role, state, *, run_id, task_id, timestamp=None) -> Message
    api_backend.py     # ApiBackend:包装 V1 的 AnthropicLLM(休眠预留;collab 不启用)
    cli_backend.py     # ClaudeCliBackend(claude -p) / CodexCliBackend(codex exec)
  worktree.py          # Worktree:从 target repo 建/取 diff/清理
  testrunner.py        # run_tests(worktree_path, test_cmd, timeout) -> TestResult
  collab_roles.py      # 协作角色 spec(build_user 纳入 diff + 测试结果)
  collab_orchestrator.py  # 线性异构编排 run_collab(...)
  config.py(扩展)     # CollabConfig:repo/test_cmd/claude_model/codex_model/sandbox/timeout/max_revisions
  schemas.py(扩展)    # TestResult;SharedState 加 target_repo/worktree_path/diffs/test_results
  cli.py(扩展)        # 新增 `macr collab` 子命令
scripts/smoke_collab.py # 真实 claude+codex 手动冒烟(不进自动化测试)
```

V1 既有模块(`agent.py`/`llm.py`/`roles.py`/`orchestrator.py`/`runlog.py`/`schemas.py`/`utils.py`/`cli.py`)保持可用;`macr run` 路径不变。

### 4.1 `AgentBackend` 抽象(预留 API 缝)
```
AgentBackend(Protocol):
    name: str
    run_role(role, state, *, run_id, task_id, timestamp=None) -> Message
```
实现:
- `ClaudeCliBackend` —— Stage A 启用。`claude -p "<prompt>" --output-format json`;prompt = role.system_prompt + role.build_user(state) + "只输出符合以下 JSON Schema 的对象";解析返回 JSON 的 `result` 字段为该 role 的 content 模型;**复用 V1 的"校验失败重试一次"**(见 `agent.py` 逻辑),二次失败抛 `AgentError`。
- `CodexCliBackend` —— Stage A 启用(仅 Executor)。`codex exec "<prompt>" --output-schema <schemafile> -o <outfile> --cd <worktree> --sandbox workspace-write --ask-for-approval never --model <codex_model>`;Codex 改 worktree 文件 + 写 schema 校验过的 `ExecutorOutput` JSON 到 `outfile`;读 `outfile` → Pydantic。**diff 由 `worktree.diff()` 取,不依赖 Codex 自报。**
- `ApiBackend(llm)` —— 休眠预留。包装现有 `AnthropicLLM` + V1 `run_agent` 逻辑;collab 流程不实例化它;未来 `--backend api` 可切。

> 原则:**协作流仅依赖 CLI;API 后端作为休眠的预留实现保留,通过同一 `AgentBackend` 接口未来可切换。** `macr collab` 不读取 `ANTHROPIC_API_KEY`。

### 4.2 `worktree.py`
- `Worktree.create(repo: Path, run_id) -> Worktree`:校验 repo 是 git 仓库且工作区干净;记当前 `base_commit = git rev-parse HEAD`;`git worktree add --detach <.macr/worktrees/run_id> <base_commit>`(detached,不新建分支,避免分支污染);记 `worktree_path`、`base_commit`。
- `.diff() -> str`:在 worktree 内 `git add -A`(纳入新增/未跟踪文件)后 `git diff --cached`,返回 patch 文本(捕获 Codex 的全部改动,含新文件)。
- `.cleanup()`:`git worktree remove --force <worktree_path>`(reject 时按需调用;approve 时**不**调用,保留供人工合并)。

### 4.3 `testrunner.py`
- `run_tests(worktree_path, test_cmd: list[str], timeout: int) -> TestResult`:在 worktree 内 `subprocess.run(test_cmd, cwd=worktree_path, timeout=...)`,捕获 returncode + stdout/stderr;超时/命令不存在记为失败。

---

## 5. 数据模型(扩展 `schemas.py`)

- **`TestResult`**:`passed: bool`、`exit_code: int`、`log: str`、`command: str`、`timed_out: bool = False`。
- **`ExecutorOutput`**(复用 V1):`artifact`(Codex 的工作摘要/说明)、`notes`、`evidence`;真实改动以 diff 体现,不放进该字段。
- **`SharedState`**(扩展,向后兼容,新增字段均有默认值):
  - `target_repo: str | None = None`
  - `worktree_path: str | None = None`
  - `diffs: list[str] = []`(每次尝试一份)
  - `test_results: list[dict] = []`(每次尝试一份,`TestResult` 的 dump)
- 角色 content 模型 `PlannerOutput` / `ReviewerOutput` 复用 V1;`ReviewerOutput.decision ∈ {approve, needs_fix}`、`findings[]`。

---

## 6. Evaluator(确定性规则,框架实现)

不调用模型。输入:本轮 `TestResult` + 本轮 `ReviewerOutput` + agent 调用是否异常。规则:

```
若 本轮存在 agent 调用失败(AgentError)         → BLOCKED
否则若 TestResult.passed 为 False               → NEEDS_FIX(证据:测试日志)
否则若 Reviewer 有 level == "blocking" 的 finding → NEEDS_FIX(证据:review)
否则                                            → PASS
```
- `decision` 写入 `state.decisions`(含 attempt、依据);`evaluator.output.json` 落盘。
- 理由:有真实测试结果时,规则门控比再调模型更可靠、可复现,贴合"证据驱动"。

---

## 7. 运行落盘(扩展 V1 run 目录)

```
.macr/runs/<run_id>/
  input.md
  planner.output.md
  executor.output.vN.md        # 每次尝试 Codex 的工作摘要
  diff.vN.patch                # 每次尝试捕获的 git diff
  test.vN.log                  # 每次尝试测试 stdout/stderr
  test.vN.json                 # 每次尝试 TestResult 结构化
  reviewer.output.md           # 每轮覆盖为最新一轮审查(与 V1 一致)
  evaluator.output.json        # 规则判定结果
  state.json                   # 完整 SharedState 快照(含 worktree_path/diffs/test_results)
  final.md                     # 最终 diff 摘要 + 测试结论 + 决策轨迹 + 人工决定
```
worktree 本体在 `.macr/worktrees/<run_id>/`(gitignored)。

---

## 8. 配置与 CLI

- **`CollabConfig`**:`target_repo: Path`、`test_cmd: list[str]`、`claude_model: str | None`、`codex_model: str | None`、`sandbox: str = "workspace-write"`、`approval: str = "never"`、`timeout: int = 1800`、`max_revisions: int = 2`。
- **CLI**:`macr collab "<task>" --repo <path> --test-cmd "pytest -q" [--max-revisions N] [--claude-model M] [--codex-model M] [--timeout S]`。
- 退出码:`0` = 人工 approve(含 edit);非 0 = reject 或出错。
- Human Gate 复用 V1 的 `interactive_human_gate`,展示信息扩展为「最终 diff 摘要 + 测试结论」。

---

## 9. 错误处理

- 找不到 `claude` 或 `codex` 可执行文件 → 友好报错,退出码 2。
- target repo 不是 git 仓库 / 工作区脏 → 报错退出,不创建 worktree。
- CLI 非零退出 或 JSON 解析/Schema 校验失败 → 重试一次(把错误回传给 agent)→ 仍失败标 BLOCKED → Human Gate(与 V1 §6 一致,不静默吞错)。
- 测试命令不存在 / 超时 → 记为 `TestResult(passed=False, timed_out=...)`,作为证据继续(交 Evaluator → NEEDS_FIX)。
- 任意步骤异常:`try/finally` 落盘 `state.json` 后再退出非 0(与 V1 修复后的行为一致)。

---

## 10. 测试策略(TDD)

- **子进程是唯一外部边界**:在 `cli_backend.py` 中,实际 `subprocess` 调用经一个可注入的薄封装(类似 V1 的 LLM 注入)。单测用 `FakeAgentBackend`(脚本化返回 content + 可选"模拟改文件"回调)注入,编排测试不触真实 CLI。
- `worktree.py` / `testrunner.py` 对**真实临时 git 仓库**测:`tmp_path` 里 `git init` + 提交一个文件,做改动,断言 `.diff()` 文本;`run_tests` 用简单命令(`["true"]` / `["false"]` / `["python","-c","import sys;sys.exit(0/1)"]`)断言 `TestResult`。确定性、无网络。
- `collab_orchestrator` 用 `FakeAgentBackend` + 真临时 worktree + 简单 test-cmd 跑全流程,断言:run 目录全部文件、`diffs`/`test_results` 入 state、四条路径(PASS / 测试挂→NEEDS_FIX→修复后 PASS / blocking review→NEEDS_FIX / agent 失败→BLOCKED / 额度耗尽)、Human Gate approve/reject。
- Evaluator 规则单测:四种输入组合 → 期望 decision。
- 真实 `claude` + `codex` 仅在 `scripts/smoke_collab.py` 手动冒烟,不进 pytest 套件。
- **commit 无 AI 署名;依赖只在项目 `.venv`。**

---

## 11. 完成标准(Definition of Done)

- [ ] `macr collab "<task>" --repo <path> --test-cmd "..."` 能用真实 `claude` + `codex` 跑完一条完整闭环:Codex 在 worktree 改代码、框架跑测试、Claude 审 diff、规则判定、Human Gate。
- [ ] 全程**不需要任何 API key**;`AgentBackend` 保留 `ApiBackend` 休眠实现。
- [ ] `.macr/runs/<run_id>/` 产出 §7 全套文件(含 diff.vN.patch、test.vN.json、state.json、final.md)。
- [ ] 返工循环、`max_revisions`、BLOCKED/额度耗尽→Human Gate、approve 不自动 merge,均符合本 spec。
- [ ] 全部单元 + 集成测试通过(FakeAgentBackend + 真临时 git 仓库,不触真实 CLI/网络)。
- [ ] V1 的 `macr run` 路径与测试不受影响,仍全绿。
