# MACR Stage C2 — rich 双栏实况视图 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:Stage C2(把 C1 讨论升级为 rich 双栏 live 视图 —— 融合的"皮")
> 前置:V0、V1、Stage A、Stage B、Stage C1(人可插话的三方讨论)已完成并合并到 `main`。本 spec 在 `macr` 包之上扩展。
> 定位:**机制不变,只加视图层。** 把 C1 的逐轮单终端打印,升级为 `rich` 左右两栏(Claude / Codex)+ 底部状态/人声面板的实时围观视图。

---

## 1. 目标与非目标

### 目标
- 给 `macr discuss` 加 `--tui`:用 `rich.Live` 渲染**左右两栏**(左 Claude、右 Codex)+ header + 底部面板,让用户像 agent-bridge / tmux 那样**实时围观两个 agent 的讨论**。
- 引入结构化视图接口 `DiscussionView`,orchestrator 发**结构化事件**而非拼好的字符串;默认 `ConsoleView` **完整保留 C1 行为**,新增 `TwoPaneView`(rich)。
- 不破坏 C1/Stage A/B/V1 现有行为与测试。纯 CLI、零 API key。

### 非目标(本阶段不做)
- **不做逐字真流式**(边生成边吐字)—— C2 仍是"每轮完成即填进对应栏";机制不变。
- 不做 `textual` 全 App / 可独立滚动活栏 / 原生输入框(那是更后面的沉浸增强)。
- 不改讨论/共识/实现的任何**逻辑**(只改"如何显示")。
- 不做 Web/UI。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 范式 | `rich` 顺序式双栏(保留 C1 顺序阻塞 orchestrator) |
| 视图抽象 | `DiscussionView` 接口;`ConsoleView`(默认=C1)/ `TwoPaneView`(rich) |
| 开关 | `--tui` opt-in,默认 `ConsoleView`;非真终端自动回退并提示 |
| 人声位置 | 插话 / 提示 / 状态 都进**底部面板**(左右栏归属 Claude/Codex) |
| 重构范围 | `printer→view`:动 `discussion.py` + `cli.py` + 两个测试文件;`_implementation_loop`(Stage A 共用)**不动** |
| 实现阶段 | 复用双栏;`_implementation_loop` 的状态行经 printer 适配器进 `view.note` |
| 依赖 | 新增 `rich` |

---

## 3. 视图接口 `DiscussionView`

新增 `macr/discussion_view.py`:

```python
class DiscussionView(Protocol):
    def plan(self, agent: str, content: dict) -> None: ...          # 第0轮某方计划
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...  # 讨论轮
    def interjection(self, round_no: int, text: str) -> None: ...   # 人的插话
    def status(self, text: str) -> None: ...                        # 阶段/轮次/测试/决策
    def consensus(self, content: dict) -> None: ...
    def note(self, text: str) -> None: ...                          # 杂项([blocked]/[human·…])
```

- `agent ∈ {"claude", "codex"}`。
- **`ConsoleView`**:每个方法按 C1 现有格式打印到一个注入的 `console`(默认 `print`),**逐栏标题、内容与 C1 完全一致**(C1 的 `_print_plan`/`_print_turn` 逻辑迁入此类)。
- **`SilentView`**:全部 no-op(测试用)。
- **`FakeView`**:记录 `(method, args)` 事件列表(测试断言用)。
- **`TwoPaneView`**:见 §4。

---

## 4. `TwoPaneView`(rich 双栏)

布局(`rich.Layout`,由 `rich.Live` 驱动):
```
┌── 主题:… ── 阶段:讨论 第2轮 ─────────────────┐  header
├──────── Claude ────────┬──────── Codex ───────┤
│ 第0轮 计划:…           │ 第0轮 计划:…          │  左/右栏:随轮次增长的文本
│ 第1轮:[concerns]…      │ 第1轮:…               │
├──────────────────────────────────────────────┤
│ 你/状态:测试 passed=… · 决策 PASS             │  bottom:状态 + 人插话 + 边界提示
└──────────────────────────────────────────────┘
```
- `TwoPaneView` 内部维护:`claude_lines: list[str]`、`codex_lines: list[str]`、`status_lines: list[str]`、`header: str`。每个 `plan/turn/...` 方法把内容追加到对应缓冲并 `live.refresh()`。
- `plan(agent,...)` / `turn(agent,...)`:按 `agent` 进左或右栏。
- `interjection` / `status` / `note`:进底部面板(`status_lines`);`interjection` 高亮"你"。
- `consensus`:可在底部或一条横跨提示中显示。
- header 显示主题 + 当前阶段/轮次(由 `status` 调用更新,或单独维护)。

### 4.1 控制与门控配合 Live(`TwoPaneView` 自带)
`rich.Live` 占用终端,读输入前必须 `live.stop()`、读完 `live.start()`。故 `TwoPaneView` 自身提供与 C1 同签名的 control/gate:
- `control(state, round_no, *, printer=None) -> ControlDecision`:`live.stop()` → 复用 `interactive_discussion_control`(传 `input`/`print`)→ `live.start()`。
- `consensus_gate(state, *, printer=None) -> HumanFeedback`:`live.stop()` → `consensus_human_gate` → `live.start()`。
- `final_gate(state, *, printer=None) -> HumanFeedback`:`live.stop()` → `collab_human_gate` → `live.start()`。
- 提供 `__enter__/__exit__`(或 `start()/stop()`)管理 `Live` 生命周期。

### 4.2 终端回退
`TwoPaneView` 构造时检测 `sys.stdout.isatty()`;非真终端则**不启用 Live**,退化为 `ConsoleView` 行为并 `note("(non-tty: falling back to console view)")`。`cli` 在 `--tui` 但非 tty 时也可直接选 `ConsoleView`。

---

## 5. orchestrator 改动(`discussion.py`)

- `run_discuss` 的 `printer: Callable` 参数 **替换为** `view: DiscussionView = ConsoleView()`。
- 内部:`printer(f"━━━ {agent} …")` 等改为 `view.plan(agent, content)` / `view.turn(agent, round_no, content)` / `view.interjection(round_no, text)` / `view.status(...)` / `view.consensus(content)` / `view.note(...)`。
- 调 `_implementation_loop` 时传 `printer=lambda s: view.note(s)`(或 `view.status`),`_implementation_loop` **签名与逻辑不变**,Stage A `run_collab` 仍传 `printer=print`。
- `discussion_control` / `consensus_gate` / `human_gate` 仍是注入参数(默认值不变);`--tui` 时由 cli 绑定到 `TwoPaneView` 的对应方法。

---

## 6. CLI(`cli.py`)

- `discuss` 子命令加 `--tui`(`action="store_true"`,默认关)。
- `_discuss_command`:
  - 默认(无 `--tui` 或非 tty):`view = ConsoleView()`,control/gate 用 C1 默认注入。
  - `--tui` 且 tty:`view = TwoPaneView(...)`;`run_discuss(..., view=view, discussion_control=view.control, consensus_gate=view.consensus_gate, human_gate=view.final_gate)`;用 `with view:`(或 try/finally start/stop)包住运行,确保 Live 正确收尾。
- 注入式后端/控制路径(测试用)保持可用:测试传 `view=`(FakeView/SilentView)+ 注入 control/gate。
- `main(...)` 增加可注入 `view`(默认 None → ConsoleView)。

---

## 7. 测试策略(TDD)

- `DiscussionView` 实现:
  - `ConsoleView`:注入假 console(收集输出),断言 `plan/turn/...` 产出含 agent / 轮次 / 关键内容。
  - `FakeView`:断言记录的事件序列正确。
  - `TwoPaneView`:用 `rich.Console(record=True)`(强制非交互)或直接断言其内部缓冲(`claude_lines`/`codex_lines`/`status_lines`)在喂事件后含关键字;**不进真 Live 交互**;断言非 tty 时回退不崩。
- `run_discuss` 改 `view` 后:`tests/test_discussion.py` 的 `printer=lambda *_: None` 改为 `view=SilentView()`(或 `FakeView`);新增断言"orchestrator 按顺序发出 plan(claude)/plan(codex)/turn(...)/interjection/consensus 事件"。
- `tests/test_cli_discuss.py`:`--tui` 在测试(非 tty)下回退 ConsoleView,流程仍 approve→0 / abort→1;并测一条 `view=FakeView()` 注入路径。
- C1 行为回归:`ConsoleView` 默认下 `run_discuss` 的可见输出与 C1 等价(可用 FakeView 断言事件,不强求逐字节相同字符串)。
- V1 / Stage A / Stage B / C1 全部测试保持绿。
- 真实 `claude`/`codex` + 真 TUI 仅在手动冒烟(`scripts/smoke_discuss.py` 加 `--tui` 说明)。
- commit 无 AI 署名;依赖只在 `.venv`;`pyproject.toml` 加 `rich`(`.venv/bin/pip install -e .` 重装拉取)。

---

## 8. 错误处理

- 非 tty / `rich` 不可用:回退 `ConsoleView`,不崩。
- `Live` 异常:`with view`/try-finally 确保 `live.stop()` 收尾,终端不被占死。
- 其余讨论/共识/实现错误处理沿用 C1(AgentError→打印/标注、try/finally 落 `state.json`、abort/共识 reject 保留 worktree)。

---

## 9. 完成标准(Definition of Done)

- [ ] `macr discuss … --tui` 在真终端用 rich 双栏(Claude 左 / Codex 右 + 底部状态/人声)实时呈现讨论;不带 `--tui` 或非 tty 时退回 C1 单终端逐轮(行为不变)。
- [ ] `DiscussionView` 接口 + `ConsoleView`(默认,=C1)/ `SilentView` / `FakeView` / `TwoPaneView` 实现齐备。
- [ ] `run_discuss` 改用 `view` 发结构化事件;`_implementation_loop` 与 Stage A `run_collab` 不变。
- [ ] `--tui` 的 control/gate 正确暂停/恢复 `Live`;Live 生命周期收尾安全。
- [ ] 非 tty 自动回退,不崩;`rich` 加入依赖。
- [ ] 全部单元 + 集成测试通过(FakeView/SilentView + 真临时 git 仓库,不触真实 CLI/真 Live 交互);V1/Stage A/B/C1 零回归。
