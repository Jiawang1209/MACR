"""AgentBackend that runs the Worker (executor) inside a tmux pane and observes
it live, preserving the structured ExecutorOutput contract. Drop-in for the
codex backend in the orchestrator's implementation loop. See the Phase 1 spec
(docs/superpowers/specs/2026-06-22-mat-phase1-tmux-worker-design.md)."""
from __future__ import annotations

import os
import shlex
import tempfile
import time
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import extract_json_object, message_from_content, validate_with_retry
from macr.agents.cli_backend import _base_prompt
from macr.agents.trace import parse_codex_stream, stream_error
from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_runtime import TmuxRuntime
from macr.schemas import Message


class TmuxExecutorBackend:
    """Implements the AgentBackend protocol. Runs `codex exec … --json` in a tmux
    pane (same argv as CodexCliBackend), observes the pane live, and on process
    exit parses the captured output into the role's content model."""

    name = "tmux_executor"

    def __init__(self, runtime: TmuxRuntime, *, observer: AgentObserver | None = None,
                 codex_bin: str = "codex", sandbox: str = "workspace-write",
                 model: str | None = None, enable_subagents: bool = True,
                 timeout: int = 1800, poll_interval: float = 0.2,
                 capture_recent: int = 5000,
                 obs_sink: Callable[[dict], None] | None = None,
                 time_fn: Callable[[], float] = time.monotonic,
                 sleep_fn: Callable[[float], None] = time.sleep):
        self._rt = runtime
        self._obs = observer or AgentObserver(runtime)
        self.codex_bin = codex_bin
        self.sandbox = sandbox
        self.model = model
        self.enable_subagents = enable_subagents
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.capture_recent = capture_recent
        self._obs_sink = obs_sink
        self._time = time_fn
        self._sleep = sleep_fn
        self._seq = 0
        self._remain_set = False

    def _spawn_argv(self, prompt_file: str, cwd: str) -> list[str]:
        """tmux control-mode commands are line-based, so a multi-line prompt cannot
        go on the spawn command line. Instead the pane reads the prompt from a file
        at runtime: `bash -lc 'codex exec "$(cat FILE)" …'`. The prompt never enters
        the shell string (no injection); only paths/enums are interpolated (quoted)."""
        inner = (f'{shlex.quote(self.codex_bin)} exec "$(cat {shlex.quote(prompt_file)})" '
                 f'--cd {shlex.quote(cwd)} --sandbox {shlex.quote(self.sandbox)} --json')
        if not self.enable_subagents:
            inner += " -c features.multi_agent=false"
        if self.model:
            inner += f" --model {shlex.quote(self.model)}"
        return ["bash", "-lc", inner]

    def _emit(self, agent_id: str, attempt: int) -> None:
        if self._obs_sink is None:
            return
        d = self._obs.state_of(agent_id)
        self._obs_sink({"agent_id": agent_id, "attempt": attempt,
                        "app": d.app.value, "state": d.state.value, "confidence": d.confidence})

    def run_role(self, role, state, *, run_id, task_id, timestamp=None, trace=None) -> Message:
        prompt = _base_prompt(role, state)
        cwd = state.worktree_path or "."
        self._seq += 1
        agent_id = f"{role.name}-{run_id}-{self._seq}"
        ctrl = self._rt._c  # the TmuxControl behind the runtime
        if not self._remain_set:
            # Keep panes after the process exits so they report dead+status and
            # retain output, instead of vanishing (default remain-on-exit off).
            # Set globally BEFORE spawning so the worker pane inherits it (no race).
            ctrl.send_command("set-option -g remain-on-exit on")
            self._remain_set = True

        fd, prompt_file = tempfile.mkstemp(prefix=f"macr-{agent_id}-", suffix=".prompt")
        with os.fdopen(fd, "w") as fh:
            fh.write(prompt)
        try:
            return self._run_pane(role, state, agent_id, prompt_file, cwd, ctrl,
                                  run_id=run_id, task_id=task_id, timestamp=timestamp, trace=trace)
        finally:
            try:
                os.remove(prompt_file)
            except OSError:
                pass

    def _run_pane(self, role, state, agent_id, prompt_file, cwd, ctrl, *,
                  run_id, task_id, timestamp, trace) -> Message:
        self._rt.spawn_agent(agent_id, self._spawn_argv(prompt_file, cwd), cwd)
        pane = self._rt._panes[agent_id]

        deadline = self._time() + self.timeout
        info = None
        while True:
            infos = {i.agent_id: i for i in self._rt.list_agents()}
            for n in ctrl.take_pending():
                if n.kind == "output" and n.pane == pane:
                    self._obs.on_output(pane, n.data)
                    self._emit(agent_id, self._seq)
            info = infos.get(agent_id)
            if info is not None and info.dead:
                self._obs.refresh_from_panes(list(infos.values()))
                self._emit(agent_id, self._seq)
                break
            if self._time() > deadline:
                self._rt.kill(agent_id)
                raise AgentError(f"tmux worker '{agent_id}' timed out after {self.timeout}s")
            self._sleep(self.poll_interval)

        out = self._rt.snapshot(agent_id, recent=self.capture_recent)
        lines = out.splitlines()
        if info.dead_status not in (0, None):
            detail = stream_error(lines, source="codex") or f"exit {info.dead_status}"
            raise AgentError(f"codex worker exited {info.dead_status}: {detail}")
        final_text, subs = parse_codex_stream(lines)
        content = validate_with_retry(role, lambda extra: extract_json_object(final_text))
        if trace is not None:
            try:
                trace.capture(lines, subs)
            except OSError:
                pass
        return message_from_content(role, content, run_id=run_id, task_id=task_id, timestamp=timestamp)
