from __future__ import annotations

from typing import Callable

from macr.schemas import HumanFeedback, SharedState
from macr.utils import now_iso


def _latest_artifact(state: SharedState) -> str:
    items = state.agent_outputs.get("executor", [])
    return items[-1].get("artifact", "") if items else ""


def interactive_human_gate(
    state: SharedState,
    *,
    input_fn: Callable[[str], str] = input,
    printer: Callable[..., None] = print,
    timestamp: str | None = None,
) -> HumanFeedback:
    ts = timestamp or now_iso()
    printer("\n===== Human Gate =====")
    printer(f"Task: {state.user_query}")
    printer("Final artifact:\n")
    printer(_latest_artifact(state))
    printer("\n[a]pprove / [r]eject / [e]dit")

    choice = input_fn("> ").strip().lower()
    if choice.startswith("r"):
        reason = input_fn("Reject reason: ").strip()
        return HumanFeedback(decision="reject", feedback=reason, timestamp=ts)
    if choice.startswith("e"):
        fb = input_fn("Feedback / edits: ").strip()
        return HumanFeedback(decision="approve", feedback=fb, timestamp=ts)
    return HumanFeedback(decision="approve", feedback="", timestamp=ts)
