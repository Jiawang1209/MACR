# Coding Agent Orchestrator (示例 / Example)

> 状态:**待展开 / TODO (V4)** — 这是一个占位桩,不是已实现的示例。

基于 MACR 的工程应用:Claude 负责方案设计、代码审查与测试,Codex 负责代码实现与修复,
两者通过回合制互审与返工形成协作闭环(参见蓝图 §5)。

落地环境建议:`tmux + git worktree`,为每个 Agent 分配独立工作目录,最后 review/merge 整合(参见蓝图 §6)。

详细工作流与目录约定将在框架 V1/V4 阶段展开。参见 [`docs/workflow_templates.md`](../../docs/workflow_templates.md)。
