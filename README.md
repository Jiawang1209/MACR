# MACR — Multi-Agent Collaborative Reasoning Framework

MACR 让多个 AI Agent 像一个**有纪律的小组**那样协作完成复杂任务:分工、独立出方案、辩论到共识、交叉审查、迭代执行、门控放行,全程留痕、可追溯、可复现。

A framework for **structured** multi-agent collaboration — independent proposals, debate-to-consensus, cross-review, gated execution, and an auditable trail — not "several AIs chatting freely".

> **现状(一句话)**:已实现的是该框架在 **"软件开发协作"** 场景下的 **CLI MVP + Web 控制台(V2)**。核心命令 `macr discuss` 能驱动 **Claude + Codex**:讨论出方案 → 独立审查方案 → 写代码 → 交叉审码 → 跑测试 → 人工门 → 把全过程落盘;`macr web` 起一个浏览器控制台,既能**回看**历史运行,也能**实况驱动**一次新运行(在浏览器里审批人工门)。详见 [现状与成熟度](#现状与成熟度--status)。

---

## 为什么需要它 / Why

多个 AI 自由聊天的典型问题:互相迎合、讨论热闹但无结论、责任不清、过程不可追溯、输出无法验证、容易幻觉。MACR 用一套**可控的协同协议**约束它们:

```text
结构化消息 + 明确角色 + 共享状态 + 任务编排 + 交叉审查 + 人工门控
```

和"可视化多 agent 工作台"(如 tmux 把多个 CLI 摆在一起、人手动路由)不同——那类工具是**舞台**,把"怎么协同"留给人;MACR 是**剧本**:把协同流程本身固化成有角色、有门控、有证据链的自动流水线。

---

## 现在能做什么 / What it does today

四条命令(`macr <command>`):

| 命令 | 做什么 | 依赖 |
|---|---|---|
| `run` | 单个模型(Anthropic API)跑 Planner→Executor→Reviewer→Evaluator 闭环 | `ANTHROPIC_API_KEY` |
| `collab` | Claude+Codex 异构协作改代码(Claude 规划/审查,Codex 在隔离 worktree 执行) | `claude` + `codex` CLI |
| **`discuss`** | **主线**:Claude+Codex 讨论到共识 → 计划审查门 → 实现 → 审码 → 测试 → 人工门 | `claude` + `codex` CLI |
| `web` | 浏览器控制台:回看 `.macr/runs/` 历史运行,或从 `+ New run` 实况驱动一次 collab/discuss(WebSocket 流式 + 浏览器人工门) | `.[web]` 额外依赖;实况驱动需 `claude` + `codex` CLI |

### `macr discuss` 的完整闭环(旗舰)

```text
任务
 │  ① 各自独立出方案        Claude / Codex 各写一份(不互参)
 │  ② 逐轮辩论到共识         互评/修订;人可每轮插话(或 --auto);Claude 汇总共识
 │  ③ 计划审查门 (Stage D)   Codex 独立审查共识方案 → 确定性判 PASS/NEEDS_FIX/BLOCKED
 │                          NEEDS_FIX → 意见注回讨论、再谈一轮、重汇总(限 --max-plan-revisions)
 │  ④ 人工门                你 approve(或 --yes 无人值守)
 │  ⑤ 实现 + 审码           Codex 在隔离 git worktree 写文件 → 跑测试 → Claude 审码 → 判定/返工
 │  ⑥ 最终人工门            看最终 diff + 测试结果拍板
 ▼  ⑦ 全程留痕             .macr/runs/<id>/  transcript / 共识 / 审查 / 决策 / 测试日志
```

差异化要点:**出方案的人不审方案**(Codex 审 Claude 汇总的共识,保独立)、**确定性门控**(不靠模型投票)、**证据可追溯**(每步落盘,可复现可审计)。

---

## 安装与运行 / Install & Run

> 只用项目专属 venv,不污染基础环境 / project-local venv only.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 跑测试(纯本地,无需网络/无需 CLI)
.venv/bin/pytest
```

### run —— 单模型 API 闭环(需 API key)

```bash
export ANTHROPIC_API_KEY=sk-...
.venv/bin/macr run "写一个判断回文的 Python 函数"
```

### collab —— Claude+Codex 异构协作(纯 CLI,无需 API key)

> 需 `claude` 与 `codex` 已安装并登录。

```bash
.venv/bin/macr collab "为模块加一个 hello() 函数" \
    --repo /path/to/target-repo \
    --test-cmd "pytest -q"
```

Claude 出方案/审 diff,Codex 在 `.macr/worktrees/<run_id>/` 改代码,框架跑 `--test-cmd`,规则判定后返工(≤ `--max-revisions`),最后 Human Gate(approve/reject/edit)。approve 后 worktree 保留供你手动 merge。

### discuss —— 讨论到共识再实现(主线,纯 CLI)

```bash
# 交互式:每轮边界 [c]继续 / [i]插话 / [e]定稿 / [a]中止
.venv/bin/macr discuss "为模块加一个 hello() 函数" \
    --repo /path/to/repo --test-cmd "pytest -q"

# 双栏实况围观(Stage C2,需真终端)
.venv/bin/macr discuss "..." --repo R --test-cmd "pytest -q" --tui

# 无人值守:自动推进讨论 + 自动过人工门
.venv/bin/macr discuss "..." --repo R --test-cmd "pytest -q" --auto --yes
```

**discuss 常用参数**:

| 参数 | 含义 |
|---|---|
| `--max-rounds` | 讨论最多几轮(默认 3) |
| `--max-plan-revisions` | 计划审查门最多修订几次(默认 1;`0`=只审不修,纯咨询门) |
| `--max-revisions` | 实现循环最多返工几次(默认 2) |
| `--auto` | 跳过每轮边界暂停(只管讨论轮次) |
| `--yes` | 自动通过共识门与最终人工门,不读 stdin(无人值守用) |
| `--tui` | `rich` 双栏实况视图(Claude/Codex 左右栏 + 底部状态/人声面板) |
| `--no-subagents` | 关闭 Claude/Codex 各自的原生 subagent |
| `--timeout` | 单次 CLI 调用超时秒数(默认 1800) |

> `--auto` 与 `--yes` 职责分离:`--auto` 管讨论是否自动推进;`--yes` 管人工门是否自动 approve。非交互环境(非 TTY)未给 `--yes` 时会清晰报错,而非卡在读 stdin。

### web —— 浏览器控制台(V2,回看 + 实况驱动)

```bash
# 安装 web 额外依赖
.venv/bin/pip install -e ".[web,dev]"

# 一次性构建前端 SPA
cd frontend && npm install && npm run build && cd ..

# 起服务(同时托管 API 与 SPA),浏览器开 http://127.0.0.1:8000
.venv/bin/macr web --runs-dir .macr/runs --port 8000
```

控制台两件事:

- **回看(read-only viewer)**:浏览 `.macr/runs/` 下的历史运行 —— 阶段卡、共识、审查、diff、测试结果一屏看完。
- **实况驱动(live driving)**:`+ New run`(`/launch`)启动一次 collab/discuss,`/live` 通过 WebSocket 流式回放并实时推进,**人工门直接在浏览器里 approve / reject / 留言**。同一时刻只跑一个实况运行,需 `claude` + `codex` 在 PATH 上。

> 前端热重载开发:`cd frontend && npm run dev`(把 `/api` 代理到 `:8000`)。详见 [`macr/web/README.md`](macr/web/README.md)。

---

## 产物 / Artifacts

每次运行写入 `.macr/runs/<run_id>/`,讨论与实现的隔离副本在 `.macr/worktrees/<run_id>/`:

```text
.macr/runs/R20260607_001/
├── topic.md                 # 任务
├── discussion/
│   ├── plan.claude.md        # 两边各自的初始方案
│   ├── plan.codex.md
│   ├── round{N}.{agent}.json # 每轮发言
│   ├── review.v{N}.json      # 计划审查门:Codex 的审查
│   └── transcript.md         # 完整可读讨论记录
├── consensus.md             # 共识方案
├── diff.v{N}.patch          # 实现各轮 diff
├── test.v{N}.json           # 测试结果
├── subagents/               # 各角色原始事件流 + subagent 摘要
├── state.json               # 完整 SharedState(可追溯/可重放)
└── final.md                 # 最终产出
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

所有 Agent 通过中央 **Blackboard / SharedState** 读写(非点对点),Evaluator 在 PASS 时放行,Human Gate 做最终确认。`discuss` 是这套抽象在"两模型 + 计划审查门 + 实现循环"上的具体落地。完整设计见 [`docs/architecture.md`](docs/architecture.md)。

### 核心角色 / Roles

| 角色 | 职责 |
|---|---|
| Planner | 生成方案、拆解步骤、标记风险 |
| Executor | 按方案在隔离 worktree 改代码,产出结果与证据 |
| Reviewer | 审查方案(计划审查门)或代码(实现循环),给出 findings |
| Evaluator | 确定性判定 `PASS / NEEDS_FIX / BLOCKED`(不调模型) |
| Human Gate | 共识门 + 最终门,最终责任主体 |

角色与消息协议详见 [`docs/agent_roles.md`](docs/agent_roles.md) 与 [`docs/message_protocol.md`](docs/message_protocol.md)。

---

## 技术栈 / Tech Stack

**当前真实使用**:

| 用途 | 技术 |
|---|---|
| 语言 | Python ≥ 3.11 |
| 结构化输出/校验 | pydantic v2 |
| 单模型 API 路径(`run`) | anthropic SDK |
| 异构协作(`collab`/`discuss`) | 直接驱动 `claude` / `codex` CLI(子进程 + JSONL 流解析) |
| 实况视图(CLI) | rich |
| 隔离执行 | git worktree |
| Web 后端(`web`) | FastAPI + uvicorn;实况驱动用 stdlib `threading`/`queue` + WebSocket |
| Web 前端 | React 18 + TypeScript + Vite + react-router;Vitest 单测 |
| 测试 | pytest(245 通过)+ Vitest(前端) |

> 数据库 / 队列等栈仍是**规划**,尚未引入;当前 Web 控制台用文件系统(`.macr/runs/`)+ 内存单会话,见 [Roadmap](#路线图--roadmap)。

---

## 现状与成熟度 / Status

- **测试**:245 个 Python 测试全绿(另有前端 Vitest),但均使用 fake 后端——验证的是逻辑正确性。
- **真机 dogfood**(2026-06-07,首次用真实 claude+codex 端到端跑,详见 [`docs/dogfood-2026-06-07-v1-real-cli.md`](docs/dogfood-2026-06-07-v1-real-cli.md)):
  - ✅ Claude 侧健康(规划/共识真机正常)。
  - ✅ Stage D 计划审查门的优雅降级真机验证通过。
  - ✅ 修复了 codex 集成的 2 个真机必挂 bug(无效 CLI flag、非 TTY stdin 继承);并改进了错误透传(从 `--json` 流取真因)。
  - ⏳ **"讨论→写码→审码→测试转绿"完整闭环尚未首次真机跑通**(受 codex 账号配额所限,待重跑确认)。

简言之:核心闭环已实现、单测覆盖充分、真机基础坑已补,**差最后一步完整真机端到端验证**。

---

## 路线图 / Roadmap

- **V0** — 文档与协议 ✅
- **V1** — CLI MVP(Stage A 异构协作 → B 嵌套 subagent → C1 讨论 → C2 双栏 TUI → D 计划审查门)✅(端到端真机验证进行中)
- **V2** — Web 控制台 ✅:① 只读运行回看(`macr web` + React/Vite SPA);② 实况驱动(`/launch` 起跑、`/live` WebSocket 流式、浏览器人工门)。*(注:前端实际用 React + Vite,非早期设计里的 Next.js)*
- **V3** — 插件化 Agent / Tool / Workflow 注册
- **V4** — 领域应用衍生(编码编排、农田生态决策、科研论文辅助等)

详见 [`docs/roadmap.md`](docs/roadmap.md)。

---

## 目录导航 / Repo Layout

- [`macr/`](macr/) — 框架与 CLI 实现
- [`macr/web/`](macr/web/) — Web 控制台后端(FastAPI:运行回看 + 实况驱动),见 [`macr/web/README.md`](macr/web/README.md)
- [`frontend/`](frontend/) — Web 控制台前端(React + TypeScript + Vite)
- [`tests/`](tests/) — 测试
- [`docs/architecture.md`](docs/architecture.md) — 架构、设计哲学、原则
- [`docs/agent_roles.md`](docs/agent_roles.md) · [`docs/message_protocol.md`](docs/message_protocol.md) · [`docs/workflow_templates.md`](docs/workflow_templates.md)
- [`docs/roadmap.md`](docs/roadmap.md) — 路线图与待办
- [`docs/dogfood-2026-06-07-v1-real-cli.md`](docs/dogfood-2026-06-07-v1-real-cli.md) — 真机验证报告
- [`docs/superpowers/`](docs/superpowers/) — 各阶段设计 spec 与实现计划
- [`examples/`](examples/) — 应用示例(占位)
