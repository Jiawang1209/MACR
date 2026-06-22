# WispTerm + CrayBot 源码接口笔记(为 MACR → Multi-Agent Term 借鉴)

> 阅读对象:`demo/craybot/`(TypeScript,可运行的姊妹项目)、`demo/wispterm-main 2/`(Zig,约 14.6 万行)
> 整理日期:2026-06-22
> 目的:从源码里把**真实接口签名**抽出来,逐个标注它映射到 MACR 的哪一块、是"已有可对齐"还是"待新建"。
> 配套阅读:`WispTerm_源码解析与_Multi-Agent_Term_借鉴报告.md`(上层结论);本文是落到接口层的补充。

---

## 0. 一句话结论

CrayBot 给了 MACR 一份**已经写好、可直接照搬的 Runtime Adapter 参考实现**(引擎模板 + 执行器 + 安全 argv + 单活动任务调度);WispTerm 给了 MACR **两块自己还没有的能力的成熟设计**:终端 Agent 的**结构化/启发式状态观测**(OSC 7748 + detector)和**统一输入通道 + 本地控制接口**。MACR 已有的(角色、确定性门、worktree 隔离、落盘)恰好是这两个项目缺的。三者拼起来正好覆盖报告里 Multi-Agent Term 的全图。

---

## 1. CrayBot —— 它是什么 + 可直接借鉴的接口

CrayBot 是一个**无界面服务端 bot**:用微信(或本地 stdin CLI)遥控一台机器上的 Claude/Codex 做数据分析。两个正交维度 —— **target**(代码在哪跑:`local` 子进程 / `ssh` 远程)、**engine**(用哪个 AI:命令模板)—— 都藏在统一接口后。它和 MACR 是姊妹关系:同样"Claude/Codex 可插拔 + local/ssh 目标抽象",但 CrayBot 把这层做成了干净的小接口。

状态:Plan 1–4 已完成(本地核心 / iLink 微信网关 / 媒体编解码回图 / 入站检索),Plan 5(SSH 执行器 + 守护 + 审计 + cwd 沙箱)待做。

### 1.1 `Executor` —— 最值得照搬的抽象(`src/executor/types.ts`)

```ts
interface RunRequest {
  target: TargetConfig;
  argv: string[];                       // 已解析好的 argv,argv[0] 是程序名
  onChunk?: (chunk: string) => void;    // stdout 流式回调
}
interface RunResult { code: number; stdout: string; stderr: string; }
interface RunHandle { result: Promise<RunResult>; cancel: () => void; }
interface Executor  { run(req: RunRequest): RunHandle; }
```

`LocalExecutor`(`executor/local.ts`)的关键细节,MACR 的 CLI 后端应对齐:
- `spawn(cmd, args, { cwd, env, stdio: ["ignore","pipe","pipe"] })` —— **stdin 接 /dev/null**,让 `codex exec` 这类读 stdin 的引擎立刻拿到 EOF 而不是挂死(MACR 真机 dogfood 踩过的"非 TTY stdin 继承"坑,这里是同一类问题的预防写法)。
- `cancel = () => child.kill("SIGTERM")`。

> **映射到 MACR**:这正是报告 Phase 2"Runtime Adapter"要的统一接口。MACR 现有 `macr/agents/base.py` + `cli_backend.py` 已是后端抽象,但缺 `RunHandle` 这种 **可取消 + 可流式** 的句柄。建议把 MACR 的后端接口收敛成 `run(req) -> handle{result, cancel, on_chunk}`,`Local` 与未来 `Ssh`/`Tmux` adapter 同接口。

### 1.2 `resolveArgv` —— 注入安全(`src/engines.ts`)

```ts
// prompt 永远是单个 argv 元素,绝不经过 shell,因此不存在命令注入
resolveArgv(cmd: string, prompt: string): string[]
// "claude -p {prompt}" + "画个图" → ["claude","-p","画个图"]
// 模板里没有 {prompt} 占位符时,prompt 追加到末尾
```

> **映射到 MACR**:与 MACR 已做的"pin claude/codex argv 契约测试"同一思路、可对齐。CrayBot 的 `{prompt}` 模板化是把"引擎=命令模板"配置化的轻量做法,MACR 若要支持用户自定义引擎可借此。

### 1.3 `route` —— 纯函数命令路由(`src/router.ts`)

```ts
type Decision =
  | { kind: "reply"; text: string }
  | { kind: "use_target"; name: string }
  | { kind: "use_engine"; name: string }
  | { kind: "run"; engine: string; prompt: string }
  | { kind: "get"; path: string }
  | { kind: "log" }
  | { kind: "stop" };

route(text, config, session): Decision   // 无副作用,易测
```

> **映射到 MACR**:`route` 把"解析输入"和"执行副作用"彻底分离 —— 解析是纯函数返回一个 tagged union,执行在 `App` 里。MACR 的 `cli.py` 命令分发、以及未来控制面的指令入口都可采用这个模式(纯解析 + 可测)。

### 1.4 `App` —— 单活动任务调度器(`src/app.ts`)

要点(都是 Multi-Agent 调度器的最小雏形):
- **单活动任务**:`private active`;跑任务时再来新任务直接拒("先 /stop")。报告里的"Scheduler 需要租约/超时/预算" —— 这是它的最小版。
- **可取消**:`active.cancel()` → `handle.cancel()`。
- **进度心跳**:`progressCheckpointsMs = [15s,45s,120s]`,并在微信 30 分钟回复窗口关闭前(`PROGRESS_DEADLINE_MS = 28min`)发提醒。长任务异步回执的实用范式。
- **制品回收**:`collectArtifacts(target) -> Promise<string[]>`,跑完把产物路径交给 `attachmentSink`。
- **结果分流**:`code===0` 回 stdout,否则回 stderr 尾部。

> **映射到 MACR**:MACR 的 orchestrator 是线性闭环、同步推进;CrayBot 的 `App` 展示了"异步句柄 + 心跳 + 制品回收"的形态。报告 Phase 4 的 `ArtifactRegistry` 可从 `collectArtifacts` 这个最小接口起步。

---

## 2. WispTerm —— 四块成熟设计的真实接口

### 2.1 终端 Agent 状态观测:`agent_detector.zig`(报告点名的"兼容层")

状态词汇表(MACR 应直接采用,与报告第 10 节的分层事实状态吻合):

```zig
pub const State = enum { none, running, waiting_approval, needs_input, halted, failed, done };
pub const App   = enum { none, codex, claude_code };
pub const Detection = struct { app: App, state: State, confidence: u8 };  // confidence 0..100
```

两条来源、**结构化优先 / 启发式兜底**:

| 来源 | 接口 | confidence | 说明 |
|---|---|---:|---|
| 结构化(权威) | `parseMarker(payload) ?Detection` | **100** | 解析 OSC 7748 标记 `wispterm-agent;state=…;app=…` |
| 启发式(兜底) | `detect(title, recent_output) Detection` | 72–96 | 在终端屏幕文本里找 "esc to interrupt" / "execution halted" / "command failed" 等关键词,按"谁更靠后"判定 |

辅助:
- `aggregate(states) State` —— 把多个 pane 状态按**注意力优先级**(`waiting_approval` > `needs_input` > `halted/failed` > `running` > `done`)汇成一个 tab 级指示灯。
- `appFromCommand(cmd) App` —— 把 tmux `#{pane_current_command}` 的进程名(`claude`/`codex`)映射到 App。
- `stateFromLabel` / `appFromLabel` —— label 字符串 ↔ 枚举互转,wire 格式和内部枚举共用一套词汇(避免双份词汇表漂移)。

> **映射到 MACR**:这是 MACR **当前完全没有**的能力。MACR 现在是**驱动** CLI(发命令、读 `--json` 流),但不**观测**一个在终端里跑的 Agent 处于什么状态。要做 Multi-Agent Term,这套 `State` 枚举可直接当 MACR 的 Agent 运行态;`confidence` 字段让"权威信号 vs 屏幕猜测"可区分。**报告的告诫要记牢**:屏幕上出现 `done` 只是 `observed`,不等于 `verified` —— MACR 的 Stage D 确定性门 + 测试转绿才是 `verified` 层,二者要分开存。

### 2.2 让 Agent 主动上报结构化状态:`claude_integration.zig`

这是 2.1 里"confidence=100"信号的**生产端**,而且**可直接照搬**:

```zig
pub const OSC_NUM = 7748;  pub const TAG = "wispterm-agent";
// 生成一条 hook 命令:把 OSC 7748 标记打到控制 tty
hookCommand(buf, state) // → printf '\033]7748;wispterm-agent;state=running;app=claude_code\007' > /dev/tty
```

机制:往 `~/.claude/settings.json` 幂等地注入 4 个 hook,让 Claude Code 在生命周期事件时自报状态:

| hook 事件 | 上报状态 |
|---|---|
| `UserPromptSubmit` / `PreToolUse` | `running` |
| `Notification` | `waiting_approval` |
| `Stop` | `done` |

`install/isInstalled/remove` 都靠 `TAG` 字符串幂等识别,不碰用户已有 hook。

> **映射到 MACR**:报告 17.3"推动 Agent Adapter 输出结构化事件"的现成落地。MACR 可装同款 hook,让被驱动的 Claude/Codex 把 `running/waiting_approval/done` 直接喂进 MACR 的 EventLog(`.macr/runs/`),不必靠解析 `--json` 流或屏幕文本。**几乎零成本的强信号来源。**

### 2.3 统一输入通道:`Surface.zig`(报告 17.2 最推崇的设计)

```zig
// 所有输入(键盘 / AI 工具 / 远程 / 控制接口)最终都走这一条 PTY 写入路径:
pub fn queuePtyWrite(self: *Surface, data: []const u8) void {
    const msg = termio.Message.writeReq(self.allocator, data) catch return;
    self.queueIo(msg);          // → mailbox.send + notify → IO writer 线程 → PTY
}
// 远程客户端也复用同一条:
fn remoteWrite(ctx, data) { surface.queuePtyWrite(data); }
```

Surface 还持有稳定 `remote_id`(跨重连不变的身份)、VT 状态、标题来源优先级(override > OSC7 > window_title)。VT 流里内联解析 OSC 7748(`agent_osc` 状态机)。

> **映射到 MACR**:MACR 目前没有终端运行时,这块是"将来要做终端 Adapter 时照抄的设计",不是现在就能用的接口。核心思想:**人工、AI、远程、控制 API 四个来源汇到同一个写入队列**,避免四套执行逻辑打架。报告也警告:Surface 身份 ≠ Agent 身份(Agent 可重启/迁移/跨多个 Surface),MACR 的 ID 模型要把 `agent_id`/`session_id`/`surface_id` 分开。

### 2.4 本地控制接口:`wisptermctl` + `src/ctl/`(报告 Phase 0 的原型入口)

loopback TCP + JSON-lines 协议,默认关闭、只听 `127.0.0.1`:

```zig
// src/ctl/protocol.zig
pub const Cmd = enum { panes, get_text, send_text };
pub const Request = struct { token, cmd: Cmd, id, recent, data };
// wisptermctl 还在客户端实现 wait-for(轮询 get-text 直到出现子串)
```

安全模型(`src/ctl/discovery.zig`):随机 token 写进 **0600** 的发现文件 `agent-control.json`(`{port, token}`)放配置目录;常量时间比较、请求大小限制、读超时。

```
wisptermctl panes
wisptermctl get-text  -t <surface-id> [--recent N]
wisptermctl send-text -t <surface-id> "<text>"
wisptermctl wait-for  -t <surface-id> "<substring>" [--timeout S]
```

> **映射到 MACR**:报告明说 wisptermctl"适合原型,但缺 Agent 身份 / 每-Agent ACL / 结构化任务语义 / 事件订阅 / 制品与验证结果 / 审计日志"。而这些**恰恰是 MACR 已经有的**(角色、确定性门、`.macr/runs/` 落盘)。所以 Phase 0 的现实路线是:**用 MACR 当控制面 + 任务语义,用 wisptermctl 风格的 loopback 接口当"观测/输入"的薄通道**接到真实终端。get-text/send-text/wait-for 三个动作就够跑通 Leader→Worker→Reviewer 最小闭环。

### 2.5 能力边界:`ToolHost` VTable(`ai_chat_types.zig`)

```zig
pub const ToolHost = struct {
    ctx: *anyopaque,
    collectSnapshot:        *const fn(...) anyerror!ToolSnapshot,   // 收集所有终端列表+快照
    surfaceSnapshot:        *const fn(...) anyerror![]u8,           // 单个 surface 快照
    writeSurface:           *const fn(...) bool,                    // 向指定 surface 写入
    spawnTab:               *const fn(...) anyerror!ToolSurface,    // 新建标签页
    closeTab:               *const fn(...) anyerror!ToolClosedTab,
    saveSshProfile / connectSshProfile / sshConnectionForSurface ...
};
```

AI 不直接乱碰窗口内部,而是通过这张函数指针表(VTable)访问宿主能力 —— 这是 AI 与运行时之间显式的**能力边界**。

> **映射到 MACR**:报告 17.5 建议把它升级为 **Capability Registry**:从"一个聊天会话调用窗口功能"升级为"**具名 Agent 通过显式授权的 Capability 调用 Runtime**"。MACR 的后端抽象(`agents/base.py`)是种子,但要加上"哪个 agent_id 被授予了哪些 capability"的授权层。

---

## 3. 接口 → MACR 映射总表

| 来源接口 | 类别 | MACR 现状 | 行动 |
|---|---|---|---|
| CrayBot `Executor` / `RunHandle` | Runtime Adapter | 有 `cli_backend`,缺可取消/流式句柄 | **对齐**:后端接口收敛为 `run→handle{result,cancel,on_chunk}` |
| CrayBot `resolveArgv` | 注入安全 | 已有 argv 契约测试 | **已对齐** |
| CrayBot `route→Decision` | 命令路由 | `cli.py` 分发 | 控制面指令入口可采用纯函数模式 |
| CrayBot `App`(单活动+心跳+制品) | 调度器雏形 | 线性 orchestrator | `ArtifactRegistry` 从 `collectArtifacts` 起步 |
| WispTerm `State`/`Detection` | Agent 状态观测 | **无** | **新建**:采用此状态枚举 + confidence |
| WispTerm OSC 7748 + Claude hooks | 结构化状态上报 | **无** | **新建,可照搬**:装 hook → 喂 EventLog |
| WispTerm `queuePtyWrite` 统一通道 | 终端运行时 | **无终端运行时** | 将来做终端 Adapter 时照搬设计 |
| WispTerm `wisptermctl`/`ctl` | 控制/观测薄通道 | Web 层是类比 | Phase 0:MACR 当控制面 + 此风格通道接终端 |
| WispTerm `ToolHost` VTable | 能力边界 | `agents/base.py` 种子 | **升级**为带授权的 Capability Registry |
| MACR 角色/确定性门/worktree/落盘 | 控制面 | **已有(报告说要补的就是这些)** | 复用,作为 `verified`/`approved` 层 |

---

## 4. 给 Phase 0 的最小闭环建议(不重写终端)

报告 Phase 0 + 上述接口,落到 MACR 上的最短路径:

1. **运行时**:用现成终端 + tmux,或直接复用 CrayBot 的 `LocalExecutor` 起 Claude/Codex 子进程。
2. **观测**:装 `claude_integration` 同款 OSC 7748 hook → 拿 `running/waiting_approval/done` 强信号;补 `agent_detector.detect` 启发式兜底。两路写入 MACR 的 `.macr/runs/` 事件流。
3. **任务语义 + 门**:沿用 MACR 现有 `discuss` 的角色 + Stage D 确定性门 + 人工门;把 detector 的 `done` 当 `observed`,测试转绿当 `verified`,严格不混。
4. **隔离**:写入型 Worker 用 MACR 已有的 `worktree.py`。
5. **控制通道**:`wisptermctl` 风格 loopback(get-text/send-text/wait-for)接终端;身份/ACL/审计走 MACR 控制面。

跑通 Leader→Worker→Reviewer 一次,即验证了 Multi-Agent Term 的产品闭环,再谈原生 UI(报告 Phase 5)。

---

## 5. 校验说明

- 本文所有接口签名摘自源码原文:CrayBot 见 `demo/craybot/src/{executor/types,executor/local,engines,router,app}.ts`;WispTerm 见 `demo/wispterm-main 2/src/{agent_detector,claude_integration,Surface,ai_chat_types}.zig` 与 `src/ctl/{protocol,discovery}.zig`、`src/wisptermctl.zig`。
- 未在沙箱编译/运行 WispTerm(无 `zig`)与 CrayBot(未 `npm install`);接口描述基于静态阅读,行为细节(如 confidence 具体阈值随版本)以源码为准。
- "MACR 现状"列依据 `macr/` 当前模块(`agents/`、`worktree.py`、`human_gate.py`、`discussion*`、`runlog.py`)与 README/roadmap 的自述,未逐一跑测复核。
