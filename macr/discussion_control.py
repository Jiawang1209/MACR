from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from macr.schemas import SharedState


@dataclass
class ControlDecision:
    action: str  # "continue" | "interject" | "end" | "abort"
    interjection: str = ""


def interactive_discussion_control(
    state: SharedState,
    round_no: int,
    *,
    input_fn: Callable[[str], str] | None = None,
    printer: Callable[..., None] = print,
) -> ControlDecision:
    if input_fn is None:
        input_fn = input
    printer(f"\n── 回合 {round_no} 边界 ── [c]继续 / [i]插话 / [e]提前定稿 / [a]中止")
    choice = input_fn("> ").strip().lower()
    if choice.startswith("i"):
        text = input_fn("你的插话 / Your message: ").strip()
        return ControlDecision(action="interject", interjection=text)
    if choice.startswith("e"):
        return ControlDecision(action="end")
    if choice.startswith("a"):
        return ControlDecision(action="abort")
    return ControlDecision(action="continue")


def auto_discussion_control(
    state: SharedState, round_no: int, *, printer: Callable[..., None] = print
) -> ControlDecision:
    return ControlDecision(action="continue")
