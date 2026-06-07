from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class DiscussionView(Protocol):
    def plan(self, agent: str, content: dict) -> None: ...
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...
    def interjection(self, round_no: int, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def consensus(self, content: dict) -> None: ...
    def note(self, text: str) -> None: ...


class ConsoleView:
    """Default view: single-terminal turn-by-turn printing (identical to Stage C1)."""

    def __init__(self, out: Callable[[str], None] = print):
        self._out = out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None:
        self._out(f"\n━━━ {agent} · 第 0 轮(计划)━━━")
        self._out(content.get("summary", ""))
        for s in content.get("steps", []):
            self._out(f"  - {s}")

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self._out(f"\n━━━ {agent} · 第 {round_no} 轮 ━━━")
        if content.get("concerns"):
            self._out("[concerns] " + "; ".join(content["concerns"]))
        self._out("[response] " + content.get("response", ""))
        if content.get("revised_steps"):
            self._out("[revised steps] " + "; ".join(content["revised_steps"]))

    def interjection(self, round_no: int, text: str) -> None:
        self._out(f"\n━━━ 你(human)· 第 {round_no} 轮后插话 ━━━\n{text}")

    def status(self, text: str) -> None:
        self._out(text)

    def consensus(self, content: dict) -> None:
        self._out(f"\n━━━ 共识 / Consensus ━━━\n{content.get('summary', '')}")

    def note(self, text: str) -> None:
        self._out(text)


class SilentView:
    """No-op view (tests / non-interactive)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None: ...
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...
    def interjection(self, round_no: int, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def consensus(self, content: dict) -> None: ...
    def note(self, text: str) -> None: ...


class FakeView:
    """Records every display event for assertions."""

    def __init__(self):
        self.events: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, agent: str, content: dict) -> None:
        self.events.append(("plan", agent, content))

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self.events.append(("turn", agent, round_no, content))

    def interjection(self, round_no: int, text: str) -> None:
        self.events.append(("interjection", round_no, text))

    def status(self, text: str) -> None:
        self.events.append(("status", text))

    def consensus(self, content: dict) -> None:
        self.events.append(("consensus", content))

    def note(self, text: str) -> None:
        self.events.append(("note", text))
