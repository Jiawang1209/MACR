# MACR 路线图与项目定位

## 1. 路线图(Roadmap V0 → V4)

### V0:文档与协议设计(当前阶段)
- 定义 MACR 核心概念、Agent Role、Message Schema、State Schema、基础 Workflow;
- 建立 GitHub 仓库与结构化文档。

### V1:CLI MVP
- 实现命令行版 MACR;
- 支持 Planner → Executor → Reviewer → Evaluator 闭环;
- 结果写入 `.macr/runs/`,支持 Markdown / JSON 日志;
- 用 Claude + Codex 软件开发协作做自验证。
- Stage D:`discuss` 共识后插入 Codex 计划审查门(独立审查 + 确定性评估 + 限次修订,耗尽升人工门)。

### V2:Web 控制台
- Next.js 前端;
- 显示任务流程与每个 Agent 输出;
- 支持人工审核与运行记录查看。

### V3:插件化 Agent 与工具注册
- Agent Registry、Tool Registry、Workflow Template Registry;
- 可配置角色与权限;
- 支持不同应用场景。

### V4:应用系统衍生
- Coding Agent Orchestrator;
- Farmland Decision System;
- Scientific Manuscript Agent System;
- 其他科研与决策场景。

## 2. 项目命名

首选名称:**MACR Framework**。

候选名称如下：

```text
MACR Framework
Multi-Agent Collaborative Reasoning Framework
Collaborative Agent Reasoning Engine
AgentRoundtable
ReasoningMesh
AgentBridge
AgentCouncil
```

英文描述：`A general-purpose framework for multi-agent collaborative reasoning, structured dialogue, cross-review, iterative execution, and human-in-the-loop decision workflows.`

中文描述：`MACR 是一个通用多智能体协同推理框架,支持多 Agent 任务分解、结构化对话、交叉审查、迭代执行、结果评估和人工门控,可作为科研、软件开发和领域决策系统的智能协作底座。`

## 3. 下一步

以下三件事为 V0 阶段的核心推进项（本仓库当前已在推进前两项）：

1. 建立 GitHub 仓库（`macr-framework`）;
2. 写第一版 README（定位、架构图、核心角色、Message Schema、Workflow 示例、技术栈、Roadmap）;
3. 实现最小工作流：`Task → Planner → Executor → Reviewer → Evaluator → Human Gate → Final Output`，产物写入 `.macr/runs/<run_id>/`。
