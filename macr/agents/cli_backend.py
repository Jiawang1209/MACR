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
from macr.agents.trace import TraceSink, parse_claude_stream, parse_codex_stream, stream_error
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
    """Drives the `claude` CLI headless, with streaming output and native subagents."""

    name = "claude_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 claude_bin: str = "claude", timeout: int = 1800, enable_subagents: bool = True):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.claude_bin = claude_bin
        self.timeout = timeout
        self.enable_subagents = enable_subagents

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace: TraceSink | None = None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path
        captured: dict = {"lines": [], "subs": []}

        def call_fn(extra: str) -> dict:
            tools = "Read,Grep,Glob,Agent" if self.enable_subagents else "Read,Grep,Glob"
            argv = [self.claude_bin, "-p", prompt + extra,
                    "--output-format", "stream-json", "--verbose",
                    "--include-partial-messages", "--allowedTools", tools]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, cwd=cwd, timeout=self.timeout)
            if res.returncode != 0:
                detail = stream_error(res.stdout.splitlines(), source="claude") or res.stderr.strip()
                raise AgentError(f"claude CLI exited {res.returncode}: {detail}")
            lines = res.stdout.splitlines()
            final_text, subs = parse_claude_stream(lines)
            captured["lines"], captured["subs"] = lines, subs
            return extract_json_object(final_text)

        content = validate_with_retry(role, call_fn)
        if trace is not None:
            try:
                trace.capture(captured["lines"], captured["subs"])
            except OSError:
                # spec §9: trace capture is incidental; never fail the run on a write error
                pass
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)


class CodexCliBackend:
    """Drives the `codex` CLI in non-interactive exec mode with JSON streaming + subagents."""

    name = "codex_cli"

    def __init__(self, *, model: str | None = None, runner: ProcessRunner | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 timeout: int = 1800, enable_subagents: bool = True):
        self.model = model
        self.runner = runner or SubprocessRunner()
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.timeout = timeout
        self.enable_subagents = enable_subagents

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace: TraceSink | None = None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."
        captured: dict = {"lines": [], "subs": []}

        def call_fn(extra: str) -> dict:
            # `codex exec` is non-interactive; it has no approval flag (sandbox governs writes).
            argv = [self.codex_bin, "exec", prompt + extra,
                    "--cd", cwd, "--sandbox", self.sandbox, "--json"]
            if not self.enable_subagents:
                argv += ["-c", "features.multi_agent=false"]
            if self.model:
                argv += ["--model", self.model]
            res = self.runner.run(argv, timeout=self.timeout)
            if res.returncode != 0:
                detail = stream_error(res.stdout.splitlines(), source="codex") or res.stderr.strip()
                raise AgentError(f"codex CLI exited {res.returncode}: {detail}")
            lines = res.stdout.splitlines()
            final_text, subs = parse_codex_stream(lines)
            captured["lines"], captured["subs"] = lines, subs
            return extract_json_object(final_text)

        content = validate_with_retry(role, call_fn)
        if trace is not None:
            try:
                trace.capture(captured["lines"], captured["subs"])
            except OSError:
                # spec §9: trace capture is incidental; never fail the run on a write error
                pass
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
