from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from macr.schemas import (
    EvaluatorOutput,
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


@dataclass(frozen=True)
class RoleSpec:
    name: str
    agent_id: str
    tool_name: str
    message_type: MessageType
    content_model: type[BaseModel]
    system_prompt: str
    build_user: Callable[[SharedState], str]


def _latest(state: SharedState, bucket: str) -> dict | None:
    items = state.agent_outputs.get(bucket, [])
    return items[-1] if items else None


def _planner_user(state: SharedState) -> str:
    return f"任务 / Task:\n{state.user_query}\n\n请制定方案:总结、分步骤、所需工具、潜在风险。"


def _executor_user(state: SharedState) -> str:
    plan = _latest(state, "planner") or {}
    steps = "\n".join(f"- {s}" for s in plan.get("steps", []))
    parts = [
        f"任务 / Task:\n{state.user_query}",
        f"方案步骤 / Plan steps:\n{steps}",
    ]
    review = _latest(state, "reviewer")
    if review is not None:
        findings = "\n".join(
            f"- {f.get('issue')}: {f.get('recommendation')}" for f in review.get("findings", [])
        )
        parts.append(
            "上一轮审查反馈 / Previous review feedback:\n"
            f"{review.get('summary', '')}\n{findings}\n请据此修订产物。"
        )
    parts.append("请产出 artifact(正文/代码片段)、notes 与 evidence。")
    return "\n\n".join(parts)


def _reviewer_user(state: SharedState) -> str:
    ex = _latest(state, "executor") or {}
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"待审产物 / Artifact to review:\n{ex.get('artifact', '')}\n\n"
        "请审查:逻辑错误、是否偏离任务、是否缺证据;给出 findings 与 decision(approve/needs_fix)。"
    )


def _evaluator_user(state: SharedState) -> str:
    ex = _latest(state, "executor") or {}
    rev = _latest(state, "reviewer") or {}
    findings = "\n".join(f"- {f.get('issue')}" for f in rev.get("findings", []))
    return (
        f"任务 / Task:\n{state.user_query}\n\n"
        f"产物 / Artifact:\n{ex.get('artifact', '')}\n\n"
        f"审查意见 / Review:\n{rev.get('summary', '')}\n{findings}\n\n"
        "请判定 decision(PASS/NEEDS_FIX/BLOCKED)、reasons 与 confidence(0-1)。"
    )


PLANNER = RoleSpec(
    name="planner", agent_id="planner_agent", tool_name="submit_plan",
    message_type=MessageType.PLAN, content_model=PlannerOutput,
    system_prompt=(
        "你是 MACR 的 Planner 智能体。只负责规划:把任务拆成清晰步骤、列出所需工具与风险。"
        "不要执行任务,不要评判合格。必须通过 submit_plan 工具提交结构化结果。"
    ),
    build_user=_planner_user,
)

EXECUTOR = RoleSpec(
    name="executor", agent_id="executor_agent", tool_name="submit_result",
    message_type=MessageType.RESULT, content_model=ExecutorOutput,
    system_prompt=(
        "你是 MACR 的 Executor 智能体。严格按既定方案执行,产出真实的文本/代码片段 artifact,"
        "并记录 notes 与 evidence。若收到审查反馈,请据此修订。不要自评是否合格。"
        "必须通过 submit_result 工具提交结构化结果。"
    ),
    build_user=_executor_user,
)

REVIEWER = RoleSpec(
    name="reviewer", agent_id="reviewer_agent", tool_name="submit_review",
    message_type=MessageType.REVIEW, content_model=ReviewerOutput,
    system_prompt=(
        "你是 MACR 的 Reviewer 智能体。只审查产物,不重写产物。检查逻辑错误、是否偏离任务、"
        "证据是否充分;每个 finding 含 level/issue/evidence/recommendation;给出 decision。"
        "必须通过 submit_review 工具提交结构化结果。"
    ),
    build_user=_reviewer_user,
)

EVALUATOR = RoleSpec(
    name="evaluator", agent_id="evaluator_agent", tool_name="submit_evaluation",
    message_type=MessageType.EVALUATION, content_model=EvaluatorOutput,
    system_prompt=(
        "你是 MACR 的 Evaluator 智能体,质量门控。基于产物+审查意见判定 PASS/NEEDS_FIX/BLOCKED,"
        "给出 reasons 与 confidence。证据严重不足或任务不可达时用 BLOCKED。不要执行任务。"
        "必须通过 submit_evaluation 工具提交结构化结果。"
    ),
    build_user=_evaluator_user,
)

ROLES: dict[str, RoleSpec] = {
    r.name: r for r in (PLANNER, EXECUTOR, REVIEWER, EVALUATOR)
}
