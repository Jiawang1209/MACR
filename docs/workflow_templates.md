# Workflow Templates

> 角色见 [agent_roles.md](agent_roles.md);消息格式见 [message_protocol.md](message_protocol.md)。

## 模式一:回合制讨论(Round-Robin Discussion)

```text
Agent A 提方案
Agent B 提方案
Agent A 审查 Agent B
Agent B 审查 Agent A
Supervisor 汇总
Evaluator 评估
Human Gate 确认
```

适用场景:方案设计、科研 idea、架构设计。

优点:避免单一 Agent 的思路盲区;促进多视角比较;适合复杂方案设计。

## 模式二:执行-审查-返工(Execute-Review-Revise)

```text
Planner 生成计划
Executor 执行
Reviewer 审查
Evaluator 判断是否通过
不通过 → Executor 修复
通过 → Human Gate
```

适用场景:软件开发、论文修订、数据分析。

## 模式三:并行专家(Parallel Specialists)

```text
Supervisor 拆解任务
多个 Specialist Agents 并行执行
Fusion Agent 融合结果
Evaluator 检查冲突和证据
Human Gate 确认
```

适用场景:领域决策系统。

举例(农田生态保育系统):数据检索 Agent、生态类型识别 Agent、限制因子诊断 Agent、风险预警 Agent、方案推荐 Agent。

## V1 最小闭环(Minimal Loop)

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

每次运行的产物写入以下目录结构。

```text
.macr/runs/<run_id>/
  input.md
  planner.output.md
  executor.output.md
  reviewer.output.md
  evaluator.output.json
  final.md
```
