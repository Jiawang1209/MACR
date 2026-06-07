from __future__ import annotations

from typing import Callable

from macr.schemas import HumanFeedback, SharedState
from macr.utils import now_iso


def _latest_artifact(state: SharedState) -> str:
    items = state.agent_outputs.get("executor", [])
    return items[-1].get("artifact", "") if items else ""


def _prompt_decision(
    input_fn: Callable[[str], str], printer: Callable[..., None], ts: str
) -> HumanFeedback:
    printer("\n[a]pprove / [r]eject / [e]dit")
    choice = input_fn("> ").strip().lower()
    if choice.startswith("r"):
        reason = input_fn("Reject reason: ").strip()
        return HumanFeedback(decision="reject", feedback=reason, timestamp=ts)
    if choice.startswith("e"):
        fb = input_fn("Feedback / edits: ").strip()
        return HumanFeedback(decision="approve", feedback=fb, timestamp=ts)
    return HumanFeedback(decision="approve", feedback="", timestamp=ts)


def interactive_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] | None = None,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    if input_fn is None:
        input_fn = input
    ts = timestamp or now_iso()
    printer("\n===== Human Gate =====")
    printer(f"Task: {state.user_query}")
    printer("Final artifact:\n")
    printer(_latest_artifact(state))
    return _prompt_decision(input_fn, printer, ts)


def collab_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] | None = None,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    if input_fn is None:
        input_fn = input
    ts = timestamp or now_iso()
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    printer("\n===== Human Gate (collab) =====")
    printer(f"Task: {state.user_query}")
    printer(f"Worktree: {state.worktree_path}")
    printer("\n--- Final diff ---")
    printer(diff)
    printer(f"\n--- Tests: passed={tr.get('passed')} exit={tr.get('exit_code')} ---")
    return _prompt_decision(input_fn, printer, ts)


def consensus_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] | None = None,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    if input_fn is None:
        input_fn = input
    ts = timestamp or now_iso()
    c = state.consensus or {}
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(c.get("steps", []), 1))
    printer("\n===== Human Gate (consensus) =====")
    printer(f"Topic: {state.topic}")
    printer(f"\n--- Consensus ---\n{c.get('summary', '')}\n{steps}")
    if c.get("open_questions"):
        printer("Open questions: " + "; ".join(c.get("open_questions", [])))
    if state.reviews:
        rv = state.reviews[-1]
        ev = state.decisions[-1].get("decision") if state.decisions else "?"
        printer(f"\n--- Plan review / 计划审查 ---")
        printer(f"Reviewer decision: {rv.get('decision', '?')}  (evaluator: {ev})")
        blocking = [f for f in rv.get("findings", []) if f.get("level") == "blocking"]
        if blocking:
            printer("Blocking:")
            for f in blocking:
                printer(f"  - {f.get('issue')} → {f.get('recommendation')}")
    return _prompt_decision(input_fn, printer, ts)
