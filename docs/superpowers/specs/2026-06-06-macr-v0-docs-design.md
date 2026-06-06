# MACR V0 文档重构 — 设计规格(Design Spec)

> 日期:2026-06-06
> 阶段:V0(文档与协议设计,不写代码)
> 范围:把现有蓝图 `MACR_Multi-Agent_Collaborative_Reasoning_Framework.md` 重构为正式的、可开源展示的 GitHub 仓库文档结构。

---

## 1. 目标与非目标

### 目标
- 把单文件大蓝图,重构为一套结构清晰、单一主题、易导航的仓库文档。
- 产出"可读、专业、可开源展示"的文档(定位:**整理重构档**)。
- 内容**忠于现有蓝图**:只做重组、润色、补图、消除重复,**不新增设计观点**。
- 为后续 V1 CLI MVP 的 `docs/` 提供可平滑沿用的地基。

### 非目标(YAGNI)
- 不写任何代码、不搭脚手架(那是 V1)。
- 不做"规格强化"(不把 Schema 升级为严谨可落地的字段约束/状态机)——保持现有蓝图的深度即可。
- 不做"研究论证档"(不展开 §17 的对比实验/评价指标分析,仅取其结论)。
- 不展开任何具体应用系统的实现细节(农田、论文、Codex 协作仅作占位)。

---

## 2. 关键决策(来自 brainstorming)

| 维度 | 决策 |
|---|---|
| 阶段/产出 | V0 文档与协议规格,不写代码 |
| 深度定位 | 整理重构档(可读、专业、可开源展示;忠于现有蓝图) |
| 语言 | 双语:README 中英双语;`docs/` 中文为主、保留英文术语 |
| 内容范围 | 只保留纯框架(A);应用(B)与落地细节(C)剥离到 `examples/` 占位桩 |
| 文档结构 | 方案 A:忠于蓝图 §13 的多文件 `docs/` 布局 |

---

## 3. 目标仓库结构

```
README.md                      # 中英双语,仓库门面
docs/
  architecture.md              # 系统架构 + 设计哲学 + 共享状态 + 设计原则
  message_protocol.md          # Message Schema + Message Type + State Schema + Dialogue Protocol
  agent_roles.md               # 7 个角色的职责/边界/权限/消息类型
  workflow_templates.md        # 3 种工作流模式 + V1 最小闭环
  roadmap.md                   # V0~V4 + 命名 + 下一步
examples/
  coding_agent_orchestrator/README.md   # 占位桩(待展开)
  farmland_decision_system/README.md    # 占位桩(待展开)
  manuscript_agent_system/README.md     # 占位桩(待展开)
```

原始蓝图文件 `MACR_Multi-Agent_Collaborative_Reasoning_Framework.md` 保留(作为来源存档),不删除。

---

## 4. 各文件章节大纲与来源映射

来源标注指向原蓝图的章节号(§)。

### 4.1 `README.md`(中英双语)
- 项目定位一句话 + 中英 GitHub 描述 ← §1, §19, §21
- 核心思想:结构化协同(对比"自由聊天"的问题)← §3
- **架构图**(新画):用户 → Supervisor → Planner/Executor/Reviewer/Evaluator/Tester → Human Gate,围绕中央 Blackboard
- 核心角色一览表(7 角色一句话职责)← §4
- Message Schema 摘要 + 一个 JSON 示例 ← §7.2
- 最小工作流示例(Task → Planner → Executor → Reviewer → Evaluator → Human Gate → Final)← §14
- 技术栈速览 ← §12
- Roadmap 摘要 + 指向 `docs/` 与 `examples/` 的链接 ← §18

**双语形式**:README 采用中英双语,每个章节**中文在前、英文在后**(与 `docs/` 中文为主保持一致);专有术语统一保持英文原词。

### 4.2 `docs/architecture.md`
- 设计哲学:为什么是结构化协同而非自由聊天 ← §3
- 框架 vs 应用的关系(MACR 是底座,领域应用在其上配置)← §2, §9
- 系统总体架构图 + 数据流说明
- 共享状态 / Blackboard 机制 ← §7.4
- 关键架构决策(精炼版,只取结论):点对点 vs Blackboard、同步回合制 vs 异步、冲突处理 ← §17
- 核心设计原则六条:角色明确 / 状态显式 / 证据可追溯 / 权限最小化 / 结构化输出 / Human-in-the-loop ← §16

### 4.3 `docs/message_protocol.md`
- Message Schema 字段表(字段 / 类型 / 必填 / 说明)+ JSON 示例 ← §7.2
- Message Type 一览表(task/proposal/plan/result/review/critique/revision_request/revision_result/test_report/evaluation/decision/human_feedback)← §7.3
- State / Blackboard Schema 结构 + JSON 示例 ← §7.4
- Dialogue Protocol 协议规则(7 条)← §7.5

### 4.4 `docs/agent_roles.md`
- 7 个角色逐一说明,每个包含:**职责 / 边界(不能做什么)/ 权限 / 接收&产出的消息类型**
  - Supervisor / Orchestrator ← §4.1
  - Planner ← §4.2
  - Executor / Implementer ← §4.3
  - Reviewer ← §4.4
  - Evaluator ← §4.5
  - Tester ← §4.6
  - Human Gate ← §4.7
- 角色定义风格原则(精确角色 vs 模糊角色对比示例)← §16.1

### 4.5 `docs/workflow_templates.md`
- 模式一:回合制讨论 ← §8.1
- 模式二:执行-审查-返工 ← §8.2
- 模式三:并行专家 ← §8.3
- V1 最小闭环 + `.macr/runs/<run_id>/` 输出目录结构 ← §14, §20.3

### 4.6 `docs/roadmap.md`
- V0 → V4 路线 ← §18
- 命名候选 ← §19
- 下一步三件事 ← §20

### 4.7 `examples/`(占位桩)
每个目录一个 `README.md`,简述用途 + 一句话指引 + 明确标注"待展开 / TODO V4":
- `coding_agent_orchestrator/` ← §5 Claude+Codex 场景 + §6 tmux/worktree
- `farmland_decision_system/` ← §10
- `manuscript_agent_system/` ← §11

---

## 5. 内容覆盖检查(无遗漏验证)

| 蓝图章节 | 去处 |
|---|---|
| §1 项目定位 | README + architecture |
| §2 框架与应用关系 | architecture |
| §3 结构化协同 | README + architecture |
| §4 角色模型 | agent_roles(README 摘要) |
| §5 Claude+Codex 场景 | examples/coding(桩) |
| §6 tmux/worktree | examples/coding(桩) |
| §7 桥梁/Schema/协议 | message_protocol |
| §8 工作流模式 | workflow_templates |
| §9 衍生关系 | architecture |
| §10 农田应用 | examples/farmland(桩) |
| §11 论文应用 | examples/manuscript(桩) |
| §12 技术栈 | README |
| §13 目录建议 | 本 spec §3(落地为真实结构) |
| §14 第一版 MVP | workflow_templates + README |
| §15 验证场景 | examples/coding(桩) |
| §16 设计原则 | architecture |
| §17 桥梁研究方向 | architecture(只取结论) |
| §18 路线图 | roadmap |
| §19 命名 | roadmap |
| §20 下一步 | roadmap |
| §21 总结 | README |

结论:蓝图 §1–§21 全部有去处,无内容丢弃。应用类(§5/§6/§10/§11/§15)降级为 `examples/` 桩,其余进入框架文档。

---

## 6. 完成标准(Definition of Done)

- [ ] `README.md`、`docs/` 下 5 个文件、`examples/` 下 3 个桩文件全部产出。
- [ ] 每个文档单一主题、章节清晰、内部链接可跳转。
- [ ] README 中英双语;`docs/` 中文为主、英文术语保留。
- [ ] 至少一张新架构图(README;architecture 可复用或细化)。
- [ ] 覆盖检查表中所有蓝图章节均已落位,无遗漏、无重复堆叠。
- [ ] 原蓝图文件保留为来源存档。
