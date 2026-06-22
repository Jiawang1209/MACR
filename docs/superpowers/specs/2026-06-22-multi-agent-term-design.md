# Multi-Agent Term 架构设计 (2026-06-22)

> 定位:MACR 的 V3 方向。把 MACR 从"驱动两个写死的 CLI 跑线性闭环"升级为"**编排并观测一队跑在真实终端里的 Agent**"。
> 配套阅读:`docs/WispTerm_源码解析与_Multi-Agent_Term_借鉴报告.md`、`docs/wispterm-craybot-源码接口笔记.md`、`docs/tmux集成方案-多Agent终端运行时.md`。
> 本 spec 定义整体架构与 **Phase 0** 的精确范围;Phase 0 实现计划见 `docs/superpowers/plans/2026-06-22-mat-phase0-tmux-runtime.md`。

## 背景

MACR 已有的是一套**有纪律的协同控制面**:角色分工(Leader/Worker/Reviewer)、独立出方案、辩论到共识、Stage D 确定性计划审查门、worktree 隔离、人工门、全程落盘可回放(`.macr/runs/`)。三命令(`run`/`collab`/`discuss`)+ V2 Web 控制台都已实现、245 测试绿、真机端到端跑通过一次。

但 MACR 当前是**驱动**模式:`cli_backend` 起一个一次性子进程(`claude -p …` / `codex exec …`),发命令、读 `--json` 流、拿最终结果。它**看不到**一个交互式终端 Agent 的实时状态(在跑/等审批/要输入/挂了),也**一个终端里只能跑一条线性流水线**,无法让人同时围观一队 Agent。

对 WispTerm / tmux / CrayBot 三个代码库的源码分析得出一个镜像结论:**WispTerm 把"终端运行时 + Agent 状态观测"做透了,但多 Agent 控制面几乎是空的;MACR 正好相反。** tmux 本身就是一个成熟的多 Agent 终端运行时(一个 pane = 一个进程 = 一个 Agent),通过 control mode 可被纯文本驱动。CrayBot 给了一份干净、可照搬的 Runtime Adapter 参考(`Executor` 接口、注入安全 argv、单活动调度)。

本 spec 把三者拼起来:**MACR 控制面(大脑)+ tmux 运行时(身体)+ OSC 7748 / 启发式观测(感官)。**

## 目标

最终形态(Multi-Agent Term):一个终端里开多个 pane,每个 pane 跑一个 Agent(`claude`/`codex`/通用终端 Agent);MACR 通过 tmux control mode 开 pane、派发任务、观测每个 Agent 的实时状态、收集制品、按现有门控验收;人 `tmux attach` 上去就能实况围观整队 Agent,而控制面、门控、审计全程在线。

**本 spec 的 Phase 0 目标(可独立交付、可纯单测)**:实现 MACR 与 tmux 之间的 **运行时 + 观测层**,且把 tmux 传输做成**可注入**(测试用假 tmux,不依赖真 tmux/真 CLI):
1. 一个 `TmuxRuntime`:经 control mode 开会话、`spawn` N 个 Agent pane、`send_input`、`snapshot`、`list_agents`、`kill`,维护 `agent_id ↔ %pane` 映射。
2. 一个 `AgentObserver`:把三路信号(OSC 7748 权威标记 / tmux 进程事实 / 屏幕启发式)融合成统一的 `Detection{app, state, confidence}`。
3. 一个端到端验证:用假 tmux 传输开一个会话、spawn 两个 Agent、喂带 OSC 标记的 `%output`,断言观测到的状态正确——即"一个终端跑多个可观测 Agent"在逻辑层跑通。

## 范围(Phase 0 已定)

- 只做 **运行时 + 观测层**(`macr/runtime/`),不改现有 orchestrator。
- tmux 传输抽象为 `TmuxTransport` Protocol(对齐现有 `ProcessRunner` 模式);提供 `SubprocessTmuxTransport`(真)与 `FakeTmuxTransport`(测试)。
- control mode 协议:解析 `%begin/%end/%error` guard 帧 + `%output`/`%window-add`/`%window-close`/`%layout-change`/`%pause`/`%continue` 等 `%`-事件;发命令行。
- `AgentState` 状态机 + OSC 7748 `parse_marker` + 启发式 `detect`(从 WispTerm `agent_detector.zig` 移植 claude_code / codex 子集)+ `aggregate`。
- Agent 生命周期:spawn / send_input / snapshot(capture-pane)/ kill / respawn;`agent_id` 与 `%pane` 分离。

## 非目标(YAGNI,留给后续 Phase)

- 接入现有 `run_discuss`/`run_collab` 把 Worker 换成 tmux Agent(→ Phase 1)。
- Task DAG / Message Bus / Agent Registry 持久化(SQLite)(→ Phase 1)。
- 安装 OSC 7748 hook 到 `~/.claude/settings.json` 的生产逻辑(→ Phase 1;Phase 0 只解析标记,不负责让 Agent 发标记;测试里由 `FakeTmuxTransport` 直接喂带标记的 `%output`)。
- 原生终端 UI / 团队视图 / DAG 视图(→ Phase 5)。
- 远程访问、设备认证、E2E 加密(→ Phase 6)。
- `%output` 大流量背压的精细调优(Phase 0 正确处理 `%pause`/`%continue` 即可,不做吞吐优化)。

## 执行模型(方案 A:tmux control mode + 可注入传输)

**方案 A(采用)**:以 control mode(`tmux -CC`)连一个 tmux server,纯文本命令行驱动,异步收 `%`-事件。底层传输是一个 `TmuxTransport`(写命令行 / 读输出行 / 关闭),用 Protocol 抽象,测试注入 `FakeTmuxTransport`。理由:tmux 已是成熟的持久、可观测、可多路复用终端运行时;control mode 是纯文本行协议,解析/发送都是可单测的纯逻辑;传输可注入 → 全套不依赖真 tmux 即可测(与 MACR 现有 `FakeProcessRunner`/`FakeAgentBackend` 同一哲学)。

**被否决备选 B**:照搬 WispTerm 的 Zig `Surface`/PTY/Renderer 自建终端运行时。否决:那是十几万行的桌面终端内核,层级太低、与 MACR(Python 控制面)不匹配;Phase 0 不需要渲染/字体/GPU。其设计思想(统一输入通道、Surface=一等执行单元)留作将来做原生 UI 时的参考。

**被否决备选 C**:像 CrayBot `LocalExecutor` 那样直接 `spawn` 一次性子进程。否决:子进程模式只能"发命令收 stdout",看不到交互式 Agent 的实时状态(等审批/要输入),也不能在一个终端里让人围观多个 Agent。但其 `Executor` 接口形状(`run→{result, cancel}`、注入安全 argv)被 `TmuxRuntime` 的方法签名借鉴。

## 架构

```
                MACR 控制面(已有,Phase 0 不改)
        discuss 角色 / Stage D 确定性门 / 人工门 / worktree / .macr/runs 落盘
                              │  (Phase 1 接缝:Worker → tmux Agent)
   ┌──────────────────────────┴───────────────────────────┐
   │                  macr/runtime/  (Phase 0 新建)          │
   │                                                        │
   │   TmuxRuntime ── spawn/send_input/snapshot/list/kill   │
   │      │  维护 agent_id ↔ %pane 映射                      │
   │      ▼                                                 │
   │   TmuxControl ── 发命令(%begin/%end 配对)             │
   │      │           收 %-事件(%output/%layout-change…)   │
   │      ▼                                                 │
   │   TmuxTransport (Protocol) ──┬── SubprocessTmuxTransport (真: tmux -CC)
   │                              └── FakeTmuxTransport (测试)
   │                                                        │
   │   AgentObserver ── 融合三路信号 → Detection{app,state,confidence}
   │      ▲  OSC7748(%output 里的标记) · tmux 进程事实(list-panes) · 屏幕启发式(capture-pane)
   │   agent_state ── AgentState 枚举 · parse_marker · detect · aggregate
   └────────────────────────────────────────────────────────┘
                              │
                       tmux server(一个终端,多个 pane = 多个 Agent)
                       %12 claude   %13 codex   %14 …
```

## ID 模型(直接采用 tmux 的命名,但分离身份)

| ID | 前缀/形态 | 含义 | 谁拥有 |
|---|---|---|---|
| `agent_id` | MACR 生成(如 `worker-1`) | Agent 长期身份,respawn 不变 | MACR |
| `%pane` | tmux `%12` | 终端显示/控制单元 | tmux |
| `session_id` | tmux `$3` / MACR run_id | 一次运行 / 一个团队 | 双方各持一份,映射 |
| `task_id` | MACR | 工作任务 | MACR |
| `worktree_id` | MACR worktree 路径 | 代码隔离空间 | MACR |

**铁律**:`agent_id ≠ %pane`。`TmuxRuntime` 维护 `agent_id → %pane` 映射;Agent `respawn` 后 `%pane` 可能不变但 `pane_pid` 变,身份以 `agent_id` 为准。

## 组件(`macr/runtime/`)

### `agent_state.py` —— 状态词汇与判定(纯函数,从 `agent_detector.zig` 移植)

```python
class AgentState(str, Enum):
    none = "none"; running = "running"; waiting_approval = "waiting_approval"
    needs_input = "needs_input"; halted = "halted"; failed = "failed"; done = "done"

class AgentApp(str, Enum):
    none = "none"; codex = "codex"; claude_code = "claude_code"

@dataclass
class Detection:
    app: AgentApp = AgentApp.none
    state: AgentState = AgentState.none
    confidence: int = 0          # 0..100;OSC 标记=100,启发式 72..96
    def visible(self) -> bool: ...

OSC_NUM = 7748; TAG = "wispterm-agent"   # 与 WispTerm 同词汇,便于复用其 hook
def parse_marker(payload: str) -> Detection | None: ...   # "wispterm-agent;state=running;app=claude_code" → confidence 100
def detect(title: str, recent_output: str) -> Detection: ... # 屏幕启发式,claude/codex 子集
def aggregate(states: list[AgentState]) -> AgentState: ...   # 按注意力优先级汇总:waiting_approval>needs_input>halted/failed>running>done
```

### `tmux_control.py` —— control mode 帧/事件解析(纯逻辑 + 可注入传输)

```python
@dataclass
class CommandResult:
    number: int; ok: bool; lines: list[str]   # %begin..%end/%error 之间的输出行

@dataclass
class Notification:
    kind: str            # "output" | "window-add" | "window-close" | "layout-change" | "pause" | "continue" | ...
    pane: str | None     # %12  (output/pause/continue)
    window: str | None   # @7   (window-*/layout-change)
    data: str            # 余下载荷(output 的字节、layout 串等)

@runtime_checkable
class TmuxTransport(Protocol):
    def send_line(self, line: str) -> None: ...
    def read_line(self, timeout: float | None = None) -> str | None: ...  # 一行控制输出,None=EOF
    def close(self) -> None: ...

class TmuxControl:
    """把 control mode 的行流解析成 CommandResult(命令响应)+ Notification(异步事件)。"""
    def __init__(self, transport: TmuxTransport): ...
    def send_command(self, cmd: str) -> CommandResult: ...   # 写命令行,读到匹配的 %begin..%end/%error
    def poll(self, timeout: float | None = None) -> list[Notification]: ...  # 收一批 %-事件
```

guard 帧格式(摘自 `cmd-queue.c:825 cmdq_guard`):`%begin <time> <number> <flags>` … 输出 … `%end <time> <number> <flags>`(成功)或 `%error …`(失败)。`<number>` 用于响应配对。事件格式摘自 `control-notify.c`:`%output %<pane> <data>`、`%window-add @<w>`、`%layout-change <w> <layout> <visible> <flags>`、`%pause %<pane>`、`%continue %<pane>` 等。

### `tmux_runtime.py` —— Agent 运行时(高层,借 CrayBot Executor 形状)

```python
@dataclass
class AgentInfo:
    agent_id: str; pane: str; pid: int | None
    current_command: str | None; dead: bool; dead_status: int | None

class TmuxRuntime:
    def __init__(self, control: TmuxControl): ...
    def open_session(self, name: str) -> str: ...                       # new-session -d -P -F '#{session_id}'
    def spawn_agent(self, agent_id: str, argv: list[str], cwd: str) -> str:  # split-window/new-window -P -F '#{pane_id}';返回 %pane
        ...
    def send_input(self, agent_id: str, text: str) -> None: ...         # send-keys -t %pane -l <text> ; send-keys Enter
    def snapshot(self, agent_id: str, *, recent: int = 200) -> str: ... # capture-pane -p -t %pane -S -recent -e
    def list_agents(self) -> list[AgentInfo]: ...                       # list-panes -a -F '... pane facts ...'
    def kill(self, agent_id: str) -> None: ...                          # kill-pane -t %pane
```

`argv` 永远作为独立参数(注入安全,对齐 CrayBot `resolveArgv` 与 MACR argv 契约测试);`send_input` 用 `send-keys -l` 字面发送,避免被当快捷键解释。

### `observer.py` —— 三路信号融合

```python
class AgentObserver:
    """持有每个 agent_id 的最新 Detection。喂入三路信号,按可信度覆盖。"""
    def __init__(self, runtime: TmuxRuntime): ...
    def on_output(self, pane: str, data: str) -> None: ...   # 扫 data 里的 OSC 7748 → parse_marker(conf 100)
    def refresh_from_panes(self) -> None: ...                # list_agents 的 pane_dead/current_command → 进程级事实
    def detect_from_snapshot(self, agent_id: str) -> None: ...# capture-pane → detect()(conf 72..96,仅当无更高可信信号)
    def state_of(self, agent_id: str) -> Detection: ...
```

融合规则:高 `confidence` 覆盖低 `confidence`;同源以更新者为准。`dead=True` → `failed`(非零)或 `done`(零)。

## 三层状态观测(对应报告第 10 节分层事实状态)

| 层 | 来源 | confidence | 映射 |
|---|---|---:|---|
| Agent 语义级 | OSC 7748(`%output` 里的标记) | 100 | `reported`(Agent 自报) |
| 进程级 | tmux `pane_dead`/`pane_current_command` | 高 | `observed`(进程事实) |
| 屏幕启发式 | `capture-pane` → `detect()` | 72–96 | `observed`(兜底) |

**严格区分**:以上三层最多到 `observed`/`reported`;**`verified` 只能由 MACR 的 Stage D 确定性门 + 测试转绿给出**,`approved` 由人工门给出,`completed` 由控制面正式关闭。Phase 0 只产出 `observed`/`reported`,不僭越验收。

## 与现有 MACR 控制面的接缝(Phase 1 预留,Phase 0 不实现)

`TmuxRuntime` 的方法形状刻意对齐"派发-观测-取证"三件事,Phase 1 时:
- `run_discuss`/`run_collab` 的 Worker 执行从"`codex_backend` 起一次性子进程"改为"`TmuxRuntime.spawn_agent` 在 pane 里跑 Agent + `send_input` 派发 + `snapshot`/observer 观测"。
- 现有 `worktree.py` 给每个写入型 Worker 的 `cwd`;现有 Stage D 门、人工门、`.macr/runs/` 落盘不变。
- observer 的 `Detection` 事件写进现有 run 日志,成为可回放事件流的一部分。

## 错误处理与生命周期

- `send_command` 收到 `%error` → 抛 `TmuxError(number, lines)`,带 tmux 原始报错。
- 传输 EOF(tmux server 退出)→ `read_line` 返回 None → `TmuxControl` 置 closed,后续 `send_command` 抛 `TmuxClosed`。
- `%pause %<pane>` → observer/runtime 标记该 pane 背压中;收到 `%continue` 恢复;Phase 0 不丢弃事件、不做吞吐优化。
- spawn 失败(命令 `%error`)→ 不记入 `agent_id→%pane` 映射,抛错。
- "事实源优先":`spawn_agent`/`open_session` 以命令响应里 tmux 回的 `%pane`/`%session-id` 为准,不乐观假设;布局变化以 `%layout-change` 为准。

## 测试策略(TDD)

- **纯函数层(最易测,先做)**:`agent_state` 的 `parse_marker`/`detect`/`aggregate` 全用字符串输入断言,直接移植 `agent_detector.zig` 的测试用例。
- **协议层**:`TmuxControl` 喂入脚本化的控制输出行(`FakeTmuxTransport` 预置 `%begin/%end`、`%output`、`%error` 等行),断言 `send_command` 正确配对、`poll` 正确解析事件。
- **运行时层**:`TmuxRuntime` 在 `FakeTmuxTransport` 上断言它发出的命令行(`new-session`/`split-window -P -F`/`send-keys -l`/`capture-pane -p`/`list-panes -F`)、并从假响应解析出 `%pane`/`AgentInfo`。
- **端到端(最强)**:`FakeTmuxTransport` 模拟一个会话 → `TmuxRuntime.open_session` + `spawn_agent` ×2 → 喂两条带不同 OSC 7748 标记的 `%output` → `AgentObserver` 断言两个 agent 的 `Detection` 状态/可信度正确;再喂 `pane_dead` 断言 `failed`/`done`。**全程无真 tmux、无真 CLI。**
- **真机冒烟(文档化,手动)**:在装了 tmux 的机器上 `SubprocessTmuxTransport` 跑 `open_session` + spawn 一个 `bash`、`send_input "echo hi"`、`snapshot` 断言看到 `hi`。CI 不跑(无 tmux),写进 plan 的最后一个 Task 作为手动验证脚本。

## 验收

- `macr/runtime/agent_state.py`:`parse_marker`/`detect`/`aggregate` 测试绿,覆盖 claude_code + codex + 权威标记 + 拒绝错误标记。
- `macr/runtime/tmux_control.py`:guard 帧配对、`%error`、各 `%`-事件解析测试绿;传输可注入。
- `macr/runtime/tmux_runtime.py`:五个方法在假传输上发出正确命令行、解析出 `%pane`/`AgentInfo`,测试绿。
- `macr/runtime/observer.py`:三路信号融合 + 可信度覆盖规则测试绿。
- 端到端:假传输下"一会话两 Agent + OSC 观测 + pane_dead"全测绿。
- 真机冒烟脚本就绪并文档化(手动验证一次即可)。
- 全套不依赖真 tmux/真 CLI;并入仓后 `pytest` 全绿。

## 后续阶段(摘要,不在本 Phase)

- **Phase 1**:接入控制面(Worker→tmux Agent)+ Agent/Task 持久化(SQLite)+ 安装 OSC 7748 hook 的生产逻辑。
- **Phase 2**:Runtime Adapter 多态(Codex/Claude/通用终端 Agent 统一结构化事件)。
- **Phase 3**:每个写入型 Worker 独立 git worktree + 任务级能力授权。
- **Phase 4**:Message Bus + Artifact Registry + Reviewer 任务 + 自动验证才进 Completed。
- **Phase 5**:原生终端 UI(团队/DAG/Agent 绑定/审批 Inbox/事件回放)。
- **Phase 6**:Remote 与生产强化(设备认证、E2E 加密、输入所有权、多租户、审计备份)。
