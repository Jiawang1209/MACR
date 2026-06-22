# Changelog

本文件记录 MACR 的所有显著变更,供人和两个开发 Agent(Claude + Codex)追溯"什么时候加了什么、对应哪个 commit、依据哪份 spec/plan"。

格式参考 [Keep a Changelog](https://keepachangelog.com/),版本语义遵循里程碑(V0→V4,见 `docs/roadmap.md`)。

## 追溯约定(开发硬约束)

**每一次有新功能或实质进展并 commit 后,必须在本文件追加一条记录。** 一条记录应包含:

- **做了什么**:一句话功能描述(对齐 commit message 的意图,不是逐行 diff)。
- **commit 短 hash**:`(abc1234)`;一组相关 commit 可并列 `(abc1234, def5678)`。
- **依据**:对应的 `docs/superpowers/specs/…` 与 `docs/superpowers/plans/…`(若有)。
- **归类**:`Added` / `Changed` / `Fixed` / `Docs` / `Build` / `Refactor`。

新进展先进入 `[Unreleased]`,一个里程碑(plan)完整合入并验收(测试绿)后,归并为一个带日期的版本小节。详细工作流见 `AGENTS.md` / `CLAUDE.md`。

---

## [Unreleased]

> Multi-Agent Term(V3 方向):MACR 控制面 + tmux 运行时 + OSC 7748 观测。设计见
> `docs/superpowers/specs/2026-06-22-multi-agent-term-design.md`,Phase 0 计划见
> `docs/superpowers/plans/2026-06-22-mat-phase0-tmux-runtime.md`。

### Docs
- 新增 WispTerm/CrayBot/tmux 源码借鉴笔记:`docs/wispterm-craybot-源码接口笔记.md`、`docs/tmux集成方案-多Agent终端运行时.md`。
- 新增 Multi-Agent Term 架构设计 spec 与 Phase 0 TDD 计划(见上)。
- 新增本 `CHANGELOG.md` 与开发指南 `AGENTS.md` / `CLAUDE.md`。

### Planned(尚未实现,Phase 0)
- [ ] `macr/runtime/agent_state.py` — `AgentState`/`parse_marker`/`detect`/`aggregate`。
- [ ] `macr/runtime/tmux_control.py` — control mode 帧/事件解析 + 可注入传输。
- [ ] `macr/runtime/tmux_runtime.py` — 一终端多 Agent pane 的 spawn/send/snapshot/list/kill。
- [ ] `macr/runtime/observer.py` — 三路信号融合为 `Detection`。

---

## [V2] — Web 控制台 — 2026-06-08 → 2026-06-12

依据:`specs/2026-06-08-v2-run-viewer-design.md`、`specs/2026-06-08-v2-live-driving-design.md`
及对应 plans。技术栈:FastAPI 后端 + React/Vite/Vitest 前端。245 测试绿。

### Added
- 子项目①只读 Run 查看器:API 模型 `Stage/Artifact/RunSummary/RunDetail` (eef8f0d);run 归一化器(推断命令类型 + collab/discuss 时间线) (2894faa, ec1e102);`list_runs` + `read_artifact`(防路径穿越) (9fa6fba);FastAPI runs list/detail/artifact 端点 (f9fe168);serve 内置 SPA (be3fde8);`macr web` 子命令 (40466b9)。
- 前端查看器:API 客户端 + 类型模型 + 路由壳 (0fdd747);`RunList` (a387288);`RunDetail` + `StageCard` (cf81333);Vite+React+TS+Vitest 脚手架 (98fc742, 9eb2250)。
- 子项目②实时驱动:`RunSession`(事件 buffer + 订阅 + 人工门桥接) (2cf93ac);`RunManager`(单活跃 session,可注入 runner) (53d5e69);orchestrator 接受可注入 `run_id` (66c9d2a);`WebView`(DiscussionView + printer 发事件) (c5b9bc4);web 门 + `start_run` 线程编排(FakeAgentBackend e2e 验证) (566fbaf);`POST /launch` + `GET /active`(409/400) (a366339);WebSocket `/active/ws`(重放 buffer + 流式 + 收门回应) (62c90f8)。
- 前端实时驱动:launch API + live-event 类型 + `/launch` `/live` 路由 (60efc41);`LaunchForm` (c4a1c33);`LiveRun` 流式时间线 + `GatePanel` (7a6fd48)。

### Build
- 新增 `web` extra(fastapi + uvicorn)与 `macr.web` 包 (c0ca566);提交 `package-lock.json` 保证可复现安装 (9eb2250)。

### Docs
- Run 查看器与实时驱动用法,均端到端验证 (78af425, bd83480);README 反映 V2 控制台 + 245 测试 + React/Vite (7998f23);标记 V1 全闭环 dogfood 通过 (256a3c2)。

---

## [V1] — CLI MVP(Claude + Codex 异构协作) — 2026-06-07

依据:Stage A–D 的 specs/plans + 一致性打磨 spec。真机 dogfood 端到端跑通(详见
`docs/dogfood-2026-06-07-*.md`)。

### Added — 基础闭环
- pydantic schemas / `SharedState` (a622839);utils(iso 时间戳 + 顺序 run id) (0761d44);runlog 写产物 + 修订历史 (7e8eb11);LLM 协议 + `FakeLLM` + `AnthropicLLM` tool-use (5102c90);四个 role spec (dcace65);通用 agent runner(一次校验重试) (ac9313e);人工门 approve/reject/edit (369a713);带限次修订的 supervisor 循环 (831fe3e);`macr run` 入口 + 退出码 (ae9deb7)。

### Added — Stage A:Claude+Codex 异构协作
依据 `specs/…stage-a-claude-codex-collab-design.md`。
- git worktree 管理 + diff 捕获 (a6cd0b3);worktree 内 test runner 捕获 `TestResult` (e98d49b);确定性 collab evaluator 门规则 (406e33c);`AgentBackend` 抽象 + process runner + 测试替身 (467e53f);Claude/Codex CLI 后端 (7a7902e);diff/test-aware collab role (79907fa);linear 异构 collab orchestrator (3d3859b);`macr collab` 子命令 (6e533a5)。

### Added — Stage B:原生嵌套子 Agent + tracing
依据 `specs/…stage-b-nested-subagents-design.md`。
- `SubagentRecord` schema + `SharedState.subagents` (208cd5f);防御式子 Agent 流解析 + `TraceSink` (53529a5);后端可选 trace 参数 + 解析失败重试 (114b480);流式 CLI 输出 + 原生子 Agent + trace 捕获 (e6d1ae1);`--no-subagents` flag (a253a18)。

### Added — Stage C:讨论到共识
依据 `specs/…stage-c-discussion-consensus-design.md`、C1/C2 plans。
- `DiscussionTurn`/`ConsensusPlan` schema + 讨论字段 (ce4cf21);讨论 role spec + transcript 渲染 (26f166e);轮边界控制 + 共识人工门 (11ff0c6);`run_discuss` orchestrator(可人工插话) (4cf84f9);`macr discuss` 子命令 (664c4dd);`DiscussionView` 接口(console/silent/fake) (c25142a);rich `TwoPaneView` (4e4b888);`--tui` 双栏视图 (93a0e9a)。

### Added — Stage D:共识后计划审查门
依据 `specs/…stage-d-plan-review-gate-design.md`。
- 确定性 `evaluate_plan` 门 (c367a0f);`DISCUSS_REVIEWER` 角色(Codex 审共识) (deddbcb);review/evaluation 事件入 DiscussionView (5f6876a);把计划审查循环插入 `run_discuss` (bf17ffa);`--max-plan-revisions` (3b3dc64)。

### Changed — V1 一致性打磨
依据 `specs/2026-06-07-v1-consistency-polish-design.md`(204 测试绿)。
- 统一 CLI 共享层;`--yes`/非 TTY guard 回填到 collab+run (8359f6f);三命令统一输入校验 (272650f);起手 announce run_id + 产物目录 (a5aec31);抽出 `_plan_review_loop` (423d29b);pin claude/codex argv 契约测试 (dfa2594)。

### Fixed — 真机 dogfood 修复
- codex `exec` 去掉无效 `--ask-for-approval` (c34da0f);无输入时 child stdin 重定向到 DEVNULL(修 codex 非 TTY 挂死) (06aaf55);从 `--json` 流提取真实 CLI 错误 (4e9714f, ad7bffb);`discuss --yes` 自动门 + 非 TTY 清晰报错 (d6faa8b, e5b5c14)。

---

## [V0] — 文档与协议设计 — 2026-06-06

依据 `specs/2026-06-06-macr-v0-docs-design.md`、`specs/2026-06-06-macr-v1-cli-mvp-design.md`。

### Docs
- 首次提交 (58133be);V0 文档重构设计 spec + 实现计划 (967f167, f9e754b);message protocol(schema/类型/状态/对话规则) (f6deab4);agent roles(7 角色:职责/边界/权限) (f45bdce);workflow templates(3 模式 + V1 最小闭环) (087e3e7);architecture(理念/图/决策/原则) (f7e4273);roadmap(V0–V4/命名/下一步) (9a2012c);双语 README front door (38fe402);原蓝图标记为 source archive (1478811);V1 CLI MVP 设计 spec + 计划 (89f7618, 5e6e7a0);`examples/` 占位 (5f064be)。
- 包脚手架:隔离 venv + pytest (b091d65)。
