# Multi-Agent Term — Phase 1: Worker → tmux 接入编排器 设计 (2026-06-22)

> 承接 Phase 0(`macr/runtime/`:tmux 运行时 + OSC 7748 观测,已实现、18 测试绿 + 真机冒烟过)。
> 总设计见 `specs/2026-06-22-multi-agent-term-design.md`。Phase 0 计划见 `plans/2026-06-22-mat-phase0-tmux-runtime.md`。
> 本 spec 只做 Phase 1 的第一块:把编排器的 **Worker(executor)执行** 从"一次性子进程"换成"在 tmux pane 里跑、可观测的 Agent",且**不改 orchestrator 主体**。

## 背景

现状:`_implementation_loop`(`collab_orchestrator.py`,被 `run_collab` 与 `run_discuss` 复用)执行 Worker 的方式是:

```python
exec_msg = codex_backend.run_role(EXECUTOR_C, state, run_id=..., task_id=..., trace=...)
```

`codex_backend` 是一个满足 `AgentBackend` Protocol 的对象(`macr/agents/base.py`):

```python
class AgentBackend(Protocol):
    name: str
    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None) -> Message: ...
```

现有实现 `CodexCliBackend.run_role` 跑 `codex exec <prompt> --cd <worktree> --sandbox <s> --json`(一次性子进程),解析 JSON 流,`validate_with_retry` 成 `ExecutorOutput`,返回 `Message`。

问题:这个一次性子进程是**不可观测的黑盒**——人看不到 Worker 在终端里干什么(在跑/等审批/卡住),也无法在一个终端里同时围观多个 Worker。Phase 0 已经把 tmux 运行时 + 观测层做好了,Phase 1 把它接上。

关键洞察:**编排器依赖的是 `AgentBackend` 这个注入接缝,不是具体实现。** 所以 Phase 1 不改编排器,只新增一个满足同接口的 `TmuxExecutorBackend`,在调用处注入替换即可。

## 目标

新增 `TmuxExecutorBackend`(实现 `AgentBackend`),`run_role` 时:
1. 用 Phase 0 的 `TmuxRuntime` 在一个 tmux pane 里跑 **与 `CodexCliBackend` 相同的 `codex exec … --json` 命令**(保留结构化输出契约),cwd = worktree。
2. 用 Phase 0 的 `AgentObserver` 实时观测该 pane 的状态(OSC 7748 / 进程事实 / 屏幕启发式),把状态事件落到 `.macr/runs/<id>/`。
3. pane 进程退出后,抓取该 pane 的完整输出,沿用现有 `parse_codex_stream` + `extract_json_object` + `validate_with_retry` 解析成 `ExecutorOutput`,返回 `Message`——**与 `CodexCliBackend` 返回完全同形**。
4. 在 `run_collab`/`run_discuss` 的调用处,把 Worker 用的 backend 注入为 `TmuxExecutorBackend`(可选,默认仍是 `CodexCliBackend`,由 CLI flag / 参数切换)。

净效果:Worker 现在跑在一个可观测的 tmux pane 里(人可 `tmux attach` 实况围观),状态可见、可回放,而编排器的角色/门控/worktree/落盘逻辑**一行不改**。

## 范围(Phase 1 第一块,已定)

- 新增 `macr/runtime/tmux_executor.py`:`TmuxExecutorBackend(AgentBackend)`。
- 复用 Phase 0 的 `TmuxRuntime`/`TmuxControl`/`AgentObserver`/`agent_state`,以及现有 `trace.parse_codex_stream`、`base.extract_json_object`、`base.validate_with_retry`、`base.message_from_content`、`cli_backend._base_prompt`。
- 结果抓取走 `TmuxRuntime.snapshot`(capture-pane,经 `TmuxControl` 可注入)→ 全程 `FakeTmuxTransport` 可测。
- 在 `run_collab`/`run_discuss` 加一个**可选注入点 / CLI flag**(如 `--worker-runtime tmux`)选择 Worker backend;默认 `cli`(行为不变,旧测试不受影响)。
- 观测事件:Worker 运行期间产生的 `Detection` 写进 run 产物(新 artifact,如 `worker-observations.jsonl`)。

## 非目标(YAGNI)

- 多 Worker 并发 / Task DAG(仍单 Worker 顺序;→ 后续 Phase)。
- 把 Claude 侧(planner/reviewer/discussion)也搬进 pane(它们是规划/审查,一次性即可;Worker 才需要可观测)。
- 交互式 REPL Worker(用 send-keys 喂多轮)(→ 见执行模型被否决备选 C)。
- OSC 7748 hook 安装器(让 codex 自报状态)——本 Phase 观测靠 `pane_dead` + 屏幕启发式即可工作;hook 安装是独立一块(可与本块并行,另立 spec)。
- Agent/Task 持久化(SQLite)、Message Bus、原生 UI、Remote(→ 后续 Phase)。

## 执行模型(方案 A:pane 里跑 `codex exec --json`,保结构化契约)

**方案 A(采用)**:Worker pane 跑的就是现有那条 `codex exec <prompt> --cd <worktree> --sandbox <s> --json` 命令,只是从"被捕获的子进程"变成"tmux pane"。进程跑完(`pane_dead`)后,从 pane 抓全量输出按现有方式解析。

理由:一次拿下"可观测 + 多路复用 + 保留结构化输出契约"三件事;`ExecutorOutput` 契约不变 → 编排器、评估门、审码、现有测试全部不动;只是执行载体从 subprocess 换成 pane。

**被否决备选 B**:继续用 `CodexCliBackend` 跑子进程,另开一个 tmux pane 只做"镜像展示"。否决:两套执行路径、状态会分叉(违反"事实源优先");pane 只是装样子,没真正成为运行时。

**被否决备选 C**:在 pane 里跑交互式 `codex`/`claude` REPL,用 `send-keys` 多轮喂 prompt、靠屏幕抓结果。否决:交互式 Agent 没有稳定的结构化输出,解析脆弱、不可靠;Phase 1 不值得。`send-keys` 输入通道留给将来"需要中途追加指令/回答审批"时再用。

## 架构

```
run_collab / run_discuss(不改)
        │  _implementation_loop 调 worker_backend.run_role(EXECUTOR_C, state, …)
        ▼
TmuxExecutorBackend.run_role  (实现 AgentBackend,drop-in 替换 codex_backend)
        │ 1. argv = codex exec <prompt> --cd <worktree> --sandbox --json   (同 CodexCliBackend)
        │ 2. runtime.spawn_agent(agent_id, argv, cwd=worktree)             → %pane
        │ 3. 轮询 control.poll() → observer.on_output / refresh_from_panes  → 落 observations
        │    直到 pane_dead(或 timeout)
        │ 4. out = runtime.snapshot(agent_id, recent=N)                    → 全量输出
        │ 5. parse_codex_stream(out.splitlines()) → extract_json_object → validate_with_retry → ExecutorOutput
        ▼ 返回 Message(与 CodexCliBackend 同形)
   Phase 0: TmuxRuntime / TmuxControl / AgentObserver / agent_state(不改)
        ▼
   tmux server(Worker 在一个 pane 里;人可 attach 围观)
```

## 组件

### `macr/runtime/tmux_executor.py` · `TmuxExecutorBackend`

```python
class TmuxExecutorBackend:
    """AgentBackend(Protocol)。在 tmux pane 里跑 codex exec --json 并实时观测,
    退出后解析为 ExecutorOutput。与 CodexCliBackend 返回同形 Message。"""
    name = "tmux_executor"

    def __init__(self, runtime: TmuxRuntime, *, observer: AgentObserver | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 model: str | None = None, enable_subagents: bool = True,
                 timeout: int = 1800, poll_interval: float = 0.2,
                 obs_sink: Callable[[dict], None] | None = None,
                 capture_recent: int = 5000): ...

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None) -> Message:
        # 1) 构 argv(复用 cli_backend 的 _base_prompt + 与 CodexCliBackend 一致的 flag)
        # 2) agent_id = f"{role.name}-{run_id}-{attempt?}";runtime.spawn_agent(argv, cwd=worktree)
        # 3) loop: control.poll() → observer.on_output(%pane,data)/refresh_from_panes()
        #          每次 Detection 变化 → obs_sink({agent_id,state,confidence,ts}) 落 observations
        #          pane_dead → break;超 timeout → kill + AgentError
        # 4) out = runtime.snapshot(agent_id, recent=capture_recent)
        # 5) final, subs = parse_codex_stream(out.splitlines())
        #    content = validate_with_retry(role, lambda extra: extract_json_object(final))
        # 6) return message_from_content(role, content, run_id=…, task_id=…, timestamp=…)
```

要点:
- **argv 与 `CodexCliBackend` 完全一致**(同 prompt、`--cd`、`--sandbox`、`--json`、`--model`、`features.multi_agent`),保证行为可比、可回退。
- **可注入**:`runtime`(内含 `TmuxControl`,可注 `FakeTmuxTransport`)、`obs_sink`(测试断言观测事件)。无真 tmux / 真 codex 即可测。
- **`agent_id` 与 `%pane` 分离**(Phase 0 已立):backend 自己生成 `agent_id`,映射由 `TmuxRuntime` 维护。
- **错误**:进程非零退出(`pane_dead_status != 0`)→ 从输出提 `stream_error` 真因 → `AgentError`(沿用现有语义,编排器据此走 BLOCKED 门);超时 → `kill` + `AgentError`。
- **退出判定边界**:进程退出(`pane_dead`)是权威完成信号(Phase 0 已定 conf 100);**但"完成"仅到 `observed`,`verified` 仍由 `_implementation_loop` 后续 diff + 测试 + 审码 + 确定性门给出**——不僭越验收(守 Phase 0 铁律)。

### 编排器注入点(最小改动)

- `run_collab(..., worker_backend: AgentBackend | None = None)`:`_implementation_loop` 里 `codex_backend` 改用 `worker_backend or codex_backend`(默认不变)。
- `run_discuss` 同理(impl 阶段用的 `impl_codex_backend`)。
- CLI:`macr collab/discuss` 加 `--worker-runtime {cli,tmux}`(默认 `cli`)。选 `tmux` 时,入口构造 `TmuxExecutorBackend(TmuxRuntime(TmuxControl(SubprocessTmuxTransport(...))), sandbox="workspace-write", ...)` 注入。

## 数据/事件

- 新 artifact `.macr/runs/<id>/worker-observations.jsonl`:每行一条 `{ts, agent_id, attempt, app, state, confidence}`,来自 `obs_sink`。可回放 Worker 状态轨迹。
- `ExecutorOutput`(artifact/notes/evidence)契约不变 → `state.agent_outputs["executor"]`、`log.write_executor`、diff/test/review/eval 全部照旧。

## 错误处理与生命周期

- spawn 失败(tmux `%error`)→ `TmuxError` → 包成 `AgentError`。
- pane 进程非零退出 → `AgentError`(带 `stream_error` 真因)→ 编排器 BLOCKED 门。
- 超时(`timeout` 内未 `pane_dead`)→ `runtime.kill(agent_id)` + `AgentError`。
- 解析失败(无合法 JSON)→ 复用 `validate_with_retry` 的一次重试;再失败 → `AgentError`(同 `CodexCliBackend` 语义)。
- pane 清理:run 结束/失败后 `runtime.kill`(或保留供人工查看,与 worktree 同策略,由参数定;默认成功保留、失败保留以便排查)。
- "事实源优先":完成判定等 `pane_dead`(`list_agents`/`%`-事件),不靠"我发了命令就算跑完"。

## 测试策略(TDD,全程 fake)

- **单元**:`TmuxExecutorBackend.run_role` 在 `FakeTmuxTransport` 上:
  - 喂 spawn 响应(`%pane`)、若干 `%output`(含 OSC 7748 标记 + 一段合法 codex `--json` 输出)、`list-panes` 显示 `pane_dead=1 status=0`、`capture-pane` 返回那段 JSON 输出 → 断言:返回的 `Message.content` 是合法 `ExecutorOutput`;`obs_sink` 收到了 running→done 的观测序列。
  - 非零退出(`status!=0`)→ 断言抛 `AgentError` 带真因。
  - 超时(始终非 dead)→ 断言 `kill` 被调用 + `AgentError`。
- **集成(强)**:把 `TmuxExecutorBackend`(注 `FakeTmuxTransport`)作为 `worker_backend` 注入真的 `run_collab`,claude 侧用 `FakeAgentBackend`(planner/reviewer 脚本化),worktree 用临时 git 仓:断言整条 executor→diff→test→review→eval 闭环跑通、`state.json` 落盘——证明 drop-in 替换不破坏编排器。**无真 tmux、无真 codex。**
- **回归**:默认 `--worker-runtime cli` 路径不变,现有 collab/discuss 测试全绿。
- **真机冒烟(手动)**:扩 `scripts/mat_tmux_smoke.py` 或新增脚本,用真 tmux + 一个最小 `codex exec --json`(或桩命令打印一段固定 JSON)验证端到端。CI 不跑。

## 验收

- `TmuxExecutorBackend` 实现 `AgentBackend`,`run_role` 在假传输下返回合法 `ExecutorOutput` 形 `Message`,观测事件落 `obs_sink`;单元测试绿。
- 作为 `worker_backend` 注入 `run_collab`,FakeAgentBackend + 临时仓下闭环跑通、落盘;集成测试绿。
- `--worker-runtime cli`(默认)行为与现状一致,全套旧测试绿。
- 真机冒烟脚本就绪并文档化。
- CHANGELOG 追加 Phase 1 条目(含 commit 短 hash)。

## 后续(不在本块)

- OSC 7748 hook 安装器(让 codex/claude 自报状态,把观测从启发式升到权威 100)——独立块,可与本块并行。
- 多 Worker 并发 + Task DAG(让"一个终端多个 Agent"真正同时跑)。
- Agent/Task 持久化(SQLite)+ 可回放事件投影。
