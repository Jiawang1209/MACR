from __future__ import annotations

from pydantic import ValidationError

from macr.llm import LLM, LLMError
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState
from macr.utils import now_iso


class AgentError(RuntimeError):
    """Raised when a role cannot produce schema-valid output after one retry."""


def run_agent(
    role: RoleSpec,
    state: SharedState,
    llm: LLM,
    *,
    task_id: str,
    run_id: str,
    timestamp: str | None = None,
) -> Message:
    system = role.system_prompt
    user = role.build_user(state)
    schema = role.content_model.model_json_schema()

    try:
        raw = llm.call_role(system=system, user=user, tool_name=role.tool_name, tool_schema=schema)
        model = role.content_model(**raw)
    except (ValidationError, LLMError) as first_err:
        retry_user = (
            f"{user}\n\n上一次输出未通过校验 / Previous output failed validation:\n"
            f"{first_err}\n请严格按 schema 重新提交。"
        )
        try:
            raw = llm.call_role(
                system=system, user=retry_user, tool_name=role.tool_name, tool_schema=schema
            )
            model = role.content_model(**raw)
        except (ValidationError, LLMError) as second_err:
            raise AgentError(f"{role.name} failed schema validation twice: {second_err}") from second_err

    return Message(
        task_id=task_id,
        run_id=run_id,
        agent_id=role.agent_id,
        role=role.name,
        message_type=role.message_type,
        content=model.model_dump(),
        timestamp=timestamp or now_iso(),
    )
