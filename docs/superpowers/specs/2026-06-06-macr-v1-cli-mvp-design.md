# MACR V1 CLI MVP — 设计规格(Design Spec)

> 日期:2026-06-06
> 阶段:V1(CLI MVP — 编排骨架)
> 前置:V0 文档已完成(`README.md`、`docs/`)。本 spec 实现 `docs/roadmap.md` 的 V1。

---

## 1. 目标与非目标

### 目标
- 用纯 Python 手写一个**极简编排器**,跑通 MACR 的核心闭环:
  `Task → Planner → Executor → Reviewer → Evaluator →(返工)→ Human Gate → Final`。
- 验证 MACR **自己的**协议与编排机制(结构化消息、共享状态、角色边界、决策日志、可追溯落盘),而非多模型协作或真实编码实用性。
- 所有 Agent 统一调用 Claude API,靠角色 prompt + 输出 schema 区分。
- 全过程产物写入 `.macr/runs/<run_id>/`,可复现、可追溯。

### 非目标(YAGNI,留给后续版本)
- 不引入 LangGraph 或任何重型编排框架(手写)。
- 不做多模型/Codex 协作(V1 之后)。
- Executor 不碰真实代码库、不跑 git/工具/测试;不接 Tester 角色。
- 不做状态持久化恢复 / `resume` 命令(Human Gate 为交互式阻塞)。
- 不做 Web/UI(V2)。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| MVP 首要证明 | 编排闭环机制(非多模型、非真实编码实用性) |
| 语言/编排 | Python + 手写极简状态机编排器(无 LangGraph) |
| 任务形态 | 通用文本任务;Executor 产出文本产物写入 run 目录;不碰 git/工具/测试;V1 不接 Tester |
| 结构化输出 | Anthropic SDK tool-use 强制 schema(每角色一个 submit tool) |
| Human Gate | 交互式阻塞确认(approve/reject/edit),决定写入 run 目录 |
| Agent 建模 | 方案 A:角色规格(role spec)驱动的单一通用 Agent |

---

## 3. 包结构与模块职责

```
macr/                    # Python 包(pyproject 管理)
  __init__.py
  cli.py                 # 入口:`macr run "<task>"`,解析参数,启动一次 run
  config.py              # API key、模型名、max_revisions 等(env + 默认值)
  schemas.py             # Pydantic:Message、MessageType 枚举、各角色 content schema、Decision 枚举、SharedState
  blackboard.py          # SharedState 操作 + 序列化(内存对象)
  llm.py                 # 唯一网络边界:Anthropic 客户端封装,call_role(role_spec, context) → 校验后的 content 模型
  roles.py               # 四个角色的 role spec:system prompt + content schema + 输入选择器 + tool 名
  agent.py               # 通用 Agent:吃 role spec,组装 context,调 llm,产出一条 Message
  orchestrator.py        # Supervisor 循环:调度四角色、返工循环、转 Human Gate
  human_gate.py          # 交互式 approve/reject/edit
  runlog.py              # 写 .macr/runs/<run_id>/ 各文件
tests/
pyproject.toml
```

设计原则:每个文件单一职责;`llm.py` 是唯一触网模块(测试时整体注入 FakeLLM)。

### Agent 建模(方案 A)
四个角色的差异本质是三项数据:**system prompt + 输出 content schema + 读取哪些 blackboard 输入**。因此用 `roles.py` 以数据描述每个角色,`agent.py` 提供一个通用 `Agent.run(role_spec, blackboard) -> Message`。新增/调整角色 = 改一条配置,无需新类。

---

## 4. 数据模型(`schemas.py`)

对齐 V0 `docs/message_protocol.md`。

- **`Message`**:`task_id`、`run_id`、`agent_id`、`role`、`message_type`、`content`(object)、`references[]`、`timestamp`、`status`。
- **`MessageType`** 枚举:V0 定义的 12 种;MVP 实际使用 `proposal`/`plan`/`result`/`review`/`revision_result`/`evaluation`/`decision`/`human_feedback`。
- **`Decision`** 枚举:`PASS` / `NEEDS_FIX` / `BLOCKED`。
- 各角色 content 模型(即 tool-use input schema):
  - `PlannerOutput`:`summary: str`、`steps: list[str]`、`tools_needed: list[str]`、`risks: list[str]`
  - `ExecutorOutput`:`artifact: str`(正文/代码片段)、`notes: str`、`evidence: list[str]`
  - `ReviewerOutput`:`summary: str`、`findings: list[Finding]`、`decision: Literal["approve","needs_fix"]`
    - `Finding`:`level: Literal["blocking","non_blocking"]`、`issue: str`、`evidence: str`、`recommendation: str`
  - `EvaluatorOutput`:`decision: Decision`、`reasons: list[str]`、`confidence: float`
- **`SharedState`**:`run_id`、`user_query`、`task_plan`、`agent_outputs: {planner:[], executor:[], reviewer:[], evaluator:[]}`、`reviews: []`、`decisions: []`、`human_feedback: HumanFeedback | None`、`final_output: str | None`。
  - `HumanFeedback`:`decision: Literal["approve","reject"]`、`feedback: str`、`timestamp`。

---

## 5. 编排流程(`orchestrator.py`)

```
macr run "<task>"
  → 生成 run_id,初始化 SharedState,写 input.md
  → Planner 产出 proposal/plan         → 写 planner.output.md,存入 state
  → 返工循环(最多 max_revisions 次,默认 2):
       Executor 执行(返工时携带上一轮 Reviewer 反馈)
                                        → 写 executor.output.md(返工保留历史 executor.output.vN.md)
       Reviewer 审查 Executor 产物       → 写 reviewer.output.md
       Evaluator 基于 result + review 判定 → 写 evaluator.output.json
       若 Evaluator.decision == PASS        → 跳出循环
       若 == NEEDS_FIX 且仍有返工额度       → 继续下一轮(Executor 重做)
       若 == BLOCKED 或 返工额度耗尽        → 跳出循环,标记进 Human Gate
  → Human Gate:交互式 approve / reject / edit,写 human_feedback 入 state
  → 产出 final.md(最终产物 + 决策轨迹摘要),写 state.json 快照
```

约束:
- **返工上界** `max_revisions`(默认 2,可配置)防止无限循环,贴合"任务收敛"目标。
- Supervisor/orchestrator 只按协议路由,不做专业判断(贴合 V0 角色边界)。
- 协议对齐 V0 `message_protocol.md` §对话协议:Reviewer 只审 result;Evaluator 基于 result+review;NEEDS_FIX 触发返工;BLOCKED 进 Human Gate。

---

## 6. LLM / tool-use 集成(`llm.py`)

- 每角色一个 tool:`submit_plan` / `submit_result` / `submit_review` / `submit_evaluation`,input schema = 对应 content 模型的 JSON Schema(由 Pydantic 生成)。
- 调用时 `tool_choice` 强制使用该角色的 tool;从响应的 `tool_use` block 取 input → 用 Pydantic 校验 → 返回 content 模型。
- 默认模型 `claude-sonnet-4-6`(`config.py` 可覆盖);启用 prompt caching(角色 system prompt 可缓存)。
- 失败处理:未走 tool / 校验失败 → 重试 1 次(把校验错误回传给模型);再失败 → 该步标 `BLOCKED` 进 Human Gate,**不静默吞错**。

---

## 7. 运行落盘(`runlog.py`)

对齐 V0 `docs/workflow_templates.md` 的目录约定,并增加 `state.json` 快照。

```
.macr/runs/<run_id>/
  input.md
  planner.output.md
  executor.output.md          # 返工时历史保留为 executor.output.v1.md, v2.md ...
  reviewer.output.md
  evaluator.output.json
  state.json                  # 完整 SharedState 快照(可复现、可追溯)
  final.md
```

- `run_id` 格式:`R<YYYYMMDD>_<NNN>`(序号按当日 `.macr/runs/` 下已有目录递增,避免随机源)。
- 每步**先落盘再继续**,任何中断都留下可追溯现场。

---

## 8. 错误处理

- 缺 `ANTHROPIC_API_KEY` / 网络错误:CLI 友好报错,退出码非 0,已产出的中间文件保留。
- 结构化输出失败:按 §6 重试 → BLOCKED → Human Gate。
- 任何角色步骤异常:落盘当前 state.json,报错退出非 0。

---

## 9. 测试策略(TDD)

- `llm.py` 为唯一网络边界 → 测试注入 **FakeLLM**,返回脚本化的结构化 content。
- 单元测试:
  - schemas 校验(合法/非法 content)。
  - blackboard 读写与序列化往返。
  - runlog 文件产出(文件存在 + 内容正确)。
  - orchestrator 状态流转三条路径:PASS 直通 / NEEDS_FIX 返工一次后 PASS / BLOCKED 转门控 / 返工额度耗尽转门控。
- 集成测试:FakeLLM 跑完整一条 run,断言 `.macr/runs/<id>/` 全部文件 + `final.md` 内容 + `state.json` 决策轨迹;Human Gate 用注入的假输入(approve / reject 各一条)。
- 不打真实 API;真实 API 仅保留一个手动冒烟脚本(不进自动化测试)。

---

## 10. CLI 交互

- `macr run "<task>"`:跑完整闭环,终端流式打印每个角色的 `summary` + `decision`,最后在 Human Gate 阻塞等待输入。
- 选项:`--max-revisions N`、`--model <name>`。
- Human Gate 输入三选一:
  - `[a]pprove` — 直接批准,`decision=approve`,`feedback` 为空。
  - `[r]eject` — 驳回,提示输入理由,`decision=reject`,理由存入 `feedback`。
  - `[e]dit` — 批准但附带修改意见/批注:提示输入反馈文本,`decision=approve` 且 `feedback` 非空;该反馈文本追加到 `final.md` 的"人工批注"小节。
- `decision` 取值与 §4 `HumanFeedback` 一致(仅 `approve`/`reject`;`edit` 是"带反馈的 approve")。
- 退出码:`0` = 人工 approve(含 edit);非 0 = reject 或出错。

---

## 11. 完成标准(Definition of Done)

- [ ] `macr run "<task>"` 能用真实 Claude API 跑完一条完整闭环,产出 `.macr/runs/<run_id>/` 全套文件。
- [ ] 四角色均通过 tool-use 产出通过 Pydantic 校验的结构化 content。
- [ ] 返工循环、`max_revisions` 上界、BLOCKED→Human Gate 行为符合 §5。
- [ ] Human Gate 三种交互(approve/reject/edit)正确写入 `human_feedback` 并影响 `final.md` 与退出码。
- [ ] 全部单元 + 集成测试通过(FakeLLM,不打真实 API)。
- [ ] 落盘文件命名与结构对齐 V0 `workflow_templates.md`。
