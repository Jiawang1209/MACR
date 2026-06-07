# MACR V1 真机 Dogfood 报告 — 2026-06-07

> 目的:首次用**真实** `claude` + `codex` CLI 端到端跑 `macr discuss`(含 Stage D 计划审查门),验证截至 Stage D 的 V1 CLI 在真机上的行为。此前所有 172 个测试都用 `FakeAgentBackend`,从未真机跑过。
>
> 结论:dogfood 抓到 **2 个真机必挂的 MACR bug**(已修复并提交),其中 1 个还被一条**断言错误契约的单元测试**掩护着;另发现 **1 个错误可观测性缺陷** + 几条次要项。Stage D 的优雅降级在真实 codex 失败下**两次**验证通过。codex 路径的完整闭环验证因**账号用量限制**(外部因素,约 20:00 恢复)未能在本轮跑满。

---

## 1. 环境

| 项 | 值 |
|---|---|
| 日期 | 2026-06-07 |
| `claude` CLI | 2.1.168 (Claude Code) |
| `codex` CLI | codex-cli 0.137.0 |
| 平台 | macOS (darwin 25.3.0) |
| 被测命令 | `macr discuss`(`--max-rounds 1 --max-plan-revisions 1 --no-subagents`) |
| 靶子 | `/tmp/macr-dogfood`(零依赖小仓库:`mymod.py` 空壳 + `check.py` 断言 `hello()=='hello'`) |
| 任务 | "在 mymod.py 中添加一个函数 hello(),返回字符串 'hello'" |

## 2. 方法

1. 先用 `printf 'a\na\n' | macr discuss ... --auto` 真机跑(发现 1/2/3)。
2. 因 headless 人工门 + codex 抢 stdin 不可靠,改用**程序化 approve-gate 的 Python harness**(`/tmp/dogfood_run.py`)直接驱动真实后端,以验证完整路径含 codex executor。
3. 逐个修复 → 重跑 → 直至定位到外部用量限制。

---

## 3. 发现汇总

| # | 发现 | 严重度 | 状态 |
|---|---|---|---|
| 1 | `codex exec` 不接受 `--ask-for-approval`,所有 codex 调用直接挂 | 🔴 致命 | **已修** `c34da0f` |
| 2 | Stage D 审查门优雅降级真机通过(codex 挂 → BLOCKED → 仍达人工门) | 🟢 正面 | 验证通过 |
| 3 | headless 下人工门 `input()` EOF;`--auto` 不自动过人工门;子进程抢 stdin | 🟡 中 | 已记录(未修,设计待定) |
| 4 | claude 集成健康(plan + consensus 真机产出正常) | 🟢 正面 | 验证通过 |
| 5 | 单元测试 `test_cli_backend.py:99` 固化了**错误**的 codex argv 契约,是 #1 的漏网主因 | 🔴 流程 | **已修** `c34da0f` |
| 6 | `SubprocessRunner` 继承父进程 stdin,非 TTY 下 `codex exec` 卡在 "Reading additional input from stdin" 退 1 | 🔴 致命 | **已修** `06aaf55` |
| 7 | `AgentError` 只透传 stderr;真实错误(如 usage limit)在 `--json` 的 stdout 流里,被掩盖 | 🟡 中(可观测性) | 已记录(未修) |
| 8 | 重跑时确定性 run_id + 源仓库残留 worktree 注册导致 `worktree add` 冲突 | 🟢 次要 | 重跑脚本已规避 |

---

## 4. 逐条详情

### 🔴 发现 1 — `codex exec` 不认 `--ask-for-approval`(已修)

**症状**:每次 codex 调用 `[discussion blocked] / [plan review blocked] codex CLI exited 2: error: unexpected argument '--ask-for-approval' found`。

**根因**:`CodexCliBackend` 拼出 `codex exec ... --ask-for-approval never ...`。codex 0.137.0 的 `exec` 子命令是非交互式、**没有审批 flag**(`--ask-for-approval` 是顶层 `codex` 的 flag,不是 `exec` 的);写沙箱由 `-s/--sandbox` 决定。代码是对着旧版 codex 写的。

**影响面**:codex planner、codex turn、**Stage D 的 Codex 审查门**、实现循环的 codex executor —— 全部 codex 角色。真实异构协作完全断。

**修复**(`c34da0f`,`macr/agents/cli_backend.py`):argv 去掉 `--ask-for-approval, self.approval`,并删除已死的 `approval` 构造参数/属性。`codex exec` 仍传 `-C/--cd`、`-s/--sandbox`、`--json`(均经 `codex exec --help` 确认有效)。

### 🟢 发现 2 — Stage D 优雅降级真机验证通过

codex 审查调用失败 → `[plan review blocked]` → `evaluate_plan(None)` → `BLOCKED` → 审查循环跳出 → 仍走到 `consensus_gate`,最终 approve。与设计/单测完全一致。**在两次不同的 codex 失败下都复现了这一正确行为**,说明 Stage D 的错误边界在真机下稳。

### 🟡 发现 3 — headless 人工门不可自动化

`--auto` 只让讨论**轮次边界**自动 continue,**不自动过人工门**;`consensus_human_gate`/`collab_human_gate` 仍调 `input()`。非 TTY 下读 stdin 得到 `EOF when reading a line` → 异常 → 退出码 2。

复杂化因素:`codex exec` 会把**管道 stdin 当作 `<stdin>` 块追加到 prompt**,所以"管道喂审批答案"既污染 codex prompt、又不可靠。

**结论**:真正的无人值守需要一个 auto-approve 门(如 `--yes`,或让 `--auto` 同时自动过门),而非靠管道 stdin。本轮用程序化 gate 的 harness 绕过以继续验证。**未修,留作设计决定。**

### 🟢 发现 4 — claude 集成健康

claude planner 真机产出了结构化计划;claude consensus 真机产出了共识方案。claude 侧路径无问题。

### 🔴 发现 5 — 单元测试固化了错误契约(已随 #1 修)

`tests/test_cli_backend.py:99` 断言 `"--ask-for-approval" in argv` —— 即测试**主动验证了那个会让真机挂掉的错误 argv**。fake 后端 + 这条断言一起,让 #1 在 172 个绿测试里完全隐身。

**教训**:对"外部 CLI 契约"这类边界,fake 测试只能验证"我们以为的契约",无法验证"真实工具的契约"。需要真机 dogfood(或针对 CLI 版本的契约测试)兜底。

**修复**(`c34da0f`):断言改为 `"--ask-for-approval" not in argv`,并加注释说明这是 dogfood 回归。

### 🔴 发现 6 — 子进程继承 stdin 导致 codex 卡死退 1(已修)

**症状**(修了 #1 之后才暴露):`codex CLI exited 1: Reading additional input from stdin...`。

**根因**:`SubprocessRunner.run` 用 `subprocess.run(..., input=None)`,当无输入时 stdin **继承自父进程**。非 TTY 运行(后台/harness)下,`codex exec` 看到一个非 /dev/null 的 stdin 就尝试读 `<stdin>` 块。

**澄清**:`"Reading additional input from stdin..."` 本身只是 codex 打到 stderr 的**信息行**,codex 会继续(后面有 `thread.started`/`turn.started`)。它退 1 的真因见发现 7。但把子进程 stdin 接到 DEVNULL 仍是正确且必要的(避免继承父 stdin、避免管道污染)。

**修复**(`06aaf55`,`macr/agents/base.py`):无 `input_text` 时传 `stdin=subprocess.DEVNULL`。

### 🟡 发现 7 — 错误透传掩盖真因(未修)

`codex exec --json` 把真实错误放在 **stdout 的 JSONL 流**里:

```json
{"type":"turn.failed","error":{"message":"You've hit your usage limit. ... try again at 8:00 PM."}}
```

而 `CodexCliBackend` 在非零退出时抛 `AgentError(f"codex CLI exited {rc}: {stderr.strip()}")`,只取 **stderr**(此处恰是无害的 "Reading additional input from stdin...")。于是用户看到误导信息,真因(用量限制)被吞。**这正是本次诊断要跑三遍才定位的原因。**

**建议**(后续):非零退出时,优先从已解析的 `--json` 流里提取 `error`/`turn.failed` 的 message 作为 `AgentError` 文本,stderr 仅作兜底。claude 侧同理(`parse_claude_stream` 应能拿到流内错误)。

### 🟢 发现 8 — 重跑的 worktree 注册冲突(脚本已规避)

run_id 按"日期+计数"确定性生成;`rm -rf` 输出目录不会清掉**源仓库**里的 git worktree 注册,导致同路径 `worktree add` 报 `missing but already registered`。重跑脚本 `/tmp/dogfood.sh` 已在每次运行前 `git worktree prune` 且使用带时间戳的全新输出目录规避。

---

## 5. 已验证 / 未决

**已验证(真机)**
- claude 全路径(planner / consensus)产出正常。
- Stage D 审查门在 codex 失败下的优雅降级(BLOCKED → 仍达门),两次复现。
- 两个修复(#1 flag、#6 stdin)经全套测试绿 + 真机不再报对应错误。

**未决**
- **codex executor 完整闭环**(真写文件 → `check.py` 转绿 → 最终 approve):因账号用量限制(约 20:00 恢复)本轮未跑满。待 codex 恢复后用 `/tmp/dogfood.sh` 重跑确认。
- 发现 3(headless auto-gate)与发现 7(错误透传)留作后续。

## 6. 重跑方法(codex 配额恢复后)

```bash
# 幂等:自动 prune stale worktree + 每次用全新输出目录
/tmp/dogfood.sh
```

预期:codex 不再 BLOCKED → worktree 内 `mymod.py` 出现 `hello()` → `TEST RESULT` 显示 `passed=True` → `FINAL DECISION: approve`。

辅助文件(本机临时):`/tmp/dogfood.sh`(wrapper)、`/tmp/dogfood_run.py`(程序化 gate 的真机 harness)、`/tmp/macr-dogfood`(靶子仓库)。

## 7. 相关提交

- `c34da0f` fix: drop invalid --ask-for-approval from codex exec invocation(含 #1 + #5)
- `06aaf55` fix: redirect child stdin to DEVNULL when no input (codex exec non-TTY hang)(#6)
