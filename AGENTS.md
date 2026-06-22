# AGENTS.md — MACR 开发指南(供 Claude 与 Codex)

> 本文件与 `CLAUDE.md` **内容完全一致**:Codex 读 `AGENTS.md`,Claude 读 `CLAUDE.md`。
> **任何一方有改动,必须同步另一份**(见文末"同步约定")。

## MACR 是什么

MACR(Multi-Agent Collaborative Reasoning Framework)是一套**有纪律的多 Agent 协同协议 + 控制面**:角色分工、独立出方案、辩论到共识、交叉审查、确定性门控、worktree 隔离、人工门、全程落盘可追溯。当前已实现该框架在"软件开发协作"场景下的 CLI MVP(`run`/`collab`/`discuss`)+ Web 控制台(`web`)。详见 `README.md` 与 `docs/roadmap.md`。

下一步方向(V3,Multi-Agent Term):MACR 控制面 + tmux 运行时 + OSC 7748 观测,让一个终端里跑多个可观测 Agent。设计见 `docs/superpowers/specs/2026-06-22-multi-agent-term-design.md`。

## 双 Agent 模型(你们俩怎么分工)

- **Claude**:规划、汇总共识、审查方案(Stage D)、审码(review diff)。出方案的一方不审自己的方案。
- **Codex**:在隔离 git worktree 里执行(写文件、跑测试)、独立审查共识方案。
- **人工门**:派发前、最终合并前由人 approve/reject/edit。
- **确定性门控**:PASS/NEEDS_FIX/BLOCKED 由规则判定,**不靠模型投票**。

## 仓库布局

```
macr/            核心包(Python，~3100 行)
  cli.py         命令分发(run/collab/discuss/web)
  agents/        backend 抽象(base.py)、CLI 后端(cli_backend.py)、API 后端、trace
  discussion*.py discuss 编排、轮控制、视图
  collab_*.py    collab 编排、角色、evaluator
  roles.py schemas.py runlog.py testrunner.py worktree.py human_gate.py utils.py
  web/           FastAPI 后端(app/session/live/runs/models)
  runtime/       【V3 新增】tmux 运行时 + OSC 观测(见设计 spec)
frontend/        React + Vite + Vitest(Web 控制台 SPA)
tests/           pytest（与 macr/ 对应；全部用 fake，不依赖网络/CLI）
docs/            架构、协议、roadmap、dogfood 报告、源码借鉴笔记
  superpowers/   specs/(设计) + plans/(TDD 实现计划)
.macr/runs/      运行产物(transcript/共识/审查/决策/测试日志，可回放)
CHANGELOG.md     历史追溯（见下，硬约束）
AGENTS.md CLAUDE.md  本指南
```

## 开发工作流:spec → plan → TDD

MACR 一切功能都走这条线,**不要跳步**:

1. **spec**:在 `docs/superpowers/specs/<date>-<name>-design.md` 写设计。固定结构:背景 / 目标 / 范围 / 非目标(YAGNI)/ 执行模型(方案选择 + 被否决备选)/ 架构 / 组件 / 协议 / 错误处理与生命周期 / 测试策略(TDD)/ 验收。
2. **plan**:在 `docs/superpowers/plans/<date>-<name>.md` 写实现计划。拆成 Phase → Task,每个 Task 五步:① 写失败测试 ② 跑红(贴预期报错)③ 写最小实现 ④ 跑绿 ⑤ commit。末尾 Self-Review(spec 覆盖 + 接口一致性 + 占位扫描)。
3. **TDD 执行**:严格红→绿→commit,一个 Task 一个(或一组)commit。
4. **更新 CHANGELOG**(硬约束,见下)。

参考已完成的范例:`specs/2026-08-…` 系列、`plans/2026-06-08-v2-live-driving.md`。

## 历史追溯(硬约束)⚠️

**每一次有新功能或实质进展并 commit 后,必须在 `CHANGELOG.md` 追加一条记录。** 一条记录含:

- 做了什么(一句话,对齐 commit 意图)
- commit 短 hash:`(abc1234)`,一组相关 commit 可并列
- 依据的 spec/plan 路径(若有)
- 归类:`Added` / `Changed` / `Fixed` / `Docs` / `Build` / `Refactor`

新进展先进 `[Unreleased]`;一个 plan 完整合入并测试绿后,归并为带日期的版本小节。**没有 CHANGELOG 记录的功能提交视为不完整。** 拿短 hash:`git rev-parse --short HEAD`。

## 环境与命令(项目专属 venv,不污染基础环境)

```bash
python3 -m venv .venv                  # 需要 Python >= 3.11
.venv/bin/pip install -e ".[dev]"      # 加 web:".[dev,web]"
.venv/bin/pytest                       # 全套后端测试(纯本地，无需网络/CLI)
.venv/bin/python -m pytest tests/test_xxx.py -q   # 单文件

cd frontend && npm install && npm test # 前端 Vitest
cd frontend && npm run build           # tsc -b + Vite 构建
```

入口:`.venv/bin/macr <run|collab|discuss|web>`(见 `pyproject.toml [project.scripts]`)。

## 编码与提交规范

- **测试用 fake,不碰真网络/真 CLI**:沿用 `FakeLLM`、`FakeAgentBackend`、`FakeProcessRunner`(`macr/agents/base.py`),新组件提供同款可注入测试替身(如 V3 的 `FakeTmuxTransport`)。
- **可注入接缝**:用 Protocol(`ProcessRunner`/`AgentBackend`/`DiscussionView`/`TmuxTransport`),真实现 + 假实现并存。
- **不臆造**:CLI 失败要从 `--json` 流提取真因;状态分层 `observed/reported`(观测)≠ `verified`(Stage D 门 + 测试转绿)≠ `approved`(人工门)。屏幕/进程信号最多到 observed,不得当验收。
- **注入安全**:prompt/参数永远作为独立 argv,绝不经 shell 拼接(见 argv 契约测试)。
- **Commit message**:Conventional Commits,跟现有历史一致:`feat(scope): …` / `fix: …` / `docs: …` / `refactor: …` / `build: …` / `test: …` / `chore: …`。一个 Task 一个聚焦 commit。
- **worktree 隔离**:写入型执行在 `.macr/worktrees/<run_id>/`;approve 后保留供人工 merge。

## 当前状态与下一步

- 已完成:V0(文档/协议)、V1(CLI MVP,Stage A–D + 一致性打磨)、V2(Web 控制台)。245 后端测试 + 前端 Vitest。真机端到端跑通过一次(`docs/dogfood-2026-06-07-*.md`)。
- 进行中:V3 Multi-Agent Term。先做 Phase 0(`macr/runtime/`,见 `plans/2026-06-22-mat-phase0-tmux-runtime.md`),只做运行时 + 观测层,不改 orchestrator。
- 详细历史见 `CHANGELOG.md`。

## 同步约定

`AGENTS.md` 与 `CLAUDE.md` 必须逐字一致。改其一时,同一个 commit 内改另一份;可用 `diff AGENTS.md CLAUDE.md` 自检(应无输出)。
