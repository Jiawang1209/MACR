from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from macr.agent import AgentError
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState
from macr.utils import now_iso


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class ProcessRunner(Protocol):
    def run(self, argv: list[str], *, cwd: str | None = None,
            input_text: str | None = None, timeout: int | None = None) -> ProcResult: ...


class SubprocessRunner:
    """Real process runner wrapping subprocess.run."""

    def run(self, argv, *, cwd=None, input_text=None, timeout=None) -> ProcResult:
        proc = subprocess.run(
            argv, cwd=cwd, input=input_text,
            capture_output=True, text=True, timeout=timeout,
        )
        return ProcResult(proc.returncode, proc.stdout, proc.stderr)


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def run_role(self, role: RoleSpec, state: SharedState, *,
                 run_id: str, task_id: str, timestamp: str | None = None) -> Message: ...


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from text, tolerating code fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in output: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def validate_with_retry(role: RoleSpec, call_fn: Callable[[str], dict]) -> BaseModel:
    """call_fn(extra_note) -> raw dict. Validate into role.content_model with one retry."""
    raw = call_fn("")
    try:
        return role.content_model(**raw)
    except ValidationError as first:
        note = (
            "\n\nPrevious output failed validation:\n"
            f"{first}\nReturn corrected JSON only, matching the schema."
        )
        raw = call_fn(note)
        try:
            return role.content_model(**raw)
        except ValidationError as second:
            raise AgentError(f"{role.name} failed schema validation twice: {second}") from second


def message_from_content(role: RoleSpec, content: BaseModel, *,
                         run_id: str, task_id: str, timestamp: str | None = None) -> Message:
    return Message(
        task_id=task_id, run_id=run_id, agent_id=role.agent_id, role=role.name,
        message_type=role.message_type, content=content.model_dump(mode="json"),
        timestamp=timestamp or now_iso(),
    )


# --- Test doubles ---

class FakeProcessRunner:
    """Returns scripted ProcResults in order; records calls."""

    def __init__(self, results: list[ProcResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    def run(self, argv, *, cwd=None, input_text=None, timeout=None) -> ProcResult:
        self.calls.append({"argv": list(argv), "cwd": cwd, "input_text": input_text})
        if not self._results:
            raise AssertionError("FakeProcessRunner exhausted")
        return self._results.pop(0)


class FakeAgentBackend:
    """AgentBackend test double: scripted content per role name; optional on_run side effect."""

    name = "fake"

    def __init__(self, scripted: dict[str, list[dict]],
                 on_run: Callable[[RoleSpec, SharedState], None] | None = None):
        self._scripted = {k: list(v) for k, v in scripted.items()}
        self._on_run = on_run
        self.calls: list[str] = []

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        self.calls.append(role.name)
        if self._on_run is not None:
            self._on_run(role, state)
        if not self._scripted.get(role.name):
            raise AssertionError(f"FakeAgentBackend has no scripted output for role '{role.name}'")
        content = self._scripted[role.name].pop(0)
        return Message(
            task_id=task_id, run_id=run_id, agent_id=role.agent_id, role=role.name,
            message_type=role.message_type, content=content, timestamp=timestamp or "t",
        )
