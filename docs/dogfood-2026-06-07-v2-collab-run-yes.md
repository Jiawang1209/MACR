# MACR Dogfood 报告 v2 — collab/run `--yes` 无人值守路径(2026-06-07)

> 目的:用**真实** `claude` + `codex` CLI 端到端跑刚打磨完的 `collab --yes` 与 `run --yes`
> 无人值守路径(V1 一致性打磨 Phase 1 把 `--yes` 自动门 + 非 TTY 守卫回填到了 collab/run)。
> 这次比 v1 dogfood 干净:当时 `--yes` 还不存在要写 Python harness,现在直接一条
> `macr collab … --yes` 在非 TTY 后台就能跑 —— **这本身就验证了打磨成果**。

---

## 1. 环境
| 项 | 值 |
|---|---|
| 日期 | 2026-06-07 23:18 |
| `claude` / `codex` | 同 v1(2.1.168 / codex-cli 0.137.0) |
| 平台 | macOS (darwin 25.3.0) |
| collab 靶子 | `/tmp/macr-dogfood-collab`(`mymod.py` 空壳 + `check.py` 断言 `add(2,3)==5` 且 `add(-1,1)==0`) |
| 命令 | `macr collab "…add(a,b)…" --repo … --test-cmd "python check.py" --yes --no-subagents --max-revisions 1`(非 TTY 后台) |

## 2. 结果汇总
| # | 项 | 结果 |
|---|---|---|
| 1 | `collab --yes` 端到端闭环(真异构) | 🟢 **通过**,退出码 0 |
| 2 | `--yes` 自动门(Phase 1)在非 TTY 真机生效 | 🟢 `[auto-approve] gate passed without prompting (--yes)` |
| 3 | 非 TTY 守卫**未**误触(因给了 `--yes`) | 🟢 全程无 EOF |
| 4 | 起手/收尾产物 banner(Phase 1/3) | 🟢 起手 `[run R…] artifacts → …`,收尾 `产物 / artifacts: …/` |
| 5 | codex executor 真写文件(workspace-write) | 🟢 worktree `mymod.py` 出现 `def add(a, b): return a + b` |
| 6 | `check.py` 转绿 | 🟢 `test.v1.json` `passed=true, exit_code=0, log="OK"` |
| 7 | claude reviewer / evaluator | 🟢 `approve` / `PASS` |
| 8 | `run --yes` 接线(无 API key 上限) | 🟡 见发现 B |
| 9 | **worktree diff 被工具副作用文件污染** | 🔴→🟢 见发现 A(**已修 + 真机验证**) |

## 3. 发现详情

### 🔴 发现 A — `Worktree.diff()` 的 `git add -A` 把工具副作用文件卷进 diff
**症状**:`diff.v1.patch` 含 3 个文件 —— `mymod.py`(任务真改动)+ `.omc/project-memory.json`
+ `.omc/sessions/<id>.json`(后两者是 oh-my-claudecode 工具在 codex 子进程里运行时写进
worktree 的副作用文件)。

**根因**:`macr/worktree.py:47-49` 的 `diff()` 先 `git add -A`(无差别 stage **所有**未跟踪
文件)再 `git diff --cached`。于是任何在 worktree 里运行期间落文件的工具(OMC 钩子、
`__pycache__`、编辑器临时文件)都会被 stage 进 diff。

**影响面**:该 diff 会 ① 展示给人工门 ② 作为"产物"喂给 claude reviewer 审 ③ 落进
`final.md`。污染降低 diff 保真度、给 reviewer 引入噪声。`collab` 与 `discuss` 共用
`_implementation_loop → worktree.diff()`,**两条路径都受影响**。

**说明**:`.omc/` 是本机 OMC 插件钩子写的;干净部署不会有这些具体文件。但底层
fragility(`git add -A` 太激进)是普适的 —— 任何写 CWD 的工具都会污染 diff。
`__pycache__` 这次未进 diff,仅因它由 `check.py`(测试)生成,而测试在 diff 捕获之后才跑。

**修复(已落实,`macr/worktree.py`)**:采用 pathspec 排除(候选 a)。`diff()` 仍 `git add -A`,
但 `git diff --cached -- . <excludes>` 排除 `.omc/`、`**/__pycache__/`、`**/*.pyc`,保留合法
新文件与改动。`_DIFF_EXCLUDES` 常量便于扩展。collab+discuss 同步受益。

**真机验证**:同条件重跑 `collab --yes`,worktree 里**仍真实写入 `.omc/`**(污染源真实存在),
但 `diff.v1.patch` 现在**只含 `mymod.py`**(`.omc` 出现 0 次),完整路径仍全绿(approve / 退 0)。
单测 `test_diff_excludes_tooling_and_cache_noise` 覆盖该场景。

### 🟡 发现 B — `run --yes` 接线已验证,完整 API 闭环受 key 阻塞
本机未设 `ANTHROPIC_API_KEY`,`run`(单模型 API 路径)无法跑完整 planner→executor→
reviewer→evaluator→auto-approve。已用**对照**验证 `--yes` 接线正确:
- 非 TTY + `--yes`:绕过守卫 → 进到 API key 检查 → `error: ANTHROPIC_API_KEY is not set`(退 2);
- 非 TTY 无 `--yes`:守卫触发,`error: 非交互环境…需要 --yes…`(退 2)。
即 `--yes` 把门解析成了 `auto_approve_gate`,守卫正确不触发。完整闭环待有 key 后补跑。

## 4. 已验证 / 未决
**已验证(真机)**:`collab --yes` 全闭环;`--yes` 自动门 + 非 TTY 守卫 + 起手/收尾 banner
在真机异构运行下全部生效;codex 真写文件、测试转绿、approve、退 0、产物齐全。
**已修复**:发现 A(diff 污染)—— pathspec 排除,单测 + 真机重跑双重验证。
**未决**:发现 B 的 run 完整 API 闭环(待 `ANTHROPIC_API_KEY`)。
