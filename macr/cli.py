from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from macr.human_gate import interactive_human_gate
from macr.llm import LLMError
from macr.orchestrator import run_task


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="macr", description="MACR multi-agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run one MACR task end-to-end")
    run_p.add_argument("task", help="the task description")
    run_p.add_argument("--max-revisions", type=int, default=2)
    run_p.add_argument("--model", default="claude-sonnet-4-6")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, llm=None, human_gate=interactive_human_gate) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        from macr.llm import AnthropicLLM

        llm = AnthropicLLM(model=args.model)

    runs_dir = Path(".macr/runs")
    try:
        state = run_task(
            args.task, llm, runs_dir,
            max_revisions=args.max_revisions, human_gate=human_gate,
        )
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface any failure as non-zero
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0 if state.human_feedback and state.human_feedback.decision == "approve" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
