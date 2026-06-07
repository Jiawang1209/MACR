from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

from macr.human_gate import collab_human_gate, interactive_human_gate
from macr.llm import LLMError
from macr.orchestrator import run_task


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="macr", description="MACR multi-agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one MACR task end-to-end (single-model API path)")
    run_p.add_argument("task", help="the task description")
    run_p.add_argument("--max-revisions", type=int, default=2)
    run_p.add_argument("--model", default="claude-sonnet-4-6")

    collab_p = sub.add_parser("collab", help="Claude+Codex heterogeneous code collaboration (CLI-only)")
    collab_p.add_argument("task", help="the task description")
    collab_p.add_argument("--repo", required=True, help="path to the target git repository")
    collab_p.add_argument("--test-cmd", required=True, help="test command, e.g. 'pytest -q'")
    collab_p.add_argument("--max-revisions", type=int, default=2)
    collab_p.add_argument("--claude-model", default=None)
    collab_p.add_argument("--codex-model", default=None)
    collab_p.add_argument("--timeout", type=int, default=1800)
    collab_p.add_argument("--no-subagents", action="store_true",
                          help="disable native subagents in Claude/Codex")
    return parser.parse_args(argv)


def _run_command(args, *, llm, human_gate) -> int:
    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        from macr.llm import AnthropicLLM

        llm = AnthropicLLM(model=args.model)
    runs_dir = Path(".macr/runs")
    try:
        state = run_task(args.task, llm, runs_dir, max_revisions=args.max_revisions, human_gate=human_gate)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


def _collab_command(args, *, claude_backend, codex_backend, human_gate) -> int:
    from macr.collab_orchestrator import run_collab

    if claude_backend is None or codex_backend is None:
        missing = [b for b in ("claude", "codex") if shutil.which(b) is None]
        if missing:
            print(f"error: required CLI not found on PATH: {', '.join(missing)}", file=sys.stderr)
            return 2
        from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend

        enable = not getattr(args, "no_subagents", False)
        if claude_backend is None:
            claude_backend = ClaudeCliBackend(
                model=args.claude_model, timeout=args.timeout, enable_subagents=enable)
        if codex_backend is None:
            codex_backend = CodexCliBackend(
                model=args.codex_model, timeout=args.timeout, enable_subagents=enable)

    try:
        state = run_collab(
            args.task,
            repo=Path(args.repo).resolve(),
            test_cmd=shlex.split(args.test_cmd),
            claude_backend=claude_backend,
            codex_backend=codex_backend,
            runs_dir=Path(".macr/runs").resolve(),
            worktrees_dir=Path(".macr/worktrees").resolve(),
            max_revisions=args.max_revisions,
            human_gate=human_gate,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure as non-zero
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


def main(argv: list[str] | None = None, *, llm=None,
         claude_backend=None, codex_backend=None,
         human_gate=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "collab":
        gate = human_gate or collab_human_gate
        return _collab_command(args, claude_backend=claude_backend, codex_backend=codex_backend, human_gate=gate)
    gate = human_gate or interactive_human_gate
    return _run_command(args, llm=llm, human_gate=gate)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
