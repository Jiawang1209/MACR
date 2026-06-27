# 多智能体协作编排系统设计思路

## 1. 项目背景

当前 Codex、Claude Code 以及其他 Agent 平台已经陆续提供了 `subagent` 或类似的子智能体机制，用于在一个主 Agent 内部进行任务分解、上下文隔离、并行执行和结果汇总。

因此，在开发一个自研的 multi-agent 协作工具时，需要首先回答一个核心问题：

> 如果 Codex / Claude Code 已经有 subagent，那么自研多智能体协作编排工具是否还有必要？

结论是：

> **有必要，但前提是它不能只是“多个 Agent 同时执行任务”。它应该定位为跨模型、跨工具、跨任务、跨项目的 Agent 协作编排层。**

换句话说：

> **Codex / Claude Code 的 subagent 是某个平台内部的分工机制；自研 multi-agent 系统应该是平台外部的协作操作系统或编排层。**

---

## 2. Codex / Claude Code subagent 的本质

### 2.1 Codex subagent

Codex 的 subagent 主要用于在 Codex 内部启动多个专门 Agent，并行完成代码库探索、多步骤功能实现、测试检查和结果汇总等任务。

其关键词可以概括为：

```text
Codex 内部
并行任务
代码任务
专门 Agent
结果汇总
```

适合的典型场景包括：

- 一个 Agent 查找代码结构；
- 一个 Agent 实现功能；
- 一个 Agent 编写或运行测试；
- 一个 Agent 检查边界问题；
- 最后由主 Agent 汇总结果。

### 2.2 Claude Code subagent

Claude Code 的 subagent 主要用于：

- 隔离上下文；
- 并行执行任务；
- 使用专门指令；
- 管理复杂代码任务；
- 保持主会话上下文干净。

其关键词可以概括为：

```text
Claude Code 内部
上下文隔离
专门任务
代码执行
工具调用
worktree / hooks / skills 配合
```

---

## 3. 自研 multi-agent 协作器的定位

不建议把自研工具定位为：

```text
我也有 subagent
```

这个定位容易和平台厂商已有能力重叠。

更合适的定位是：

```text
面向多模型、多平台、多任务的 Agent 协作编排框架
```

或者：

```text
Agent Collaboration Orchestrator
```

如果沿用 MACR 的命名，可以定义为：

```text
MACR: Multi-Agent Collaborative Reasoning Framework
```

中文定义：

> **MACR 是一个面向复杂科研与软件开发任务的多智能体协作编排框架，重点解决任务拆解、异构模型协同、执行-审查闭环、结果验证、过程记录与知识沉淀等问题。**

英文定义：

> **MACR is a lightweight orchestration framework for coordinating heterogeneous AI agents across planning, execution, review, testing, and reporting workflows.**

---

## 4. 与 Codex / Claude Code subagent 的区别

| 维度 | Codex / Claude Code subagent | 自研 multi-agent 协作器 |
|---|---|---|
| 所属层级 | 平台内部能力 | 平台外部编排层 |
| 作用范围 | 主要服务当前代码任务 | 可服务代码、论文、数据分析、科研流程、运维等 |
| Agent 来源 | 通常来自同一平台 | 可调度 Claude、Codex、GPT、Gemini、DeepSeek、本地模型、脚本工具 |
| 协作结构 | 主 Agent 分派任务给子 Agent | 可定义审查-执行-测试-仲裁-回滚-复盘等复杂拓扑 |
| 上下文管理 | 平台内部上下文隔离 | 可做跨会话、跨项目、跨工具的长期上下文管理 |
| 记忆机制 | 当前项目或当前会话为主 | 可沉淀任务记录、评审记录、失败案例、决策日志 |
| 可靠性机制 | 平台自带检查与权限 | 可加入强制测试、双模型交叉验证、证据链、回滚机制 |
| 可迁移性 | 绑定 Codex 或 Claude Code | 可迁移到不同 Agent 后端 |
| 目标用户 | 代码开发者 | 可扩展到科研人员、数据工程师、平台开发者、团队协作 |

核心区别可以概括为：

> **Codex / Claude Code 的 subagent 是执行单元；自研 multi-agent 系统应该是调度、治理和评估层。**

也可以更直观地表达为：

> **subagent 是平台内部的工人；自研系统应该是项目经理、调度中心和质检系统。**

---

## 5. 什么时候没有必要自研？

如果工具只做下面几类事情，则应用价值有限。

### 5.1 只是包装 subagent

例如：

```text
主 Agent -> 调用 3 个子 Agent -> 汇总输出
```

这种能力 Codex / Claude Code 已经可以覆盖。

### 5.2 只是角色扮演

例如：

```text
你是架构师 Agent
你是程序员 Agent
你是测试 Agent
```

如果没有真实的任务拆解、状态跟踪、文件隔离、测试验证、错误回滚、冲突仲裁、成本控制和日志沉淀，这类系统容易退化成“多角色聊天”。

### 5.3 只解决单一平台能解决的问题

如果所有任务都发生在 Claude Code 内部，那么 Claude Code subagent 已经足够。

如果所有任务都发生在 Codex 内部，那么 Codex subagent 也已经足够。

---

## 6. 什么时候有必要自研？

### 6.1 跨模型协作

例如：

```text
Codex：低成本执行、批量修改、跑测试
Claude：高质量审查、架构判断、风险识别
GPT：需求澄清、文档生成、方案归纳
DeepSeek / 本地模型：低成本预处理、中文材料整理
```

可以形成如下工作流：

```text
需求输入
  ↓
任务拆解 Agent
  ↓
Codex 执行
  ↓
Claude 审查
  ↓
测试 Agent 验证
  ↓
仲裁 Agent 决策是否合并
  ↓
生成变更日志 / PR / 文档
```

这种跨模型、跨平台编排不是单一平台 subagent 能完整解决的。

### 6.2 审查-执行闭环

一个有价值的多智能体系统应该形成强制闭环：

```text
计划 → 执行 → 测试 → 审查 → 修复 → 再测试 → 归档
```

可以设计为：

```text
Planner Agent：拆解任务
Executor Agent：执行修改
Tester Agent：运行验证
Reviewer Agent：审查代码或结果
Fixer Agent：根据测试失败进行修复
Reporter Agent：生成报告
```

这比简单的 subagent 更接近一个工程管理系统。

### 6.3 科研工作流自动化

对于科研场景，自研多智能体系统尤其有价值。

例如：

```text
数据检查 Agent
统计建模 Agent
R代码执行 Agent
图表生成 Agent
论文写作 Agent
审稿意见回复 Agent
文献核查 Agent
```

在微生物组和生态数据分析中，可以形成：

```text
微生物组数据
  ↓
数据质控 Agent
  ↓
差异分析 Agent
  ↓
网络分析 Agent / ggNetView Agent
  ↓
可视化 Agent
  ↓
生态解释 Agent
  ↓
论文结果段落 Agent
  ↓
审稿人视角 Reviewer Agent
```

这个方向可以和 ggNetView、GeneFam-Pipeline、生态数据分析平台、论文辅助系统形成联动。

### 6.4 长期项目记忆与复盘

平台内 subagent 通常解决“当前任务怎么做”。

自研系统可以进一步解决：

```text
这个项目过去做过什么？
上次失败在哪里？
为什么选择这个参数？
哪个 Agent 的判断更可靠？
哪些测试经常失败？
哪些代码修改导致过回归？
```

可以为每个任务保存结构化记录：

```yaml
task_id: 2026-06-27-001
goal: 增加 ggNetView 的共识网络模块
planner_output: ...
executor_changes: ...
reviewer_comments: ...
test_results: ...
final_decision: accepted / rejected / needs_revision
lessons_learned: ...
```

---

## 7. 项目应避免的误区

### 7.1 不要和平台厂商拼 Agent 数量

平台厂商的 subagent 能力会越来越强，单纯比“我有更多 Agent”没有护城河。

真正有价值的是：

```text
任务生命周期管理
异构模型调度
质量控制
验证机制
复盘沉淀
科研场景适配
```

### 7.2 不要做成聊天群

很多 multi-agent demo 只是：

```text
Agent A 说一句
Agent B 说一句
Agent C 总结一下
```

这不是工程化协作。

真正有用的是：

```text
每个 Agent 有明确输入、输出、验收标准、失败处理和状态记录。
```

### 7.3 不要缺少验证层

如果没有测试、审查和证据链，多 Agent 可能只是“多个幻觉互相强化”。

因此系统必须重视：

- 单元测试；
- lint；
- 类型检查；
- 文件 diff；
- 引用证据；
- 运行日志；
- 人工审批节点；
- 失败回滚。

---

## 8. 最小可用版本设计

第一版不需要做得过大，可以从一个清晰的 MVP 开始。

```text
输入一个任务
  ↓
Planner 拆解任务
  ↓
Executor 执行任务
  ↓
Tester 运行验证
  ↓
Reviewer 审查结果
  ↓
Reporter 输出报告
```

每个 Agent 都应输出结构化结果，例如：

```json
{
  "agent": "reviewer",
  "status": "needs_revision",
  "findings": [
    {
      "severity": "high",
      "file": "R/build_network.R",
      "issue": "函数未处理空矩阵输入",
      "suggestion": "增加输入校验"
    }
  ],
  "decision": "reject"
}
```

系统根据结构化结果决定下一步：

```text
accept → 结束
needs_revision → 回到 Executor
reject → 回滚 / 请求人工确认
```

---

## 9. 开发语言选择

### 9.1 直接结论

第一版推荐使用：

```text
Python
```

原因不是 Python 运行最快，而是这个项目的主要瓶颈并不是 CPU 性能，而是：

```text
LLM API 调用延迟
CLI 调度
文件读写
任务状态管理
日志记录
上下文压缩
测试执行
Agent 间消息传递
```

在这些场景下，Python 的开发效率、AI/数据科学生态、LLM 框架支持、科研脚本兼容性明显更合适。

---

## 10. 不同语言的适用性比较

| 语言 | 是否推荐 | 适合部分 | 结论 |
|---|---:|---|---|
| Python | 强烈推荐 | 主编排层、Agent 调度、LLM 调用、科研工作流 | 第一选择 |
| TypeScript / Node.js | 推荐作为备选 | Web UI、插件系统、前端集成、CLI 工具 | 适合界面和扩展层 |
| Go | 可选 | 高并发任务队列、守护进程、CLI、服务端网关 | 后期可拆出来 |
| Rust | 不建议第一版使用 | 高性能执行器、安全沙箱、文件索引 | 过早使用会拖慢开发 |
| Java / Kotlin | 不推荐 | 企业服务端 | 对当前场景偏重 |
| R | 不适合作为主语言 | 科研统计分析、ggNetView 调用 | 作为被调度工具即可 |

---

## 11. 为什么第一版用 Python？

### 11.1 Agent 生态成熟

当前主流 agent workflow / multi-agent 框架大多优先支持 Python，例如：

- LangGraph；
- CrewAI；
- AutoGen；
- Microsoft Agent Framework；
- LangChain 相关生态。

使用 Python 可以更快吸收现有框架的思想、接口、插件和社区经验。

### 11.2 科研场景天然适配 Python

该系统面向的不只是纯后端任务，而是科研工作流：

```text
R脚本
Python脚本
Shell命令
Conda环境
数据文件
论文材料
图表生成
统计建模
网络分析
Git仓库
测试脚本
```

Python 非常适合做这些工具之间的“胶水层”。

例如：

```text
Python Orchestrator
  ├── 调用 Claude / Codex / OpenAI / DeepSeek API
  ├── 执行 Rscript analysis.R
  ├── 执行 pytest / R CMD check
  ├── 读取 Git diff
  ├── 保存 agent 日志
  ├── 管理任务状态 SQLite / DuckDB
  ├── 调用 ggNetView 分析流程
  └── 生成 Markdown / HTML / Word 报告
```

### 11.3 性能不是主要矛盾

真正耗时的通常是：

```text
LLM 生成：几秒到几十秒
代码执行：几秒到几分钟
数据分析：几十秒到几小时
网络请求：不稳定
模型审查：几秒到几十秒
```

Python 编排本身的开销通常不是瓶颈。

---

## 12. 其他语言的角色

### 12.1 TypeScript

适合用于：

```text
Web UI
VS Code 插件
Electron 桌面端
CLI 交互界面
Node.js 工具链集成
前后端同构
```

如果后续想做任务看板、Agent 运行轨迹、审查面板、人工审批按钮，可以引入 TypeScript。

### 12.2 Go

适合用于：

```text
单二进制分发
并发 worker
后台 daemon
任务队列
服务端网关
```

可以作为后期性能化和部署化的补充。

### 12.3 Rust

适合用于：

```text
安全沙箱
文件索引
高性能 diff
本地缓存
插件隔离
代码执行安全控制
```

但 Rust 不适合第一版快速验证多智能体协作逻辑。

### 12.4 R

R 不适合作为主编排语言，但非常适合作为被调度的科研分析工具。

例如：

```text
MACR Python Core → 调用 Rscript → 运行 ggNetView / 统计分析 / 可视化流程
```

---

## 13. 推荐技术架构

建议采用：

```text
Python 主体 + TypeScript UI
```

整体架构可以设计为：

```text
MACR
├── Python Core
│   ├── Agent 调度
│   ├── 任务状态机
│   ├── LLM API 适配器
│   ├── CLI 执行器
│   ├── R/Python/Shell 工具调用
│   ├── 日志与审查记录
│   └── SQLite / DuckDB 存储
│
├── TypeScript UI / CLI
│   ├── Web 控制台
│   ├── 任务看板
│   ├── Agent 对话查看
│   ├── 审查结果展示
│   └── 人工审批按钮
│
└── Optional Go/Rust Worker
    ├── 高并发执行
    ├── 安全沙箱
    └── 文件索引
```

第一阶段可以极简：

```text
Python + Typer + Pydantic + SQLite + Rich + asyncio
```

---

## 14. 第一版技术栈建议

### 14.1 CLI 框架

推荐：

```text
Typer
```

适合快速构建命令行工具，例如：

```bash
macr run "给 ggNetView 增加共识网络模块"
macr review ./repo
macr task list
macr task show 2026-06-27-001
macr replay 2026-06-27-001
```

### 14.2 数据模型

推荐：

```text
Pydantic
```

用于定义 Agent 输出协议：

```python
from pydantic import BaseModel
from typing import Literal

class ReviewFinding(BaseModel):
    severity: Literal["low", "medium", "high"]
    file: str | None
    issue: str
    suggestion: str

class AgentResult(BaseModel):
    agent_name: str
    status: Literal["success", "needs_revision", "failed"]
    summary: str
    findings: list[ReviewFinding] = []
```

结构化输出是多智能体系统工程化的关键。

### 14.3 状态存储

第一版推荐：

```text
SQLite
```

原因：

- 零配置；
- 足够稳定；
- 适合本地任务记录；
- 方便保存任务状态、Agent 输出、diff、日志。

后期可以升级到 PostgreSQL。

### 14.4 日志与可观测性

推荐：

```text
loguru / structlog
```

需要记录：

```text
任务ID
Agent名称
输入 prompt
输出结果
工具调用
执行命令
退出码
错误信息
token 消耗
耗时
最终决策
```

这是区别于普通 subagent 的关键部分。

### 14.5 并发执行

推荐：

```text
asyncio
```

因为 Agent 调用多数是 I/O 密集型：

```text
API 请求
CLI 等待
文件读写
测试执行
```

后期如任务队列变复杂，可引入：

```text
Celery / Dramatiq / RQ
```

### 14.6 工作流引擎

第一版不建议直接依赖重型框架。

可以先自己实现轻量状态机：

```text
PLAN → EXECUTE → TEST → REVIEW → REVISE → REPORT
```

后期再考虑接入：

- LangGraph；
- CrewAI；
- Microsoft Agent Framework；
- Temporal；
- Prefect；
- Airflow。

更好的策略是：

```text
自己定义 MACR 的核心协议
然后把 LangGraph / CrewAI / Claude / Codex 都作为 backend 或 adapter
```

这样系统才有自己的主权，而不是变成某个框架的 wrapper。

---

## 15. 推荐目录结构

```text
macr/
├── pyproject.toml
├── README.md
├── src/
│   └── macr/
│       ├── cli.py
│       ├── core/
│       │   ├── task.py
│       │   ├── state.py
│       │   ├── orchestrator.py
│       │   └── protocol.py
│       ├── agents/
│       │   ├── planner.py
│       │   ├── executor.py
│       │   ├── reviewer.py
│       │   ├── tester.py
│       │   └── reporter.py
│       ├── adapters/
│       │   ├── openai.py
│       │   ├── anthropic.py
│       │   ├── codex_cli.py
│       │   ├── claude_code.py
│       │   └── shell.py
│       ├── storage/
│       │   ├── sqlite.py
│       │   └── models.py
│       ├── tools/
│       │   ├── git.py
│       │   ├── runner.py
│       │   ├── rscript.py
│       │   └── diff.py
│       └── prompts/
│           ├── planner.md
│           ├── executor.md
│           ├── reviewer.md
│           └── reporter.md
└── tests/
```

---

## 16. 核心抽象设计

建议优先定义 5 个核心对象。

### 16.1 Task

描述任务本身：

```text
任务是什么？
输入是什么？
验收标准是什么？
目标仓库是什么？
允许修改哪些文件？
```

### 16.2 Agent

描述执行者：

```text
谁来做？
使用哪个模型？
有什么系统提示词？
能调用哪些工具？
输出格式是什么？
```

### 16.3 Message

描述 Agent 之间传递的信息：

```text
是自然语言？
还是 JSON？
是否包含文件引用、diff、测试结果？
```

### 16.4 State

描述任务状态：

```text
当前任务走到哪一步？
是否失败？
是否需要人工介入？
是否需要回滚？
```

### 16.5 Policy

描述系统策略：

```text
什么时候允许继续？
什么时候必须测试？
什么时候必须人工审批？
什么时候回滚？
```

这些抽象比“写几个 Agent 类”更重要。

---

## 17. 推荐落地路线

### 阶段 1：纯 Python CLI

目标：验证编排逻辑。

技术栈：

```text
Python + Typer + Pydantic + SQLite + Rich
```

实现流程：

```text
Planner → Executor → Tester → Reviewer → Reporter
```

优先支持：

```text
本地 Git 仓库
shell 命令
Rscript
pytest
R CMD check
markdown 报告
```

### 阶段 2：接入 Codex / Claude Code

目标：让系统成为真正的外部编排器。

实现适配器：

```text
CodexCLIAdapter
ClaudeCodeAdapter
OpenAIAdapter
AnthropicAdapter
ShellAdapter
```

命令示例：

```bash
macr run "修复 R 包测试" --executor codex --reviewer claude
macr run "写审稿人回复" --planner gpt --reviewer claude
```

### 阶段 3：科研场景模板

目标：形成差异化。

可以内置模板：

```text
R package development workflow
Microbiome analysis workflow
Gene family analysis workflow
Manuscript revision workflow
Reviewer response workflow
```

这比泛泛的 multi-agent 框架更有实际应用价值。

### 阶段 4：Web UI / Dashboard

目标：提升可视化和人工介入能力。

可实现：

```text
任务列表
Agent 运行轨迹
审查意见
测试结果
文件 diff
人工批准 / 拒绝
成本统计
```

---

## 18. 推荐定位语

### 中文短版

```text
MACR 是一个面向科研代码开发与数据分析任务的多智能体协作编排框架，支持任务拆解、异构模型协同、执行-审查-测试闭环、过程记录与知识沉淀。
```

### 中文正式版

```text
MACR 是一个面向复杂科研与软件开发任务的多智能体协作编排框架。该框架通过任务拆解、异构模型调度、结构化通信、执行-审查-测试闭环、失败回滚与过程记录，实现多个智能体在同一任务生命周期中的协同工作，适用于科研代码开发、数据分析流程、论文辅助写作和项目级知识沉淀等场景。
```

### 英文短版

```text
MACR is a lightweight orchestration framework for coordinating heterogeneous AI agents across planning, execution, review, testing, and reporting workflows.
```

### GitHub Description

```text
A lightweight multi-agent orchestration framework for coordinating heterogeneous AI agents across planning, execution, review, testing, and reporting workflows.
```

---

## 19. 最终结论

自研 multi-agent 协作工具有必要，但不要做成“另一个 subagent”。

正确方向是：

```text
面向科研代码开发与数据分析的多智能体协作编排框架
```

其核心价值不是 Agent 数量，而是：

```text
异构模型协作
任务生命周期管理
结构化通信协议
执行-审查-测试闭环
验证与回滚机制
长期项目记忆
科研场景适配
```

第一版建议使用：

```text
Python 3.11+
Typer
Pydantic
SQLite
Rich
asyncio
```

后期可以引入：

```text
TypeScript：Web UI / 插件 / Dashboard
Go：高并发 worker / daemon / 服务端网关
Rust：安全沙箱 / 高性能文件索引 / diff 引擎
```

一句话总结：

> **用 Python 快速做出核心编排系统，不要追求语言性能；先把 Agent 协作协议、状态机、执行-审查-测试闭环做扎实。**

