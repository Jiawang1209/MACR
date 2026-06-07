# MACR Stage B — 原生嵌套 subagent + 可追踪 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage B(给 Claude / Codex 各自加"原生 subagent"能力,并使其可追踪)
> 前置:V0 文档、V1 CLI MVP、Stage A(Claude⟷Codex 异构协作)已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。

---

## 1. 目标与非目标

### 目标
- 让 `macr collab` 调用的 **Claude(`claude` CLI)** 与 **Codex(`codex` CLI)** 能各自使用**原生 subagent**(嵌套的第二层 agent)分工干活。
- 让这层嵌套**对 MACR 可追踪**:把每个 CLI 的 subagent 活动(原始事件流 + 结构化摘要)捕获进 `.macr/runs/<run_id>/subagents/`,贴合 MACR"可追踪、可复现"的核心理念。
- 保持纯 CLI、零 API key;不破坏 V1(`macr run`)与 Stage A 现有行为与测试。

### 非目标(YAGNI / 留待后续)
- 不编写自定义 subagent 定义文件(`.claude/agents/*.md` / `~/.codex/agents/*.toml`)—— 仅使用各 CLI 内置 subagent(Claude 的 `Explore`/`general-purpose`,Codex 的 `worker`/`explorer`)。
- 不试图突破 Claude 的"一层嵌套"硬限制(官方:subagent 不能再 spawn subagent,不可配置)。
- 不调高 Codex `agents.max_depth`(保持默认 1)。
- 不做 MACR 自建的第二层编排(不依赖 CLI 原生能力的方案)。
- 不做 Web/UI。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 范围 | 开启原生 subagent **+ 可追踪**(捕获事件) |
| 捕获粒度 | **摘要 + 原始事件流**落进 `.macr/runs/` |
| subagent 类型 | **仅内置**(不写自定义定义文件) |
| 捕获接入方式 | 方案 A:`run_role` 增加**可选 `trace` 参数**(最小侵入,旧后端忽略) |
| 默认开关 | `macr collab` **默认开启** subagent;`--no-subagents` 可关 |
| Claude 角色 cwd | 以 **worktree 为 cwd**(让其 subagent 能读代码库;仍只读不写) |

---

## 3. 已核实的关键事实(决定设计边界)

- **两边都有原生 subagent,且"何时 spawn"由 CLI 内部模型决定**;编排器只能通过 prompt + 工具许可"引导",不能直接命令 spawn。
- **Claude(headless)**:`claude -p ... --allowedTools "...,Agent"` 开启 `Agent` 工具即可 spawn subagent;**嵌套仅一层,硬限制不可配**。可观测性:`--output-format stream-json --verbose --include-partial-messages`,事件含 `parent_tool_use_id`(非空=来自某 subagent)。
- **Codex(headless)**:`features.multi_agent` **默认开**;`codex exec --sandbox workspace-write --ask-for-approval never` 下可 spawn;深度默认 1、并发默认 6。可观测性:`codex exec --json` 输出 JSONL(`thread.*`/`turn.*`/`item.*` 事件)。
- **⚠️ 两者完整事件 schema 无法从文档 100% 核实** —— 见 §7 防御式解析 + 冒烟校准。

---

## 4. 模块结构(扩展 `macr/`)

```
新增:
  macr/agents/trace.py        # 解析函数 + TraceSink + SubagentRecord
改动:
  macr/agents/base.py         # run_role 增加可选 trace=None;FakeAgentBackend/ApiBackend 接受并忽略
  macr/agents/cli_backend.py  # Claude→stream-json+Agent+cwd;Codex→--json;两者捕获事件→trace
  macr/collab_orchestrator.py # 每"角色×尝试"建 TraceSink 传入;聚合 state.subagents
  macr/schemas.py             # 新增 SubagentRecord;SharedState 加 subagents 字段
  macr/cli.py                 # collab 增 --no-subagents;按此构造 CLI 后端
新增脚本/文档:
  scripts/smoke_collab.py     # 复用;冒烟时据真实事件流校准解析器(见 §7)
```

### 4.1 `AgentBackend.run_role` 签名变更(向后兼容)
```
run_role(role, state, *, run_id, task_id, timestamp=None, trace: TraceSink | None = None) -> Message
```
- `trace` 为**可选**关键字参数,默认 `None`。
- `ApiBackend`、`FakeAgentBackend`(V1/Stage A 既有后端)**接受该参数并忽略**(`FakeAgentBackend` 可选地在收到 trace 时写一条脚本化摘要,用于测试编排器接线)。
- 仅 CLI 后端在 `trace` 非空时落盘事件流 + 摘要。

---

## 5. 捕获模型(`agents/trace.py`)

### 5.1 数据结构
- `SubagentRecord(BaseModel)`:
  - `source: Literal["claude", "codex"]`
  - `agent_type: str = "unknown"`(尽力解析:Claude 从 `Agent` 工具调用的 `subagent_type`,Codex 从 spawn 事件;取不到记 "unknown")
  - `ref: str`(Claude=`parent_tool_use_id`;Codex=spawned thread id)
- `SharedState.subagents: list[dict]`(每条:`{role, attempt, count, types: list[str]}`)。

### 5.2 解析函数(防御式,见 §7)
- `parse_claude_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]`
  - `final_text`:取 `type == "result"` 事件的 `result` 字段;取不到则回退为所有主-agent 文本拼接。
  - subagent 列表:收集所有**非空 distinct** `parent_tool_use_id`;尽力把 id 映射到 `Agent` 工具调用的 `subagent_type`。
- `parse_codex_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]`
  - `final_text`:取最后一条 agent 消息类 `item.completed`(或等价)的文本;取不到则回退为可见文本拼接。
  - subagent 列表:收集非根 `thread.started`(或 spawn 类 item)的 distinct thread id。
- 两函数对**未知/缺失字段必须不崩**;无法解析出任何 `final_text` 时返回空串(由后端据此触发重试/BLOCKED)。

### 5.3 `TraceSink`
```
TraceSink(directory: Path, label: str)
  .capture(raw_lines: list[str], subagents: list[SubagentRecord]) -> None
     # 写 <label>.events.jsonl(raw_lines 原样,逐行)
     # 写 <label>.subagents.json(SubagentRecord 列表的 JSON)
```

### 5.4 run 目录新增
```
.macr/runs/<run_id>/subagents/
  planner.v1.events.jsonl    planner.v1.subagents.json
  executor.v1.events.jsonl   executor.v1.subagents.json
  reviewer.v1.events.jsonl   reviewer.v1.subagents.json
  ...(每轮每角色;label = "<role>.v<attempt>")
```

---

## 6. 后端改动(`cli_backend.py`)

构造参数新增:`enable_subagents: bool = True`(由 CLI 的 `--no-subagents` 取反传入)。

### 6.1 ClaudeCliBackend
- argv:`claude -p <prompt> --output-format stream-json --verbose --include-partial-messages --allowedTools "<tools>" [--model M]`;
  - `<tools>` = `Read,Grep,Glob,Agent`(只读类 + Agent);`enable_subagents=False` 时去掉 `Agent` → `Read,Grep,Glob`。
  - 以 **worktree 为 cwd**:`runner.run(argv, cwd=state.worktree_path, timeout=...)`(不写新增文件,故不污染 diff)。
- 解析:收集 stdout 全部行 → `parse_claude_stream` → `final_text` → `extract_json_object` → `validate_with_retry`(逻辑不变)。
- 捕获:校验成功后,若 `trace` 非空,`trace.capture(raw_lines, subagents)`。

### 6.2 CodexCliBackend
- argv:`codex exec <prompt> --cd <worktree> --sandbox workspace-write --ask-for-approval never --json [--model M]`;
  - `enable_subagents=False` 时追加 `-c features.multi_agent=false`。
- 解析:收集 stdout 全部行 → `parse_codex_stream` → `final_text` → `extract_json_object` → `validate_with_retry`。
- 捕获:同上。

### 6.3 重试与捕获的关系
- `validate_with_retry` 的 `call_fn` 每次运行 CLI 并把"本次原始行 + 解析出的 subagents"暂存在闭包持有器;**只捕获最终(成功或最后一次)尝试**的事件流。

---

## 7. ⚠️ 事件 schema 不确定性与防御策略

文档无法 100% 确认两 CLI 的完整事件键名,故:
1. 解析器**只依赖可靠存在的信号**:Claude 的 `type=="result"`/`parent_tool_use_id`;Codex 的 agent 消息 item / `thread.*`。其余尽力而为。
2. **遇到未知结构绝不抛异常**;`final_text` 取不到时返回空串,后端按"解析失败"→重试一次→仍失败标 BLOCKED→Human Gate(不静默)。
3. **确切键名在 `scripts/smoke_collab.py` 真实运行中确认**:首次冒烟会把原始 `events.jsonl` 落盘,据此微调解析器。spec 把"解析器键名以真实输出为准"作为已知校准点,不视为缺陷。
4. 即便 subagent 摘要解析不完美(例如 `agent_type` 全是 "unknown"),**原始 `events.jsonl` 始终全保真落盘**,可追踪性不丢。

---

## 8. 编排器 / 状态 / CLI

- `collab_orchestrator.run_collab`:为每个角色调用建 `TraceSink(run_path / "subagents", f"{role}.v{attempt}")`,以 `trace=` 传入对应 `run_role`。
- 每次调用后,把该 `<label>.subagents.json` 的摘要聚合进 `state.subagents`(`{role, attempt, count, types}`)。
- `_build_final` 增"嵌套 subagent 概览"小节(各角色各轮 spawn 数量/类型)。
- `state.json` 含 `subagents`。
- CLI:`macr collab "<task>" --repo <p> --test-cmd "..." [--no-subagents] [其余同 Stage A]`;默认开启 subagent;按 `--no-subagents` 构造 `ClaudeCliBackend(enable_subagents=...)` / `CodexCliBackend(enable_subagents=...)`。注入式后端路径不受影响。

---

## 9. 错误处理

- 沿用 Stage A:CLI 缺失→退出 2;CLI 非零退出/解析失败→重试→BLOCKED→门控;任意异常→`try/finally` 落盘 `state.json`→退出非 0。
- 新增:`TraceSink.capture` 落盘失败**不应**让整次 run 崩溃——捕获是"附带产物",写失败只记一条 printer 警告并继续(不影响主结果与门控)。
- CLI 子进程超时仍由 `SubprocessRunner` 转 `AgentError`(Stage A 已实现)。

---

## 10. 测试策略(TDD)

- **解析器**:`parse_claude_stream` / `parse_codex_stream` 用**合成事件流**(手写 JSONL,含 1–2 个 subagent 信号 + 一个最终结果事件)单测:断言 `final_text` 正确、`SubagentRecord` 列表(count/ref/agent_type)正确、未知结构不崩、无最终结果时返回空串。
- **TraceSink**:`capture` 写出 `<label>.events.jsonl` + `<label>.subagents.json`,内容正确。
- **CLI 后端**:`FakeProcessRunner` 返回多行 stream-json/`--json`,断言 (1) 返回 `Message` 正确、(2) 传入 `trace` 时落盘了两份文件、(3) `enable_subagents=False` 时 argv 不含 `Agent` / 含 `features.multi_agent=false`、(4) Claude 调用以 worktree 为 cwd。
- **编排器**:`FakeAgentBackend`(扩展为收到 trace 时写脚本化摘要)跑全流程,断言 `subagents/` 目录生成、`state.subagents` 聚合、`final.md` 含概览;Stage A 的五条路径测试仍通过。
- **回归**:V1 + Stage A 全部测试保持绿(`trace` 可选、旧后端忽略)。
- 真实 `claude` + `codex` 仅在 `scripts/smoke_collab.py` 手动跑,并据其 `events.jsonl` 校准解析器(§7)。
- commit 无 AI 署名;依赖只在 `.venv`。

---

## 11. 完成标准(Definition of Done)

- [ ] `macr collab` 默认调用 Claude/Codex 时允许其原生 subagent(Claude `Agent` 工具;Codex `multi_agent`),`--no-subagents` 可关。
- [ ] 每个角色调用的原始事件流 + 结构化 subagent 摘要落进 `.macr/runs/<run_id>/subagents/`;`state.subagents` 聚合;`final.md` 含概览。
- [ ] 解析器防御式实现:未知结构不崩;无最终结果→重试→BLOCKED→门控。
- [ ] Claude 角色以 worktree 为 cwd 且只读工具白名单(不污染 diff)。
- [ ] 全部单元 + 集成测试通过(合成事件流 + FakeProcessRunner + 真临时 git 仓库,不触真实 CLI)。
- [ ] V1 + Stage A 测试与行为不受影响。
- [ ] `scripts/smoke_collab.py` 可用于真实校准(本阶段交付"可校准"的解析器 + 落盘机制,真实键名校准在冒烟阶段完成)。
