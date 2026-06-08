# V2 子项目 ② — 实时驱动 设计 (2026-06-08)

## 背景

V2 完整控制台拆为三个有依赖顺序的子项目:① 只读 Run 查看器(已完成并合并)、
**② 实时驱动(本 spec)**、③ 多运行管理。① 提供了 FastAPI 后端(`macr/web/`)、
归一化 `Stage`/`RunDetail` 模型、Vite+React SPA(`frontend/`)与 `macr web` 子命令。

② 让用户**从网页启动并驱动一个 run**:实时流式看 agent 输出、在浏览器里过人工门。

关键前提(① 已铺好):现有编排器 `run_collab` / `run_discuss` 的 **view 和 gate 都可注入**
(`run_discuss(..., view=, consensus_gate=, human_gate=, discussion_control=)`、
`run_collab(..., human_gate=, printer=)`);`DiscussionView` 是 Protocol;gate 是
`(state, *, printer=) -> HumanFeedback` 可调用。② 正是复用这些注入点。

## 目标

单个 live run:从网页启动 collab/discuss → 后台线程跑编排器 → WebSocket 流式推 agent
输出(复用 ① 的 Stage 模型渲染)→ 浏览器里过共识门与最终门(approve/reject/批注)→
run 结束照常落盘,可在 ① 查看器复看。

## 范围(已定)

- 单个活跃 live run(并发/队列 → ③)。
- 可启动 **collab** 与 **discuss**(都用真 claude+codex CLI)。`run`(API 路径)不纳入(无 key)。
- 交互 = 两个人工门(approve / reject / 文字批注);讨论轮次**自动推进**(等价 `--auto`)。

## 非目标(YAGNI)

- 多 run 并发 / 队列 / 管理面板、硬中断子进程(→ ③;② 只支持"门上 reject 即停")。
- 讨论 `discussion_control` 插话(轮次自动推进)。
- 鉴权 / 多用户 / 多 WS 客户端广播(单本地用户,单 WS 客户端)。
- `run`(单模型 API 路径)启动。

## 执行模型(方案 A:进程内后台线程 + 注入 WS-view + gate-bridge)

被否决的备选:B 子进程 `macr ... --json` 解析 stdout——CLI 门读 stdin/交互式,浏览器门
喂决定不可靠(dogfood 已证 stdin 脆),`--yes` 又无交互;文本流重建事件有损。
C 把编排器重写成 async 生成器——对已测同步代码大改,风险高不值。
A 直接复用编排器既有的 view/gate 注入点,gate = "阻塞调用 ↔ threading.Event" 干净映射,纯 stdlib。

## 架构

```
POST /api/runs/launch ──▶ RunManager 建 RunSession(单活跃)
                              │ 后台 thread: run_collab/run_discuss(注入 WebView + web-gates)
            WebView/gates ──▶ 事件总线(buffer + 线程安全推送)
                              ▼
        WebSocket /api/runs/active/ws  ◀──▶  浏览器(LiveRun:流式时间线 + 门面板)
```

## 后端组件(`macr/web/`)

### `session.py` · `RunSession`
管一个 live run。持有:
- `run_id`、`command`(collab|discuss)、`status`(running|awaiting_gate|done|error)。
- `events: list[dict]` —— 全量事件 buffer,供重连重放。
- `gate_event: threading.Event`、`gate_response: HumanFeedback | None` —— 门桥接。
- 后台线程跑编排器。
- `emit(event)` —— 追加 buffer 并推给当前 WS 连接。**原子化**:WS 连接时在锁内"快照
  buffer + 挂接一个 per-connection 异步队列";此后每条 emit 既进 buffer 又(若有连接)
  经 `loop.call_soon_threadsafe` 进该队列。锁保证快照与挂接之间无 emit 漏/重。

### `webview.py` · `WebView`
实现 `DiscussionView`(plan/turn/consensus/review/evaluation/interjection/note/status)
并充当 collab 的 printer。每个方法构造一条 **Stage 形状**的事件(复用 ① 的 `Stage`)
调 `session.emit({"type":"stage", ...})`;note/status 调 `emit({"type":"note", ...})`。

### web gates
`web_consensus_gate` / `web_final_gate`,签名 `(state, *, printer=None) -> HumanFeedback`:
1. 构造 `gate_request` 事件(gate 类型 + 展示数据:共识 summary/steps,或 diff + 测试结果),
   `emit` 它,置 status=awaiting_gate。
2. 阻塞 `gate_event.wait()`。
3. 返回 `gate_response`,清空 `gate_event` 与 `gate_response`,status 回 running。

### `RunManager`
模块级单活跃 session 持有者(`active: RunSession | None`)。**可注入 backends**:测试注入
`FakeAgentBackend`,默认建真 CLI backends(claude/codex,沙箱与 CLI 一致:codex review
read-only、impl workspace-write)。`launch()` 已有活跃 session 则拒绝。

### 端点(扩 `app.py`)
- `POST /api/runs/launch` —— body `{command, task, repo, test_cmd, options}`;校验(repo 存在、
  test_cmd 非空、task 非空);已有活跃 session → **409**;校验失败 → **400**;成功返回 `{run_id}`。
- `GET /api/runs/active` —— 当前 session 状态(或 204/null)。
- `WS /api/runs/active/ws` —— 连接时重放 buffer 再续流;接收门回应消息。

## 事件协议(WS 上的 JSON)

服务端→客户端:
- `stage`:`{type:"stage", stage:{kind,label,agent,status,body}}`(同 ① 的 Stage)。
- `note`:`{type:"note", text}`。
- `gate_request`:`{type:"gate_request", gate:"consensus"|"final", data:{...}}`。
- `status`:`{type:"status", status}`。
- `done`:`{type:"done", run_id, decision}`。
- `error`:`{type:"error", message}`。

客户端→服务端(门回应):`{decision:"approve"|"reject", feedback:""}`。

## 前端组件(`frontend/src/`)

- **`LaunchForm`**(`/launch`):选命令(collab/discuss)、task、repo、test-cmd、可选
  max-rounds/max-revisions/timeout/no-subagents → `POST /api/runs/launch`;成功跳 `/live`。
- **`LiveRun`**(`/live`):开 WS → `stage` 事件用**复用 ① 的 `StageCard`** 渲染成实时增长
  的时间线;`note` 进顶部状态条;`gate_request` 弹 **`GatePanel`**(approve/reject + 批注
  textarea)经 WS 回送;`done` 显示最终决定 + 到 `/runs/:id`(① 查看器)的链接;`error` 显示错误。
- 路由新增 `/launch`、`/live`;`/` 与 `/runs/:id` 不变;导航加 "+ New run" 入口。

## 错误处理与生命周期

- launch:已有活跃 → 409;repo 不存在/test-cmd 空/task 空 → 400。
- 编排器线程内抛异常 → `emit` 一条 `error` + status=error,线程退出,session 保留供查看。
- WS 断开重连:连接时重放全量 buffer 再续流(单 WS 客户端;新连接替换旧的)。
- run 结束照常落盘 `.macr/runs/<id>/`,可在 ① 复看。
- 取消:本轮只"门上 reject 即停"(reject 走编排器拒绝分支自然结束);硬中断 → ③。

## 测试策略(TDD)

- **后端(重点)**:
  - `RunSession` 单测:注入脚本化假编排器(emit 若干事件 + 命中一个门),断言 buffer 累积、
    门阻塞到收到回应、回应正确解 `HumanFeedback`、status 转换。
  - 端到端(最强):把现有 `FakeAgentBackend` 注入真的 `run_collab`(后台线程跑),配 `WebView`
    + web-gates,用 FastAPI TestClient 的 WebSocket:launch → 收 stage → 收 `gate_request`
    → 回 approve → 收 `done`。无需真 CLI。
  - 端点:launch 正常 / 409(并发)/ 400(非法输入);active 状态。
- **前端(轻)**:`LaunchForm` 提交一个;`LiveRun` 用 mock WebSocket 喂 stage+gate_request,
  断言时间线渲染 + 门面板出现 + 点 approve 回送正确。

## 验收

- `macr web` 下,`/launch` 启动一个 collab/discuss run;`/live` 实时流式显示阶段时间线。
- 命中共识门/最终门时浏览器弹门面板;approve/reject/批注经 WS 回送,编排器继续/结束。
- run 结束后可在 `/runs/:id` 复看落盘记录。
- 已有活跃 session 时再 launch → 409;非法输入 → 400;线程异常 → error 事件不崩服务。
- 后端 RunSession + 端到端 WS + 端点全测绿;前端两个组件渲染/交互测试绿。
