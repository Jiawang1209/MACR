# 消息与状态协议 (Message & State Protocol)

> 角色定义见 [agent_roles.md](agent_roles.md);工作流见 [workflow_templates.md](workflow_templates.md)。

## 消息结构 (Message Schema)

每条 Agent 输出必须遵循统一的消息格式。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | string | 是 | 所属任务/子任务 ID |
| `run_id` | string | 是 | 运行实例 ID |
| `agent_id` | string | 是 | 发出消息的 Agent 标识 |
| `role` | string | 是 | Agent 角色(见 agent_roles.md) |
| `message_type` | enum | 是 | 消息类型(见下表) |
| `content` | object | 是 | 消息主体(summary/findings/decision/confidence 等) |
| `references` | string[] | 否 | 证据来源(文件/diff/日志) |
| `timestamp` | string (ISO8601) | 是 | 产生时间 |
| `status` | enum | 是 | submitted / accepted / superseded 等 |

```json
{
  "task_id": "T123",
  "run_id": "R20260606_001",
  "agent_id": "claude_reviewer",
  "role": "reviewer",
  "message_type": "review",
  "content": {
    "summary": "Codex 的实现基本符合 consensus,但缺少边界条件测试。",
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
  "references": ["consensus.md", "diff.patch", "test.log"],
  "timestamp": "2026-06-06T10:00:00Z",
  "status": "submitted"
}
```

## 消息类型 (Message Type)

以下消息类型已定义。

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

## 共享状态 (State / Blackboard Schema)

各 Agent 通过共享的 Blackboard 进行通信，而非点对点传递消息：Agent A 写入 Blackboard → Agent B 读取 → Supervisor 决定下一步 → Evaluator 检查结果 → Human Gate 最终确认。共享状态存储以下内容：

- 用户原始任务
- 任务拆解
- 每个 Agent 的输出
- 工具调用记录
- 证据来源
- 当前决策
- 评估结果
- 人工反馈

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

## 对话协议 (Dialogue Protocol)

Agent 之间的交互遵循显式协议：

1. Planner 必须先输出 proposal;
2. Reviewer 只能基于 proposal 或 result 进行审查;
3. Executor 只能基于 approved plan 执行;
4. Evaluator 必须基于 result + evidence + rule 进行判断;
5. 如果 Evaluator 返回 NEEDS_FIX,则 Supervisor 触发 revision;
6. 如果 Evaluator 返回 BLOCKED,则进入 Human Gate;
7. 所有结论必须附带 evidence 或说明缺失信息。
