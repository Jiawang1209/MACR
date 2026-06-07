# V1 一致性优先打磨 — 设计 (2026-06-07)

## 背景

V1 CLI MVP 有三条命令:`run`(单模型 API 闭环)、`collab`(Claude+Codex 异构协作)、
`discuss`(讨论到共识 + Stage D 计划审查门 + 实现)。

真机 dogfood(见 `docs/dogfood-2026-06-07-v1-real-cli.md`)硬化了 **`discuss`**:
非 TTY 守卫、`--yes` 自动门、`stream_error` 错误透传、ConsoleView/TUI。但
**`collab` 和 `run` 没跟上**,共享层也没统一。

## 目标

把 `discuss` 已有的硬化沉到**共享层**,让 `collab`/`run` 自动继承,统一三命令在
CLI 一致性、健壮性、可观测性上的行为;补齐契约测试。全程 TDD,每阶段结束测试全绿。

## 非目标 (YAGNI — 本轮明确排除)

- **瞬时/永久错误分类**(usage-limit vs 超时):现有"优雅 BLOCKED"已够用。
- **`--json` / `--quiet` 机器可读输出**:当前无消费方。
- 不为 `run`/`collab` 造完整 view 对象(避免过度设计);只共享摘要输出。

## 审计清单(代码实点,按轴归类)

**A · CLI 一致性**
- A1 `discuss`/`run` flag 无帮助文字,只有 `collab` 有(`cli.py:37-45` vs `26-31`)
- A2 `run` 写相对 `.macr/runs`,collab/discuss 用 `.resolve()`(`cli.py:62`)
- A3 无 `--version`;`run` 无 `--timeout`
- A4 终端不告诉用户产物落在哪

**B · 健壮性**
- B1 `collab`/`run` 非 TTY 人工门 `input()` 直接 EOF,只有 `discuss` 有守卫(`cli.py:162-168`)
- B2 `collab`/`run` 无 `--yes` 自动门
- B3 空白 `task`、空 `--test-cmd`、负 `--max-*`、不存在的 `--repo` 无校验

**C · 可观测性**
- C1 `run`/`collab` 用裸 `print`,无 view 抽象
- C2 结尾不打印 `.macr/runs/<id>/` 路径

**D · 代码质量与测试**
- D1 `run_discuss` ~150 行深嵌套,Stage-D 审查循环可抽 helper
- D2 `cli.py` 门/控制装配逻辑(`134-168`)可抽 `_resolve_gates`
- D3 `discussion_view.py`(242 行)最大文件,查内聚度
- D4 真机 CLI 契约测试只覆盖 codex argv(发现 5 回归),claude 无契约测试

## 执行策略:一致性优先(已选定)

### Phase 1 — 统一共享层(脊柱)
1. 抽 `_resolve_gates(args, *, interactive_gate, ...)`(cli.py),三命令复用 → D2
2. `collab`/`run` 加 `--yes`(auto_approve_gate)→ B2
3. `collab`/`run` 加非 TTY 守卫(对齐 discuss 的清晰报错退 2)→ B1
4. 给 `discuss`/`run` 所有 flag 补 help 文字 + 默认值 → A1
5. `run` 的 runs_dir 用 `.resolve()` → A2
6. 抽 `print_run_summary`:三命令起手打印 run_id、结尾打印产物路径 → A4 + C2
7. 加 `--version`、`run` 补 `--timeout` → A3

### Phase 2 — 输入校验
8. 校验:`task` 非空白;`--test-cmd` 非空(collab/discuss);`--max-*` 非负;
   `--repo` 存在且是目录。统一 `error:` + 退 2 → B3

### Phase 3 — 可观测性对等
9. `run`/`collab` 复用 `print_run_summary`,起手/收尾摘要与 discuss 一致 → C1 关键部分

### Phase 4 — 重构
10. 从 `run_discuss` 抽 Stage-D 审查循环为 `_plan_review_loop`(对称 `_implementation_loop`)→ D1
11. 查 `discussion_view.py` 内聚度,**有清晰接缝才拆**,否则不动 → D3

### Phase 5 — 契约测试
12. 补 claude argv 契约测试(对称 codex);加"两后端不得出现已删 flag"守卫测试;
    给新增 `--yes`/非 TTY 守卫/输入校验/摘要输出补测试 → D4

## 验收

- 三命令 `--help` 帮助文字风格一致,均有 `--yes`、非 TTY 守卫、`--version`。
- 三命令非 TTY 无 `--yes` 时给清晰错误而非裸 EOF。
- 三命令起手打印 run_id、收尾打印 `.macr/runs/<id>/` 产物路径。
- 输入校验对非法 `task`/`--test-cmd`/`--max-*`/`--repo` 给清晰错误退 2。
- 全套测试绿,新增契约 + 守卫 + CLI 行为测试。
