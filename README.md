# MACR — Multi-Agent Collaborative Reasoning Framework

MACR 是一个通用多智能体协同推理框架,让多个 Agent 围绕同一个复杂任务进行分工、讨论、互审、迭代、执行、评估和最终决策。

A general-purpose framework for multi-agent collaborative reasoning, structured dialogue, cross-review, iterative execution, and human-in-the-loop decision workflows.

---

## 核心思想 / Core Idea

多智能体协作不是"多个 AI 随意聊天",而是结构化协同:通过明确角色、统一消息协议、共享状态黑板、任务编排引擎、交叉审查机制和人工门控节点,将复杂任务分解为可追踪、可审计、可迭代的协作流程。

Multi-agent collaboration is not "multiple AIs chatting freely" — it is structured coordination.

```text
结构化消息 + 明确角色 + 共享状态 + 任务编排 + 交叉审查 + 人工门控
```

---

## 架构 / Architecture

```text
                ┌─────────────┐
                │  用户 / Task │
                └──────┬──────┘
                       ▼
                ┌─────────────┐        路由 / 编排
                │  Supervisor  │◄───────────────────────┐
                └──────┬──────┘                          │
                       │ 调度                             │
   ┌─────────┬─────────┼─────────┬──────────┐            │
   ▼         ▼         ▼         ▼          ▼            │
┌──────┐ ┌──────┐ ┌────────┐ ┌────────┐ ┌──────┐        │
│Planner│ │Execu-│ │Reviewer│ │Evalua- │ │Tester│        │
│       │ │ tor  │ │        │ │ tor    │ │      │        │
└───┬──┘ └───┬──┘ └────┬───┘ └────┬───┘ └───┬──┘        │
    │        │         │          │         │            │
    └────────┴─────────┴────┬─────┴─────────┘            │
                            ▼                            │
                  ┌───────────────────┐  读/写            │
                  │  Blackboard /      │──────────────────┘
                  │  Shared State      │
                  └─────────┬─────────┘
                            ▼ PASS
                     ┌────────────┐
                     │ Human Gate │ → Final Output
                     └────────────┘
```

详细架构见 [`docs/architecture.md`](docs/architecture.md)。

---

## 核心角色 / Roles

| 角色 Role | 职责 Responsibility |
|---|---|
| Supervisor / Orchestrator | 流程控制与协同调度,维护全局状态 |
| Planner | 生成方案、拆解步骤、标记风险 |
| Executor / Implementer | 按方案执行,产出结果与证据 |
| Reviewer | 审查方案与结果,给出修改建议 |
| Evaluator | 判断是否合格,输出 PASS / NEEDS_FIX / BLOCKED |
| Tester | 运行测试、验证边界、输出测试日志 |
| Human Gate | 关键决策最终确认,最终责任主体 |

详见 [`docs/agent_roles.md`](docs/agent_roles.md)。

---

## 消息协议 / Message Protocol

每个 Agent 输出遵循统一消息结构,包含 task_id / run_id / role / message_type / content / references / decision / confidence 等字段,确保所有 Agent 之间的交互可追踪、可审计、可重放。

```json
{
  "task_id": "T123",
  "run_id": "R20260606_001",
  "agent_id": "claude_reviewer",
  "role": "reviewer",
  "message_type": "review",
  "content": {
    "summary": "Codex 的实现基本符合 consensus,但缺少边界条件测试。",
    "decision": "needs_fix",
    "confidence": 0.86
  },
  "references": ["consensus.md", "diff.patch", "test.log"],
  "status": "submitted"
}
```

完整字段、消息类型与对话协议见 [`docs/message_protocol.md`](docs/message_protocol.md)。

---

## 最小工作流 / Minimal Workflow

```text
Task → Supervisor 拆解 → Planner → Executor → Reviewer → Evaluator(PASS/NEEDS_FIX/BLOCKED) → Human Gate → Final Output
```

三种工作流模式见 [`docs/workflow_templates.md`](docs/workflow_templates.md)。

---

## 技术栈 / Tech Stack

| 层级 Layer | 技术 Tech |
|---|---|
| Agent 编排 | LangGraph |
| 后端 | FastAPI |
| 前端 | Next.js + React + Tailwind |
| 数据库 | PostgreSQL |
| 向量检索 | pgvector |
| 队列/缓存 | Redis |
| 文件存储 | 本地文件系统 / MinIO |
| 模型调用 | LiteLLM / OpenAI SDK / Anthropic SDK |
| 部署 | Docker Compose |

---

## 路线图 / Roadmap

- **V0** — 文档与协议 / Documentation & Protocol
- **V1** — CLI MVP
- **V2** — Web 控制台 / Web Console
- **V3** — 插件化 / Plugin System
- **V4** — 应用衍生 / Application Variants

详见 [`docs/roadmap.md`](docs/roadmap.md)。

---

## 目录导航 / Repo Layout

- [`docs/architecture.md`](docs/architecture.md) — 架构、设计哲学、原则
- [`docs/message_protocol.md`](docs/message_protocol.md) — 消息与状态协议
- [`docs/agent_roles.md`](docs/agent_roles.md) — 7 个 Agent 角色
- [`docs/workflow_templates.md`](docs/workflow_templates.md) — 工作流模式
- [`docs/roadmap.md`](docs/roadmap.md) — 路线图
- [`examples/`](examples/) — 应用示例(占位)

---

## 运行 CLI MVP (V1) / Running the CLI MVP

> 仅在项目专属虚拟环境中运行,不污染基础环境 / Project-local venv only.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 跑测试 / run tests (no network)
.venv/bin/pytest

# 真实运行一条任务 / run a real task (needs an API key)
export ANTHROPIC_API_KEY=sk-...
.venv/bin/macr run "写一个判断回文的 Python 函数"
```

产物写入 `.macr/runs/<run_id>/`:`input.md` / `planner.output.md` / `executor.output.md` / `reviewer.output.md` / `evaluator.output.json` / `state.json` / `final.md`。

---

## Claude⟷Codex 异构协作 (Stage A) / Heterogeneous collaboration

> 纯 CLI,不需要 API key。需 `claude` 与 `codex` 已安装并登录 / CLI-only, no API key; requires `claude` and `codex` on PATH.

```bash
# Claude 出方案/审 diff,Codex 在隔离 worktree 改代码,框架跑测试
.venv/bin/macr collab "为模块加一个 hello() 函数" \
    --repo /path/to/target-repo \
    --test-cmd "pytest -q"
```

流程:Claude Planner → Codex 在 `.macr/worktrees/<run_id>/` 改代码 → 框架跑 `--test-cmd` → Claude 审 diff+测试 → 规则判定 → 返工(≤ `--max-revisions`)→ Human Gate(approve/reject/edit)。产物在 `.macr/runs/<run_id>/`(含 `diff.vN.patch`、`test.vN.json`、`final.md`)。approve 后 worktree 保留供你手动 merge。

### 嵌套 subagent (Stage B) / Nested subagents

`macr collab` 默认允许 Claude(`Agent` 工具)与 Codex(`multi_agent`)使用各自的**原生 subagent**;用 `--no-subagents` 关闭。每个角色调用的原始事件流与 subagent 摘要落在 `.macr/runs/<run_id>/subagents/`。解析器为防御式,真实事件 schema 校准见 `docs/superpowers/STAGE_B_CALIBRATION.md`。
