# V2 子项目 ① — 只读 Run 查看器 设计 (2026-06-08)

## 背景

V1 是 CLI MVP:`run`/`collab`/`discuss` 三命令把多 agent 协作全过程落盘到
`.macr/runs/<run_id>/`(`state.json` 为权威转储 + 渲染好的 md 文件 + `discussion/`、
`subagents/` 子目录)。现在看一个 run 只能翻文件夹。

V2 路线图是"Web 控制台"。用户选定**完整控制台**(查看 + 实时驱动 + 多运行管理),
因体量过大,拆为三个有依赖顺序的子项目,本 spec 只覆盖 **①**:

| 子项目 | 内容 | 依赖 |
|---|---|---|
| **① 只读 Run 查看器**(本 spec) | 后端读 `.macr/runs/`,前端渲染 run 列表 + 每个 run 的结构化时间线 | 无 |
| ② 实时驱动 | 后端异步包装 orchestrator,WebSocket 流式推送,浏览器人工门 | ① 的数据模型 + UI 骨架 |
| ③ 多运行管理 | 并发 run、队列、状态面板、取消 | ② 的驱动 |

每个子项目独立 spec → plan → 实现。架构按"②③ 能复用 ①"来定。

## 目标

一个本地 Web 查看器:浏览历史 run、按结构化时间线查看每个 run 的任务流、各 agent 输出、
diff、测试、决策链、人工门结果。**只读**,不驱动、不实时流。

## 技术栈(已定)

- **后端**:Python / FastAPI,包在现有 `macr` 包内(`macr/web/`)。
- **前端**:Vite + React + TypeScript SPA(`frontend/`),构建为静态资源由 FastAPI 托管。
- **入口**:新增 `macr web` CLI 子命令,起 FastAPI 服务 `/api/*` + SPA `/`。本地 localhost、无鉴权。

## 关键设计决定

1. **`state.json` 是单一数据源**。它已含 `agent_outputs` / `reviews` / `decisions` /
   `test_results` / `diffs` / `subagents` / `discussion` / `consensus` / `human_feedback` /
   `final_output`。后端 normalizer 只解析它即可重建整条时间线;run 目录里的 md 文件只用于
   "下载原始产物",不作渲染数据源。
2. **归一化时间线模型**。三种命令流(run/collab/discuss)都映射到同一个有序 `Stage[]` 序列,
   前端通用渲染。② 的实时流后续可复用同一 `RunDetail` 模型(orchestrator 本就增量写盘)。
3. **前后端分目录**:`macr/web/`(Python)+ `frontend/`(Vite/TS)。

## 架构

```
.macr/runs/<id>/state.json ──read──▶ FastAPI (macr/web)
                                         │ normalize → RunSummary / RunDetail
                                         ▼
                                   REST /api/runs[...]
                                         ▼
                              Vite+React SPA(列表页 + 时间线详情页)
```

## 组件

### 后端 `macr/web/`(Python)
- `models.py` — Pydantic API 模型:`RunSummary`(列表用)、`RunDetail`、`Stage`。
- `runs.py` — normalizer:读一个 run 的 `state.json` → 推断 `command_type` → 产出
  `RunDetail`(meta + 有序 `stages[]` + `artifacts[]`)。
- `app.py` — FastAPI app + 三端点。
- `macr web` 子命令(在 `macr/cli.py` 注册):`--runs-dir`(默认 `.macr/runs`)、`--host`、
  `--port`;起 uvicorn,挂 `/api/*` 和 SPA 静态。

### 前端 `frontend/`(Vite+React+TS)
- `RunList` — run 列表:id、类型徽章、最终决策、任务摘要;倒序(最近在前);坏 run 标灰可点进。
- `RunDetail` — 结构化时间线:每阶段一张卡,markdown 渲染 agent 输出、diff 语法高亮、
  测试徽章、决策链、人工门结果。
- 极简路由:列表 `/` ↔ 详情 `/runs/:id`;零状态管理库(fetch + local state)。

## 数据流

**`GET /api/runs`**:扫 `runs-dir` 子目录,读各自 `state.json` 头部字段,返回 `RunSummary[]`
(run_id、command_type、task/topic、最终决策、有无 worktree),按 run_id 倒序。读不动/损坏的
目录跳过并标 `broken: true`,不拖垮整页。

**`GET /api/runs/{id}`**:读 `state.json` → normalizer → `RunDetail`:
- `command_type` 推断:有 `discussion`/`consensus` → `discuss`;有 `target_repo`+`diffs` 但无
  `discussion` → `collab`;否则 `run`。
- `stages[]` 按真实执行序重建:从 `agent_outputs`/`decisions`/`test_results`/`diffs` 按 attempt
  交错(executor#n → tests#n → reviewer#n → evaluator#n);discuss 额外前插 plan/turn/
  consensus/plan-review 段(来自 `discussion[]` + `reviews` + `consensus`)。
- `artifacts[]`:run 目录里可下载的原始文件(`diff.v*.patch`、`test.v*.log`、`final.md`)。

**`GET /api/runs/{id}/artifacts/{name}`**:白名单校验 `name`(只允许该 run 目录内已知文件名,
防路径穿越),返回纯文本。

## 错误处理

- run 不存在 → 404;`state.json` 缺失/损坏 → 422 带清晰 message(不抛 500)。
- `artifacts/{name}` 路径穿越(`..`/绝对路径/不在白名单)→ 400。
- 前端:列表/详情各有 loading / error / empty 三态;坏 run 标灰可点进看错误,不静默吞。

## 测试策略(TDD)

- **后端(重点,全 TDD)**:normalizer 对 run/collab/discuss 三种 fixture run 目录各测一遍
  (测试内造 `state.json`);FastAPI 用 `TestClient` 测三端点的正常 / 404 / 422 / 路径穿越。
- **前端(轻)**:Vitest + React Testing Library,`RunDetail` 时间线 + `RunList` 各一个组件
  渲染测试(喂 fixture,断言阶段卡片/列表项出现)。挡明显回归即可,不追高覆盖。

## 明确排除(YAGNI,本子项目不做)

- 实时驱动 / WebSocket / 浏览器人工门(→ ②)
- 多 run 并发管理 / 队列 / 取消(→ ③)
- 鉴权 / 多用户 / 部署(本地 localhost 工具)
- 可视化 DAG 图(已选结构化时间线)
- 编辑/删除 run、搜索/过滤(列表先只做倒序;过滤可留作 ① 后续小增量)

## 验收

- `macr web` 启动后,`/` 展示 run 列表,点进任一 run 看到结构化时间线。
- run/collab/discuss 三种 run 的时间线都正确重建并渲染。
- 坏 run 不拖垮列表;路径穿越被挡;不存在的 run 给 404。
- 后端 normalizer + 端点全测绿;前端两个组件渲染测试绿。
