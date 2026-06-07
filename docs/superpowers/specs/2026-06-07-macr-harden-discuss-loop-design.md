# MACR 硬化 discuss 闭环 设计规格(Design Spec)

> 日期:2026-06-07
> 阶段:硬化(让"讨论→写码→审码"闭环能稳定、无人值守地端到端真机跑通)
> 前置:V0、V1、Stage A–D 已完成并合并到 `main`。本 spec 基于 2026-06-07 真机 dogfood 报告(`docs/dogfood-2026-06-07-v1-real-cli.md`)的发现 3 与发现 7。
> 定位:**不加新角色、不改闭环结构,只补两处工程缺陷**,使现有 `macr discuss` 的完整闭环能一键无人值守跑通、出错时能看懂真因。

---

## 1. 目标与非目标

### 目标
- **发现 7 — 错误透传**:后端 CLI 非零退出时,`AgentError` 优先呈现 `--json` 流里的真实错误(如 codex 的 `turn.failed` / usage limit),而非只透传 stderr(此前 stderr 恰是无害的 "Reading additional input from stdin..." 噪音,掩盖了真因,导致诊断跑了三遍)。
- **发现 3 — headless 自动门**:给 `macr discuss` 加 `--yes`,置位时共识门与最终人工门自动 approve、**不读 stdin**,使无人值守 = `--auto --yes` 可一键跑完整闭环。非 TTY 且未给 `--yes` 时,把裸 `EOFError` 换成清晰报错。

### 非目标(本次不做)
- 不改讨论/共识/Stage D 审查门/实现循环的任何**逻辑或角色**。
- 不动 `collab`/`run` 子命令的门(只动 `discuss` 闭环)。
- claude 的 error 事件提取仅 best-effort(codex 是已证实痛点,做扎实);不做交互式确认分级;不做 PDF/其它输入。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 错误来源优先级 | 非零退出时 `stream_error(...) or stderr.strip()`(流内真因优先,stderr 兜底) |
| `stream_error` 位置 | `macr/agents/trace.py`(与现有 `parse_claude_stream`/`parse_codex_stream` 同处) |
| 触发时机 | 仅在 CLI **非零退出**时富化(成功路径不变) |
| 无人值守开关 | 新增 `--yes`,与 `--auto` **职责分离**(`--auto`=讨论轮次自动推进;`--yes`=人工门自动 approve) |
| 自动门函数 | `auto_approve_gate` 复用于共识门 + 最终门 |
| 非 TTY 无 `--yes` | 不再裸 `EOFError`,给一句"加 --yes"的清晰报错 |

---

## 3. 组件 1 — 错误透传

### 3.1 `stream_error`(新增于 `macr/agents/trace.py`)

```python
def stream_error(lines: list[str], *, source: str) -> str | None:
    """从 CLI 的 JSONL stdout 中提取一条人类可读的错误信息;无错误返回 None。

    source="codex": 命中 {"type":"error","message":...} 或
                    {"type":"turn.failed","error":{"message":...}}。
    source="claude": best-effort,命中带 is_error / error 字段的事件。
    """
```

- 逐行 `json.loads`(忽略非 JSON 行);命中第一条错误事件即返回其 message。
- codex 形态(已由真机确认):
  - `{"type":"error","message":"..."}`
  - `{"type":"turn.failed","error":{"message":"..."}}`
- claude 形态(best-effort):事件含 `is_error: true` 或 `error.message` / `result` 错误子类型时取其文本。
- 全部无命中 → `None`。

### 3.2 两个 backend 富化 `AgentError`

`macr/agents/cli_backend.py`,`ClaudeCliBackend` 与 `CodexCliBackend` 的 `call_fn` 内,非零退出分支:

```python
if res.returncode != 0:
    detail = stream_error(res.stdout.splitlines(), source="codex") or res.stderr.strip()
    raise AgentError(f"codex CLI exited {res.returncode}: {detail}")
```

(claude 分支同理,`source="claude"`、文案 `claude CLI exited ...`。)成功路径不变。

---

## 4. 组件 2 — headless 自动门

### 4.1 `auto_approve_gate`(新增于 `macr/human_gate.py`)

```python
def auto_approve_gate(state, *, printer=print, timestamp=None, **kwargs) -> HumanFeedback:
    """无人值守:不读 stdin,直接 approve。"""
    printer("\n[auto-approve] gate passed without prompting (--yes)")
    return HumanFeedback(decision="approve", feedback="", timestamp=timestamp or now_iso())
```

签名与 `consensus_human_gate`/`collab_human_gate` 兼容(接受 `state` + `printer`/`timestamp`/`input_fn` 等 kwargs),以便在 `_discuss_command` 处可互换装配。

### 4.2 CLI 与装配(`macr/cli.py`)

- `discuss` 子命令新增:`discuss_p.add_argument("--yes", action="store_true", help="无人值守:自动通过共识门与最终人工门(不读 stdin)")`。
- `_discuss_command` 装配门时(在现有"未注入则按 tui/console 选择"逻辑之上叠加):
  - 若 `args.yes`:`consensus_gate` 与 `human_gate` 未被显式注入者,一律置为 `auto_approve_gate`(覆盖 tui/console 默认)。
  - 若**非 TTY 且未给 `--yes` 且门为交互式**:不进入会 `EOFError` 的路径,提前打印清晰报错并返回 2,提示"非交互环境请加 --yes"。
- 注入点(测试用 `consensus_gate=`/`human_gate=` 注入)优先级最高,不被 `--yes` 覆盖,保持现有测试与可测试性。

---

## 5. 状态与产物

无新增状态字段;无新增落盘格式。`--yes` 仅改变门的来源;`stream_error` 仅改变 `AgentError` 文本。

---

## 6. 错误处理与边界

- `stream_error` 对非 JSON 行、空行、缺字段一律安全跳过;任何解析异常视作"无错误"返回 `None`(绝不因解析失败再抛)。
- 富化只在非零退出触发;成功路径(rc==0)行为与字节级输出不变。
- `--yes` 与 `--auto` 可单独或组合使用;`--yes` 不影响讨论轮次推进,`--auto` 不影响门。
- 非 TTY + 无 `--yes` + 交互门:返回码 2 + 明确提示(优于裸 `EOFError` 退 2)。

---

## 7. 测试计划

**`stream_error`(`tests/test_trace.py` 或新建 `tests/test_stream_error.py`)**
- codex `{"type":"error","message":...}` → 返回该 message。
- codex `{"type":"turn.failed","error":{"message":...}}` → 返回该 message。
- claude 含 `is_error`/`error.message` 事件 → 返回其文本(best-effort)。
- 无错误事件 / 全非 JSON / 空 → 返回 `None`。

**backend 富化(`tests/test_cli_backend.py`)**
- 非零退出 + stdout 含 codex 错误事件 + stderr 为噪音 → `AgentError` 文本含**真因**、不含(或不止)stderr 噪音。
- 非零退出 + stdout 无错误事件 → 回退到 stderr 文本。

**`--yes` / 自动门(`tests/test_human_gate*.py` + `tests/test_cli_discuss.py`)**
- `auto_approve_gate` 返回 approve 且**不调用** `input_fn`(传一个会 raise 的 input_fn 断言未被调用)。
- CLI 解析 `--yes`。
- 注入 backend 的 discuss 跑(非 TTY + `--yes`,不注入门)→ 返回 0,全程不读 stdin。
- 非 TTY + 无 `--yes` + 交互门 → 返回 2 且打印含 "--yes" 的提示(不抛裸 EOFError)。

**回归**:全套 `.venv/bin/pytest -q` 绿。

---

## 8. 影响文件清单

| 文件 | 改动 |
|---|---|
| `macr/agents/trace.py` | 新增 `stream_error` |
| `macr/agents/cli_backend.py` | 两个 backend 非零退出分支富化 `AgentError` |
| `macr/human_gate.py` | 新增 `auto_approve_gate` |
| `macr/cli.py` | `discuss` 加 `--yes` + 装配自动门 + 非 TTY 无 `--yes` 的清晰报错 |
| `tests/...` | 上述测试 |
| `docs/roadmap.md` | 勾掉发现 3、发现 7 两条待办 |

后续(不在本次):配额恢复后用 `/tmp/dogfood.sh` 重跑,首次完整验证"讨论→写码→审码→测试绿"真机闭环。
