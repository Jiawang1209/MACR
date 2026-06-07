from __future__ import annotations

import json

from macr.agent import AgentError
from macr.agents.base import (
    ProcessRunner,
    SubprocessRunner,
    extract_json_object,
    message_from_content,
    validate_with_retry,
)
from macr.roles import RoleSpec
from macr.schemas import Message, SharedState


def _schema_instruction(role: RoleSpec) -> str:
    schema = role.content_model.model_json_schema()
    return (
        "\n\n只输出一个符合以下 JSON Schema 的 JSON 对象,不要任何解释或额外文本:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _base_prompt(role: RoleSpec, state: SharedState) -> str:
    return f"{role.system_prompt}\n\n{role.build_user(state)}{_schema_instruction(role)}"


class ClaudeCliBackend:
    """Drives the `claude` CLI in headless print mode."""

    name = "claude_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 claude_bin: str = "claude", timeout: int = 1800):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.claude_bin = claude_bin
        self.timeout = timeout

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        prompt = _base_prompt(role, state)

        def call_fn(extra: str) -> dict:
            argv = [self.claude_bin, "-p", prompt + extra, "--output-format", "json"]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"claude CLI exited {res.returncode}: {res.stderr.strip()}")
            return self._parse(res.stdout)

        content = validate_with_retry(role, call_fn)
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)

    @staticmethod
    def _parse(stdout: str) -> dict:
        try:
            envelope = json.loads(stdout)
            inner = envelope.get("result", stdout) if isinstance(envelope, dict) else stdout
        except json.JSONDecodeError:
            inner = stdout
        return extract_json_object(inner)


class CodexCliBackend:
    """Drives the `codex` CLI in non-interactive exec mode inside a worktree."""

    name = "codex_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 approval: str = "never", timeout: int = 1800):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.approval = approval
        self.timeout = timeout

    def run_role(self, role, state, *, run_id, task_id, timestamp=None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."

        def call_fn(extra: str) -> dict:
            argv = [
                self.codex_bin, "exec", prompt + extra,
                "--cd", cwd,
                "--sandbox", self.sandbox,
                "--ask-for-approval", self.approval,
            ]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                raise AgentError(f"codex CLI exited {res.returncode}: {res.stderr.strip()}")
            return extract_json_object(res.stdout)

        content = validate_with_retry(role, call_fn)
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
