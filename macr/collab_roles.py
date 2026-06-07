from __future__ import annotations

from macr.roles import RoleSpec
from macr.schemas import (
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def _latest(state: SharedState, bucket: str) -> dict | None:
    items = state.agent_outputs.get(bucket, [])
    return items[-1] if items else None


def _planner_user(state: SharedState) -> str:
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        "目标代码仓库已在工作目录就绪。请制定实现方案:summary(总述)、"
        "steps(分步骤)、tools_needed、risks。不要写代码,只出方案。"
    )


def _executor_user(state: SharedState) -> str:
    plan = _latest(state, "planner") or {}
    steps = "\n".join(f"- {s}" for s in plan.get("steps", []))
    parts = [
        f"任务 / Task:\n{state.user_query}",
        f"实现方案 / Plan steps:\n{steps}",
        "请直接在当前工作目录(git worktree)中修改/新增文件来实现该方案;"
        "完成后用 JSON 汇总 artifact(改动说明)、notes、evidence(改了哪些文件)。",
    ]
    review = _latest(state, "reviewer")
    if review is not None:
        findings = "\n".join(
            f"- {f.get('issue')}: {f.get('recommendation')}" for f in review.get("findings", [])
        )
        parts.append(
            "上一轮审查反馈 / Previous review feedback:\n"
            f"{review.get('summary', '')}\n{findings}"
        )
    if state.test_results:
        tr = state.test_results[-1]
        if not tr.get("passed", False):
            parts.append("上一轮测试失败日志 / Previous test failure log:\n" + tr.get("log", ""))
    parts.append("请据此修订代码。")
    return "\n\n".join(parts)


def _reviewer_user(state: SharedState) -> str:
    diff = state.diffs[-1] if state.diffs else "(无改动 / no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    test_line = (
        f"passed={tr.get('passed')}, exit_code={tr.get('exit_code')}\n{tr.get('log', '')}"
        if tr else "(未运行 / not run)"
    )
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"本轮代码改动 (git diff):\n{diff}\n\n"
        f"测试结果 / Test result:\n{test_line}\n\n"
        "请综合 diff 与测试结果审查:逻辑错误、是否偏离任务、是否缺证据;"
        "给出 findings(含 level=blocking/non_blocking)与 decision(approve/needs_fix)。"
    )


PLANNER_C = RoleSpec(
    name="planner", agent_id="claude_planner", tool_name="submit_plan",
    message_type=MessageType.PLAN, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 的 Planner(由 Claude 扮演)。只出实现方案,不写代码,不评判合格。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_planner_user,
)

EXECUTOR_C = RoleSpec(
    name="executor", agent_id="codex_executor", tool_name="submit_result",
    message_type=MessageType.RESULT, content_model=ExecutorOutput,
    system_prompt=(
        "你是 MACR 的 Executor(由 Codex 扮演)。在当前工作目录中真实修改/新增文件实现方案,"
        "若有审查反馈或失败测试则据此修订。完成后输出符合 JSON Schema 的 artifact/notes/evidence。"
    ),
    build_user=_executor_user,
)

REVIEWER_C = RoleSpec(
    name="reviewer", agent_id="claude_reviewer", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 的 Reviewer(由 Claude 扮演)。只审查 diff 与测试结果,不改代码。"
        "输出必须是符合给定 JSON Schema 的对象。"
    ),
    build_user=_reviewer_user,
)

COLLAB_ROLES: dict[str, RoleSpec] = {r.name: r for r in (PLANNER_C, EXECUTOR_C, REVIEWER_C)}
