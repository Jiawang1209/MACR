from __future__ import annotations

from macr.agent import run_agent
from macr.llm import LLM
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState


class ApiBackend:
    """Dormant API seam: adapts the V1 API tool-use path to the AgentBackend interface.

    Not used by `macr collab` (which is CLI-only). Kept so a future API path can be
    selected through the same AgentBackend interface without refactoring.
    """

    name = "api"

    def __init__(self, llm: LLM):
        self._llm = llm

    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None) -> Message:
        return run_agent(role, state, self._llm, task_id=task_id, run_id=run_id, timestamp=timestamp)
