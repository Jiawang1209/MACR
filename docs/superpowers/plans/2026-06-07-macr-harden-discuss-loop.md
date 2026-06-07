# MACR 硬化 discuss 闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `macr discuss` 的"讨论→写码→审码"闭环能一键无人值守端到端跑通(`--yes` 自动过门),并在后端 CLI 失败时呈现 `--json` 流里的真实错误而非无害的 stderr 噪音。

**Architecture:** 两处聚焦工程改动,不动闭环逻辑/角色:(1) 新增 `stream_error` 从 CLI 的 JSONL stdout 提取真因,两个 backend 在非零退出时用它富化 `AgentError`;(2) 新增 `auto_approve_gate` + `discuss --yes`,无人值守时共识门/最终门自动 approve 不读 stdin,非 TTY 且无 `--yes` 时给清晰报错。

**Tech Stack:** Python 3.13, pytest, `.venv` 本地虚拟环境(所有命令用 `.venv/bin/...`)。

> **设计依据:** `docs/superpowers/specs/2026-06-07-macr-harden-discuss-loop-design.md`
>
> **关键约定:**
> - 所有测试命令用 `.venv/bin/pytest ...`(项目 venv,绝不用 base/conda)。
> - 提交信息用各步给出的原文,**不加** AI 署名 / Co-Authored-By / "Generated with"。
> - 直接在 `main` 分支开发(用户已同意),不开新分支。
> - 每个 Task 末尾跑该模块测试 + 全套回归 `.venv/bin/pytest -q`,绿了才提交。

---

## 文件结构(改动地图)

| 文件 | 责任 | 改动 |
|---|---|---|
| `macr/agents/trace.py` | CLI 流解析 | 新增 `stream_error(lines, *, source)` |
| `macr/agents/cli_backend.py` | 真实 CLI 后端 | 两个 backend 非零退出分支富化 `AgentError` |
| `macr/human_gate.py` | 人工门 | 新增 `auto_approve_gate` |
| `macr/cli.py` | CLI 入口 | `discuss` 加 `--yes` + 门装配 + 非 TTY 无 `--yes` 报错 |
| `tests/test_stream_error.py` | 测试 | 新建:`stream_error` 单测 |
| `tests/test_cli_backend.py` | 测试 | 扩展:非零退出富化 |
| `tests/test_human_gate.py` | 测试 | 扩展:`auto_approve_gate` |
| `tests/test_cli_discuss.py` | 测试 | 扩展:`--yes` 与非 TTY 守卫 |
| `docs/roadmap.md` | 文档 | 勾掉发现 3、发现 7 |

---

## Task 1: `stream_error` —— 从 JSONL 流提取真因

**Files:**
- Modify: `macr/agents/trace.py`
- Test: `tests/test_stream_error.py`(新建)

- [ ] **Step 1: 写失败测试** —— 新建 `tests/test_stream_error.py`

```python
from macr.agents.trace import stream_error


def _jl(*objs):
    import json
    return [json.dumps(o) for o in objs]


def test_codex_error_event():
    lines = _jl({"type": "thread.started"}, {"type": "error", "message": "boom"})
    assert stream_error(lines, source="codex") == "boom"


def test_codex_turn_failed():
    lines = _jl({"type": "turn.started"},
                {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    assert stream_error(lines, source="codex") == "You've hit your usage limit."


def test_claude_error_message():
    lines = _jl({"type": "system"}, {"type": "x", "error": {"message": "claude broke"}})
    assert stream_error(lines, source="claude") == "claude broke"


def test_claude_is_error_result():
    lines = _jl({"type": "result", "is_error": True, "result": "overloaded"})
    assert stream_error(lines, source="claude") == "overloaded"


def test_no_error_returns_none():
    lines = _jl({"type": "turn.started"}, {"type": "turn.completed"})
    assert stream_error(lines, source="codex") is None


def test_non_json_and_empty_are_safe():
    assert stream_error(["not json", "", "   "], source="codex") is None
    assert stream_error([], source="claude") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stream_error.py -q`
Expected: FAIL — `ImportError: cannot import name 'stream_error'`

- [ ] **Step 3: 实现** —— 在 `macr/agents/trace.py` 的 `parse_codex_stream` 之后追加(复用文件内已有的 `_iter_json_lines`):

```python
def stream_error(lines: list[str], *, source: str) -> str | None:
    """Extract a human-readable error message from a CLI's JSONL stdout, else None.

    Surfaces the real failure (e.g. codex usage limit) instead of an incidental
    stderr line when a CLI exits non-zero. Never raises: malformed lines are skipped.
    """
    for obj in _iter_json_lines(lines):
        t = obj.get("type")
        if source == "codex":
            if t == "error" and obj.get("message"):
                return str(obj["message"])
            if t == "turn.failed":
                msg = (obj.get("error") or {}).get("message")
                if msg:
                    return str(msg)
        else:  # claude (best-effort across stream-json event shapes)
            if t == "error" and obj.get("message"):
                return str(obj["message"])
            err = obj.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if obj.get("is_error") and obj.get("result"):
                return str(obj["result"])
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stream_error.py -q`
Expected: PASS(6 passed)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/agents/trace.py tests/test_stream_error.py
git commit -m "feat: add stream_error to extract real CLI failure from JSONL stdout"
```

---

## Task 2: backend 非零退出富化 `AgentError`

**Files:**
- Modify: `macr/agents/cli_backend.py`
- Test: `tests/test_cli_backend.py`

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_cli_backend.py` 末尾追加

```python
def test_codex_nonzero_surfaces_stream_error_over_stderr():
    from macr.agent import AgentError
    from macr.agents.base import FakeProcessRunner, ProcResult

    stdout = '{"type":"turn.started"}\n{"type":"turn.failed","error":{"message":"usage limit"}}'
    runner = FakeProcessRunner([ProcResult(1, stdout, "Reading additional input from stdin...")])
    backend = CodexCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    with pytest.raises(AgentError) as ei:
        backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert "usage limit" in str(ei.value)
    assert "Reading additional input" not in str(ei.value)


def test_codex_nonzero_falls_back_to_stderr_when_no_stream_error():
    from macr.agent import AgentError
    from macr.agents.base import FakeProcessRunner, ProcResult

    runner = FakeProcessRunner([ProcResult(2, "", "boom on stderr")])
    backend = CodexCliBackend(runner=runner)
    state = SharedState(run_id="R1", user_query="task", worktree_path="/tmp/wt")
    with pytest.raises(AgentError) as ei:
        backend.run_role(EXECUTOR_C, state, run_id="R1", task_id="R1", timestamp="t")
    assert "boom on stderr" in str(ei.value)
```

> 说明:非零退出时 `call_fn` 立即 raise `AgentError`,`validate_with_retry` 只捕 `ValidationError`/`ValueError`,故 `AgentError` 直接外抛——一个 `ProcResult` 即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_cli_backend.py::test_codex_nonzero_surfaces_stream_error_over_stderr -q`
Expected: FAIL — 断言 `"usage limit" in ...` 失败(当前只透传 stderr)

- [ ] **Step 3: 实现** —— `macr/agents/cli_backend.py`

(a) 顶部 import 增加 `stream_error`:

```python
from macr.agents.trace import TraceSink, parse_claude_stream, parse_codex_stream, stream_error
```

(b) `ClaudeCliBackend.run_role` 的非零分支:

```python
            if res.returncode != 0:
                detail = stream_error(res.stdout.splitlines(), source="claude") or res.stderr.strip()
                raise AgentError(f"claude CLI exited {res.returncode}: {detail}")
```

(c) `CodexCliBackend.run_role` 的非零分支:

```python
            if res.returncode != 0:
                detail = stream_error(res.stdout.splitlines(), source="codex") or res.stderr.strip()
                raise AgentError(f"codex CLI exited {res.returncode}: {detail}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_cli_backend.py -q`
Expected: PASS(既有 + 新增 2 全绿)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/agents/cli_backend.py tests/test_cli_backend.py
git commit -m "fix: surface real CLI error from --json stream on non-zero exit"
```

---

## Task 3: `auto_approve_gate`

**Files:**
- Modify: `macr/human_gate.py`
- Test: `tests/test_human_gate.py`

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_human_gate.py` 末尾追加

```python
def test_auto_approve_gate_approves_without_reading_stdin():
    from macr.human_gate import auto_approve_gate
    from macr.schemas import SharedState

    def _boom(_prompt):
        raise AssertionError("auto_approve_gate must not read stdin")

    s = SharedState(run_id="R1", user_query="q")
    hf = auto_approve_gate(s, input_fn=_boom, printer=lambda *_: None, timestamp="t")
    assert hf.decision == "approve" and hf.timestamp == "t"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_human_gate.py::test_auto_approve_gate_approves_without_reading_stdin -q`
Expected: FAIL — `ImportError: cannot import name 'auto_approve_gate'`

- [ ] **Step 3: 实现** —— 在 `macr/human_gate.py` 末尾追加(`now_iso` 顶部已 import):

```python
def auto_approve_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] | None = None,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    """Unattended gate: approve without reading stdin (used by `discuss --yes`)."""
    printer("\n[auto-approve] gate passed without prompting (--yes)")
    return HumanFeedback(decision="approve", feedback="", timestamp=timestamp or now_iso())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_human_gate.py -q`
Expected: PASS

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/human_gate.py tests/test_human_gate.py
git commit -m "feat: add auto_approve_gate for unattended discuss runs"
```

---

## Task 4: CLI `--yes` + 门装配 + 非 TTY 守卫

**Files:**
- Modify: `macr/cli.py`
- Test: `tests/test_cli_discuss.py`

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_cli_discuss.py` 末尾追加

```python
def test_discuss_yes_auto_approves_without_stdin(tmp_path, monkeypatch):
    """--yes makes both gates auto-approve; no stdin read; zero exit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true",
         "--max-rounds", "1", "--yes"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        # NOTE: do NOT inject gates — let --yes wire auto_approve_gate
    )
    assert rc == 0


def test_discuss_non_tty_without_yes_errors_clearly(tmp_path, monkeypatch, capsys):
    """Non-TTY + interactive gates + no --yes → exit 2 with a --yes hint (not raw EOFError)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(
        ["discuss", "build it", "--repo", str(repo), "--test-cmd", "true", "--max-rounds", "1"],
        claude_backend=_claude(), codex_backend=_codex_discuss(), impl_codex_backend=_codex_impl(),
        discussion_control=lambda s, r, **kw: ControlDecision("end"),
        # gates NOT injected → resolve to interactive console gates → guard fires
    )
    assert rc == 2
    assert "--yes" in capsys.readouterr().err
```

> 说明:`_claude`/`_codex_discuss`/`_codex_impl` 已在文件顶部定义并含 `discuss_reviewer` 脚本(Stage D 时补);本任务复用。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_cli_discuss.py::test_discuss_yes_auto_approves_without_stdin -q`
Expected: FAIL — `unrecognized arguments: --yes`

- [ ] **Step 3: 实现** —— `macr/cli.py`

(a) `discuss` 子解析器加(在 `--tui` 那行附近):

```python
    discuss_p.add_argument("--yes", action="store_true",
                           help="无人值守:自动通过共识门与最终人工门(不读 stdin)")
```

(b) 替换 `_discuss_command` 现有的门装配块。把:

```python
    if consensus_gate is None:
        from macr.human_gate import consensus_human_gate
        consensus_gate = view.consensus_gate if tui_active else consensus_human_gate
    if human_gate is None:
        human_gate = view.final_gate if tui_active else collab_human_gate
```

改为:

```python
    from macr.human_gate import auto_approve_gate, consensus_human_gate
    auto_gate = getattr(args, "yes", False)
    if consensus_gate is None:
        if auto_gate:
            consensus_gate = auto_approve_gate
        else:
            consensus_gate = view.consensus_gate if tui_active else consensus_human_gate
    if human_gate is None:
        if auto_gate:
            human_gate = auto_approve_gate
        else:
            human_gate = view.final_gate if tui_active else collab_human_gate

    # 非 TTY 且未给 --yes 且门为交互式 console 门 → 会因读不到 stdin 而 EOF;提前清晰报错。
    if not sys.stdout.isatty() and not auto_gate and (
        consensus_gate is consensus_human_gate or human_gate is collab_human_gate
    ):
        print("error: 非交互环境(非 TTY)下运行 discuss 需要 --yes 自动通过人工门;"
              "否则人工门会因无法读取 stdin 而失败。", file=sys.stderr)
        return 2
```

> 注:`collab_human_gate` 已在 `cli.py` 顶部 import;此处再 import `consensus_human_gate` 与 `auto_approve_gate` 以便装配与身份比较。注入的门(测试用 `consensus_gate=`/`human_gate=`)优先级最高,既不被 `--yes` 覆盖也不触发守卫(它们不是 `consensus_human_gate`/`collab_human_gate` 本体)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_cli_discuss.py -q`
Expected: PASS(既有 + 新增 2 全绿;尤其既有 `test_discuss_tui_flag_falls_back_non_tty` 因注入了门,不触发守卫,仍绿)

- [ ] **Step 5: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add macr/cli.py tests/test_cli_discuss.py
git commit -m "feat: add discuss --yes auto-gate and clear non-TTY error"
```

---

## Task 5: 文档(勾掉 backlog)

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: 把发现 3、发现 7 两条待办勾上** —— `docs/roadmap.md` 的「V1 待办」小节,将:

```markdown
- [ ] **错误透传**(发现 7):后端非零退出时,`AgentError` 应优先从 `--json` 流里提取真实错误(如 `turn.failed` / usage limit),而非只透传 stderr——避免真因被无害的 stderr 信息行掩盖。
- [ ] **headless 自动门**(发现 3):提供无人值守过人工门的机制(如 `--yes`,或让 `--auto` 同时自动 approve 共识门/最终门),不依赖管道 stdin(`codex exec` 会把管道 stdin 当 `<stdin>` 块追加进 prompt)。
```

改为(标记完成 + 注明落地):

```markdown
- [x] **错误透传**(发现 7):后端非零退出时 `AgentError` 优先从 `--json` 流提取真因(`stream_error`),stderr 兜底。
- [x] **headless 自动门**(发现 3):`discuss --yes` 自动过共识门/最终门(`auto_approve_gate`),不读 stdin;非 TTY 无 `--yes` 时清晰报错。`--auto` 仅管讨论轮次。
```

(保留第三条 "codex executor 完整闭环验证" 不变——它待配额恢复后重跑。)

- [ ] **Step 2: 全套回归**

Run: `.venv/bin/pytest -q`
Expected: 全绿

- [ ] **Step 3: 提交**

```bash
git add docs/roadmap.md
git commit -m "docs: mark dogfood findings 3 and 7 done in roadmap"
```

---

## Self-Review(plan 作者已完成)

**Spec coverage:**
- §3.1 `stream_error`(codex error/turn.failed、claude best-effort、安全跳过)→ Task 1。
- §3.2 两个 backend 非零退出富化(真因优先、stderr 兜底)→ Task 2。
- §4.1 `auto_approve_gate`(不读 stdin、签名兼容)→ Task 3。
- §4.2 `--yes` + 门装配(`--yes` 覆盖默认、注入门优先、非 TTY 无 `--yes` 守卫)→ Task 4。
- §6 错误处理(解析安全、仅非零触发、`--auto`/`--yes` 独立、非 TTY 守卫)→ Task 1(安全跳过测试)+ Task 2 + Task 4(守卫测试)。
- §7 测试计划 → 各 Task 测试步;§8 文件清单 → 各 Task。

**Placeholder scan:** 无 TBD/TODO;每个代码步给出完整代码与确切命令。

**Type/name consistency:**
- `stream_error(lines: list[str], *, source: str) -> str | None`(Task 1)与 Task 2 两处调用 `stream_error(res.stdout.splitlines(), source="codex"/"claude")`、Task 1 测试签名一致。
- `auto_approve_gate(state, *, input_fn=, printer=, timestamp=)`(Task 3)与 Task 3 测试调用、Task 4 装配(作为 `consensus_gate`/`human_gate` 互换)签名兼容。
- Task 4 守卫用 `consensus_gate is consensus_human_gate or human_gate is collab_human_gate` 做身份比较;二者分别本地 import 与顶部 import,均在作用域内。
- `getattr(args, "yes", False)` 与 `discuss_p.add_argument("--yes", ...)`(argparse 将 `--yes` 映射为 `args.yes`)一致。
- 既有 `test_discuss_tui_flag_falls_back_non_tty` 注入了门 → 守卫不触发、`--yes` 不覆盖,保持绿(已在 Task 4 Step 4 标注)。
