# MACR：Multi-Agent Collaborative Reasoning Framework

> 📦 来源存档 / Source archive — 本文件是 MACR 的原始设计蓝图。结构化文档见 [README.md](README.md) 与 [`docs/`](docs/)。

> 多智能体协同推理框架设计笔记  
> 整理时间：2026-06-06  
> 目标：作为后续开发 MACR 框架的项目蓝图与 GitHub 初始文档

---

## 1. 项目定位

MACR，全称 **Multi-Agent Collaborative Reasoning Framework**，中文可称为：

> **多智能体协同推理框架**

它不是某一个具体应用系统，而是一个面向复杂任务的通用智能体协作底座。

MACR 的核心目标是：

```text
让多个智能体围绕同一个复杂任务进行分工、讨论、互审、迭代、执行、评估和最终决策。
```

它关注的不是单个大模型能力，而是：

- 多 Agent 如何协同；
- Agent 之间如何交换信息；
- 如何形成结构化讨论；
- 如何让一个 Agent 审查另一个 Agent；
- 如何实现方案生成、执行、审查、测试、返工和最终确认；
- 如何保证全过程可追踪、可复现、可人工干预。

---

## 2. MACR 与具体应用系统的关系

本次讨论中逐渐明确了一个重要判断：

> **“多智能体协同推理框架” 与 “农田生态保育决策系统 / 科研论文智能辅助系统” 可以是并列项目。**

更准确地说：

```text
MACR = 通用多智能体协同推理底座
农田生态保育决策系统 = 基于 MACR 的领域应用
科研论文智能辅助系统 = 基于 MACR 的科研应用
软件开发协作系统 = 基于 MACR 的工程应用
```

因此，MACR 不应写死任何一个具体领域，例如：

- 不应只绑定农田生态保育；
- 不应只绑定科研论文写作；
- 不应只绑定 Claude Code / Codex 协作；
- 不应只绑定某个数据库或知识图谱。

MACR 应抽象为一套通用机制：

```text
Agent
Role
Task
State
Message
Tool
Evidence
Review
Decision
Feedback
Workflow
Human Gate
```

具体应用系统只是在 MACR 之上配置不同的 Agent、工具、规则和工作流。

---

## 3. 核心思想：不是自由聊天，而是结构化协同

多智能体协作不应理解为“多个 AI 在一起随意聊天”。

更合理的理解是：

> **结构化消息 + 明确角色 + 共享状态 + 任务编排 + 交叉审查 + 人工门控。**

自由聊天容易产生以下问题：

- Agent 之间互相迎合；
- 讨论看起来热闹，但没有有效结论；
- 任务边界模糊；
- 责任不清；
- 中间过程不可追溯；
- 输出无法验证；
- 容易出现幻觉和过度推断。

因此，MACR 的核心不是“让 Agent 聊天”，而是建立一套可控的协同推理协议。

---

## 4. MACR 的基础角色模型

MACR 可以从以下基础角色开始设计。

### 4.1 Supervisor / Orchestrator Agent

中枢调度智能体。

职责：

- 接收用户任务；
- 判断任务类型；
- 拆解任务；
- 决定调用哪些 Agent；
- 控制 Agent 的执行顺序；
- 维护全局状态；
- 触发审查、返工或人工审核；
- 生成最终输出。

Supervisor 不一定负责专业判断，而是负责流程控制和协同调度。

---

### 4.2 Planner Agent

规划智能体。

职责：

- 生成初步方案；
- 拆解任务步骤；
- 判断所需工具和数据；
- 给出执行路线；
- 标记潜在风险。

在 Claude Code / Codex 协作场景中，Claude 可以偏向 Planner / Architect。

---

### 4.3 Executor / Implementer Agent

执行智能体。

职责：

- 根据明确方案执行任务；
- 生成代码、分析结果、报告、图表或其他产物；
- 记录执行过程；
- 输出修改文件、工具调用、测试结果等证据。

在代码开发场景中，Codex 可以偏向 Executor / Implementer。

---

### 4.4 Reviewer Agent

审查智能体。

职责：

- 审查 Planner 的方案；
- 审查 Executor 的结果；
- 检查逻辑错误；
- 检查任务是否偏离目标；
- 检查结果是否缺少证据；
- 给出修改建议。

Reviewer 的定位不是重新执行任务，而是质量控制。

---

### 4.5 Evaluator Agent

评估智能体。

职责：

- 根据规则、证据、测试结果和评价指标判断输出是否合格；
- 判断是否需要返工；
- 判断是否需要人工审核；
- 输出 PASS / NEEDS_FIX / BLOCKED 等状态。

Evaluator 是 MACR 中非常关键的质量门控角色。

---

### 4.6 Tester Agent

测试智能体。

职责：

- 运行测试；
- 设计测试用例；
- 验证边界条件；
- 检查结果是否可复现；
- 输出测试日志。

在软件开发场景中，Claude 可以担任 Reviewer + Tester；Codex 负责实现与修复。

---

### 4.7 Human Gate

人工门控。

职责：

- 对关键决策进行最终确认；
- 接收系统输出；
- 修改、批准或驳回结果；
- 将人工反馈写回系统；
- 作为最终责任主体。

MACR 不应该追求完全自动化，而应该强调：

```text
AI 负责提出、执行、审查和验证；人负责最终判断。
```

---

## 5. Claude Code + Codex 协作作为 MACR 的早期验证场景

本次讨论最早从 Claude Code 和 Codex CLI 的多智能体协作开始。

目标是：

```text
Claude 负责方案设计、代码审查和测试；
Codex 负责代码实现和修复；
两者通过回合制互审和返工形成协作闭环。
```

推荐流程：

```text
需求输入
  ↓
Claude 生成方案
  ↓
Codex 生成备选方案
  ↓
Claude 审查 Codex 方案
  ↓
Codex 审查 Claude 方案
  ↓
Claude 汇总 consensus.md
  ↓
Codex 根据 consensus.md 实现代码
  ↓
Claude 审查 git diff
  ↓
Codex 根据 review 修复
  ↓
Claude 最终测试
  ↓
人类确认并 merge
```

这个流程可以作为 MACR 的第一个 MVP 验证场景。

---

## 6. tmux、git worktree 与多 Agent 本地协作

为了同时运行多个 Claude Code / Codex CLI，可以使用：

```text
tmux + git worktree
```

### 6.1 tmux 的作用

- 在一个终端中运行多个 pane/window；
- 让多个 CLI Agent 同时运行；
- 支持长任务和后台 session；
- 可通过 send-keys / capture-pane 实现简单输入输出控制。

但 tmux 本身不是多智能体框架，它只是运行容器。

### 6.2 git worktree 的作用

- 为每个 Agent 分配独立工作目录；
- 避免多个 Agent 同时修改同一份代码；
- 支持并行分支开发；
- 最后通过 review / merge 进行整合。

推荐结构：

```text
repo/
  main/
  .worktrees/
    claude-plan/
    codex-impl/
    claude-review/
    integration/
```

---

## 7. 智能体之间的“对话桥梁”设计

这是 MACR 的核心问题之一。

### 7.1 核心判断

智能体之间的桥梁不应是自由文本聊天，而应是：

```text
统一消息结构 + 共享状态 / Blackboard + Supervisor 路由 + 协议约束
```

---

### 7.2 Message Schema：统一消息结构

每个 Agent 输出都应符合统一消息格式。

示例：

```json
{
  "task_id": "T123",
  "run_id": "R20260606_001",
  "agent_id": "claude_reviewer",
  "role": "reviewer",
  "message_type": "review",
  "content": {
    "summary": "Codex 的实现基本符合 consensus，但缺少边界条件测试。",
    "findings": [
      {
        "level": "blocking",
        "issue": "缺少异常输入处理",
        "evidence": "src/api/user.ts:45",
        "recommendation": "增加 null input 检查"
      }
    ],
    "decision": "needs_fix",
    "confidence": 0.86
  },
  "references": [
    "consensus.md",
    "diff.patch",
    "test.log"
  ],
  "timestamp": "2026-06-06T10:00:00Z",
  "status": "submitted"
}
```

消息结构至少应包含：

- task_id；
- run_id；
- agent_id；
- role；
- message_type；
- content；
- references / evidence；
- decision；
- confidence；
- timestamp；
- status。

---

### 7.3 Message Type：消息类型

建议定义以下消息类型：

| 类型 | 含义 |
|---|---|
| `task` | 原始任务或子任务 |
| `proposal` | 方案或设计 |
| `plan` | 执行计划 |
| `result` | 执行结果 |
| `review` | 审查意见 |
| `critique` | 批判性评价 |
| `revision_request` | 返工请求 |
| `revision_result` | 返工结果 |
| `test_report` | 测试报告 |
| `evaluation` | 质量评估 |
| `decision` | 决策结果 |
| `human_feedback` | 人工反馈 |

---

### 7.4 Blackboard / Shared State：共享状态

Agent 之间不一定直接点对点通信，而是通过共享状态交流。

```text
Agent A 写入 Blackboard
Agent B 读取 Blackboard
Supervisor 决定下一步
Evaluator 检查结果
Human Gate 最终确认
```

共享状态可以保存：

- 用户原始任务；
- 任务拆解；
- 每个 Agent 的输出；
- 工具调用记录；
- 证据来源；
- 当前决策；
- 评估结果；
- 人工反馈。

示例结构：

```json
{
  "run_id": "R20260606_001",
  "user_query": "为当前项目设计多智能体协作机制",
  "task_plan": [],
  "agent_outputs": {
    "planner": [],
    "executor": [],
    "reviewer": [],
    "evaluator": []
  },
  "evidence": [],
  "reviews": [],
  "decisions": [],
  "human_feedback": null,
  "final_output": null
}
```

---

### 7.5 Dialogue Protocol：对话协议

MACR 中的 Agent 交互需要明确协议。

基本协议可以包括：

```text
1. Planner 必须先输出 proposal；
2. Reviewer 只能基于 proposal 或 result 进行审查；
3. Executor 只能基于 approved plan 执行；
4. Evaluator 必须基于 result + evidence + rule 进行判断；
5. 如果 Evaluator 返回 NEEDS_FIX，则 Supervisor 触发 revision；
6. 如果 Evaluator 返回 BLOCKED，则进入 Human Gate；
7. 所有结论必须附带 evidence 或说明缺失信息。
```

---

## 8. MACR 的工作流模式

### 8.1 回合制讨论模式

适用于方案设计、科研 idea、架构设计。

```text
Agent A 提方案
Agent B 提方案
Agent A 审查 Agent B
Agent B 审查 Agent A
Supervisor 汇总
Evaluator 评估
Human Gate 确认
```

优点：

- 避免单一 Agent 的思路盲区；
- 促进多视角比较；
- 适合复杂方案设计。

---

### 8.2 执行-审查-返工模式

适用于软件开发、论文修订、数据分析。

```text
Planner 生成计划
Executor 执行
Reviewer 审查
Evaluator 判断是否通过
如果不通过 → Executor 修复
如果通过 → Human Gate
```

---

### 8.3 并行专家模式

适用于领域决策系统。

```text
Supervisor 拆解任务
多个 Specialist Agents 并行执行
Fusion Agent 融合结果
Evaluator 检查冲突和证据
Human Gate 确认
```

例如农田生态保育系统中：

- 数据检索 Agent；
- 生态类型识别 Agent；
- 限制因子诊断 Agent；
- 风险预警 Agent；
- 方案推荐 Agent。

---

## 9. MACR 与应用系统的衍生关系

MACR 是框架底座，后续可衍生多个应用。

```text
MACR Framework
  ├── Coding Agent Orchestrator
  ├── Farmland Ecological Conservation Decision System
  ├── Scientific Manuscript Agent System
  ├── Research Idea Generation System
  ├── Data Analysis Agent Platform
  └── 其他领域决策系统
```

---

## 10. 应用方向一：农田生态保育决策系统

该应用可以基于 MACR 派生领域 Agent：

- 数据检索智能体；
- 知识问答智能体；
- 生态类型识别智能体；
- 限制因子诊断智能体；
- 保育效果评估智能体；
- 风险预警智能体；
- 方案推荐智能体；
- 结果融合与可解释输出智能体。

该系统解决的问题：

```text
针对农田生态保育技术模式筛选、区域适配和推广服务缺乏智能化工具的问题，
形成任务分解、知识检索、图谱推理、模型调用、专家规则约束、结果融合和可解释输出的协同机制。
```

---

## 11. 应用方向二：科研论文智能辅助系统

该应用可以基于 MACR 派生科研 Agent：

- Idea 生成智能体；
- 文献检索智能体；
- 数据审查智能体；
- 统计分析智能体；
- 代码执行智能体；
- 结果解释智能体；
- 过度解读审查智能体；
- 论文写作智能体；
- 审稿人模拟智能体；
- 修稿与回复智能体。

该系统不应定位为“AI 自动写论文”，而应定位为：

```text
证据驱动的科研流程智能辅助系统。
```

重点是：

- 不编造数据；
- 不编造文献；
- 不编造统计结果；
- 不夸大机制解释；
- 方法、结果、图表和正文保持一致；
- 所有关键结论可追溯。

---

## 12. 技术栈建议

### 12.1 MVP 技术栈

适合第一版开发：

| 层级 | 技术 |
|---|---|
| Agent 编排 | LangGraph |
| 后端服务 | FastAPI |
| 前端 | Next.js + React + Tailwind |
| 数据库 | PostgreSQL |
| 向量检索 | pgvector |
| 队列 / 缓存 | Redis |
| 文件存储 | 本地文件系统 / MinIO |
| 规则 | YAML / JSON |
| 模型调用 | LiteLLM / OpenAI SDK / Anthropic SDK |
| 部署 | Docker Compose |

---

### 12.2 进阶技术栈

| 层级 | 技术 |
|---|---|
| Agent 编排 | LangGraph + Supervisor Pattern |
| Agent SDK | LangChain / OpenAI Agents SDK |
| 模型网关 | LiteLLM |
| 后端 | FastAPI + Celery |
| 前端 | Next.js + React Flow + ECharts |
| 数据库 | PostgreSQL + PostGIS |
| 向量数据库 | Qdrant / Milvus |
| 知识图谱 | Neo4j / NebulaGraph |
| 对象存储 | MinIO |
| 可观测性 | LangSmith / OpenTelemetry / Phoenix |
| 部署 | Docker Compose → Kubernetes |

---

## 13. 初始项目目录建议

```text
macr-framework/
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── agents/
│   │   ├── graphs/
│   │   ├── messages/
│   │   ├── tools/
│   │   ├── rules/
│   │   ├── schemas/
│   │   └── storage/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   └── nextjs-app/
├── infra/
│   ├── docker-compose.yml
│   ├── postgres/
│   ├── redis/
│   └── minio/
├── examples/
│   ├── coding_agent_orchestrator/
│   ├── farmland_decision_system/
│   └── manuscript_agent_system/
├── docs/
│   ├── architecture.md
│   ├── message_protocol.md
│   ├── agent_roles.md
│   ├── workflow_templates.md
│   └── roadmap.md
└── tests/
```

---

## 14. 第一版 MVP 建议

第一版不要做太大。

建议只实现：

```text
Supervisor Agent
Planner Agent
Executor Agent
Reviewer Agent
Evaluator Agent
Human Gate
Shared State
Message Schema
Decision Log
```

第一版工作流：

```text
用户输入任务
  ↓
Supervisor 拆解任务
  ↓
Planner 生成方案
  ↓
Executor 执行
  ↓
Reviewer 审查
  ↓
Evaluator 判断 PASS / NEEDS_FIX / BLOCKED
  ↓
如果 NEEDS_FIX → Executor 修复
  ↓
如果 PASS → Human Gate
  ↓
最终输出
```

---

## 15. 第一版验证场景

建议优先用软件开发协作作为验证场景。

原因：

- 输入明确；
- 输出可验证；
- 可以用 git diff 评估；
- 可以运行测试；
- Claude / Codex 分工清晰；
- 适合验证 Planner–Executor–Reviewer–Tester 闭环。

MVP 示例：

```text
任务：为某个项目增加一个功能
Claude：设计方案
Codex：实现代码
Claude：审查 diff
Codex：修复问题
Claude：运行测试并最终验收
人类：确认 merge
```

---

## 16. MACR 的核心设计原则

### 16.1 角色明确

每个 Agent 必须有明确边界。

不要使用模糊角色：

```text
你是一个优秀的全栈专家。
```

应使用精确角色：

```text
你是代码审查智能体。
你只能审查 git diff，不要修改代码。
每个问题必须包含文件路径、风险等级、原因和建议。
```

---

### 16.2 状态显式化

所有关键过程都必须写入 State：

- 输入；
- 计划；
- 执行结果；
- 审查意见；
- 证据；
- 决策；
- 测试日志；
- 人工反馈。

---

### 16.3 证据可追溯

所有关键结论都应能追溯到：

- 数据；
- 文件；
- 文献；
- 代码；
- 工具调用；
- 测试日志；
- 专家规则。

---

### 16.4 权限最小化

每个 Agent 只能访问必要工具。

例如：

- Reviewer 默认不能改代码；
- Executor 默认不能决定是否合格；
- Evaluator 默认不能执行任务；
- Writer 默认不能编造数据。

---

### 16.5 结构化输出

Agent 输出不能只是自然语言，应尽可能结构化。

例如：

```json
{
  "decision": "needs_fix",
  "blocking_issues": [],
  "non_blocking_issues": [],
  "evidence": [],
  "next_action": "revise"
}
```

---

### 16.6 Human-in-the-loop

MACR 不应追求完全无人化。

关键节点必须支持人工确认：

- 高风险决策；
- 不确定输出；
- 证据不足；
- 多 Agent 冲突；
- 最终合并；
- 对外发布。

---

## 17. 研究“智能体对话桥梁”的方向

如果将 Agent 通信桥梁作为 MACR 的研究重点，可以从以下问题展开。

### 17.1 自由文本 vs 结构化消息

比较：

```text
自由对话
结构化 JSON 消息
Markdown + YAML frontmatter
TypedDict / Pydantic schema
```

评价指标：

- 信息完整性；
- 可解析性；
- 任务收敛速度；
- 错误率；
- 冲突率；
- 可追溯性。

---

### 17.2 点对点通信 vs Blackboard

比较：

```text
Agent A 直接发给 Agent B
Agent A 写入共享状态，Agent B 从共享状态读取
Supervisor 控制路由
```

MACR 初期建议采用 Blackboard + Supervisor。

---

### 17.3 同步回合制 vs 异步事件驱动

回合制适合：

- 方案讨论；
- 互审；
- 决策生成。

异步适合：

- 多工具调用；
- 长任务执行；
- 多 Agent 并行检索；
- 批量分析。

---

### 17.4 冲突处理机制

当多个 Agent 结论不一致时，可以采用：

- Supervisor 仲裁；
- Evaluator 评估；
- 规则库约束；
- 证据优先；
- 置信度排序；
- 投票；
- Human Gate。

建议高风险任务不要自动投票决定，而应进入 Human Gate。

---

## 18. 未来开发路线图

### V0：文档与协议设计

- 定义 MACR 核心概念；
- 定义 Agent Role；
- 定义 Message Schema；
- 定义 State Schema；
- 定义基础 Workflow；
- 建立 GitHub 仓库。

---

### V1：CLI MVP

- 实现命令行版 MACR；
- 支持 Planner → Executor → Reviewer → Evaluator；
- 结果写入 `.macr/runs/`；
- 支持 Markdown / JSON 日志；
- 用 Claude + Codex 软件开发协作验证。

---

### V2：Web 控制台

- Next.js 前端；
- 显示任务流程；
- 显示每个 Agent 输出；
- 支持人工审核；
- 支持运行记录查看。

---

### V3：插件化 Agent 与工具注册

- Agent Registry；
- Tool Registry；
- Workflow Template Registry；
- 可配置角色与权限；
- 支持不同应用场景。

---

### V4：应用系统衍生

- Coding Agent Orchestrator；
- Farmland Decision System；
- Scientific Manuscript Agent System；
- 其他科研与决策场景。

---

## 19. 项目命名建议

候选英文名称：

```text
MACR Framework
Multi-Agent Collaborative Reasoning Framework
Collaborative Agent Reasoning Engine
AgentRoundtable
ReasoningMesh
AgentBridge
AgentCouncil
```

建议首选：

```text
MACR Framework
```

GitHub 描述可以写为：

```text
A general-purpose framework for multi-agent collaborative reasoning, structured dialogue, cross-review, iterative execution, and human-in-the-loop decision workflows.
```

中文描述：

```text
MACR 是一个通用多智能体协同推理框架，支持多 Agent 任务分解、结构化对话、交叉审查、迭代执行、结果评估和人工门控，可作为科研、软件开发和领域决策系统的智能协作底座。
```

---

## 20. 当前最重要的下一步

建议立即做三件事：

### 20.1 建 GitHub 仓库

仓库名建议：

```text
macr-framework
```

或者：

```text
multi-agent-collaborative-reasoning
```

---

### 20.2 写第一版 README

README 应包含：

- 项目定位；
- 架构图；
- 核心角色；
- Message Schema；
- Workflow 示例；
- 技术栈；
- Roadmap。

---

### 20.3 先实现一个最小工作流

最小工作流：

```text
Task → Planner → Executor → Reviewer → Evaluator → Human Gate → Final Output
```

输出目录：

```text
.macr/runs/<run_id>/
  input.md
  planner.output.md
  executor.output.md
  reviewer.output.md
  evaluator.output.json
  final.md
```

这就是 MACR 的第一版可运行雏形。

---

## 21. 总结

MACR 的本质不是一个聊天机器人，也不是一个具体业务系统，而是：

> **面向复杂任务的多智能体协同推理、交叉审查、迭代执行和人工门控框架。**

它的核心价值在于：

```text
多角色协同
结构化通信
共享状态
任务编排
交叉审查
证据追踪
迭代返工
人工确认
多应用衍生
```

未来可以基于 MACR 衍生：

- 软件开发协作系统；
- 农田生态保育决策系统；
- 科研论文智能辅助系统；
- 数据分析智能体平台；
- 领域知识决策系统；
- 更多科研和工程场景。

因此，当前最优路线是：

```text
先开发 MACR 通用框架；
再用 Claude + Codex 软件开发协作做自验证；
随后扩展到农田生态保育和科研论文智能辅助等应用场景。
```

