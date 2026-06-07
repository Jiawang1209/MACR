# Stage B 全自动托管 `/goal`

> 用途:把 MACR Stage B(原生嵌套 subagent + 可追踪)从已批准的 spec 一直自主做到合并回 `main`。
> 用法:把下面代码块里的整段(含开头的 `/goal`)粘贴进输入框发送,然后即可离开。

---

## 粘贴这段

```
/goal 自主完成 MACR Stage B(原生嵌套 subagent + 可追踪)的全流程实现,从已批准的 spec 一直做到合并回 main。

spec(已批准、已提交):docs/superpowers/specs/2026-06-07-macr-stage-b-nested-subagents-design.md

执行链路:
1. 用 superpowers:writing-plans 基于该 spec 写出 Stage B 实现计划,存到 docs/superpowers/plans/ 并提交。
2. 用 superpowers:subagent-driven-development 执行:先从 main 切分支 feat/stage-b-subagents,再逐任务 TDD(先写失败测试→跑红→实现→跑绿→commit),每个任务用 .venv/bin/pytest 作为客观门。
3. 所有任务完成后,用 oh-my-claudecode:code-reviewer 做一次完整 code review,修复所有 High/Critical findings,再次确认全量测试绿。
4. 用 superpowers:finishing-a-development-branch 把分支合并回 main(本地),在合并后的 main 上重跑测试确认绿,删除分支。**不要 push**(我自己 push)。

硬性约束:
- commit message 一律纯净,**绝不带 Co-Authored-By 或任何 AI 署名**。
- 依赖只在项目 .venv,所有 python/pytest 走 .venv/bin/...,绝不污染 base/miniforge 环境。
- 一次只跑一个 git 命令(此仓库出现过 index.lock 竞争)。
- 不破坏 V1(macr run)与 Stage A 现有行为与测试,全程保持绿。

明确不做(spec §7):
- **不要运行真实的 claude / codex CLI**(未登录、需交互)。事件 schema 的真实校准留给我手动冒烟。
- 因此:解析器保持防御式,所有测试用合成事件流 + FakeProcessRunner + 临时 git 仓库;在最终总结里明确写出"真实 CLI 冒烟校准 = 待办(需要我本人跑 scripts/smoke_collab.py)"。

收尾:完成后留一段简短总结——做了哪些模块、测试数、合并的 commit、以及"待我手动做的 smoke 校准"清单。如果遇到 spec 无法消解的真实歧义,停下并留清楚说明,不要瞎猜。
```

---

## 它会做 / 不会做

- **会留给你的**:Stage B 代码合并进本地 `main`,全量测试绿,**未 push** —— 醒来后 `git push` 即可。
- **故意不做**:不碰真实 `claude`/`codex`(需要你登录的交互环境)。spec §7 的"用真实事件流校准解析器"作为**待办**留给你。

## 醒来后的手动校准(唯一待办)

```bash
.venv/bin/python scripts/smoke_collab.py <一个真实git仓库> "pytest -q" "一个小任务"
# 然后看 .macr/runs/<id>/subagents/*.events.jsonl
# 若真实事件键名与解析器假设有出入,再微调 macr/agents/trace.py(很小的活)
```

## 提醒

- **托管 = 放权**:全自动会一口气产生十几个 subagent 任务 + 评审 + 修复,token 消耗不小,符合"完全托管"预期。
- **范围安全**:严格限定在 Stage B 这一份已批准 spec 内,且不 push、不碰真实外部 CLI,休息期间不会有不可逆或对外动作。
