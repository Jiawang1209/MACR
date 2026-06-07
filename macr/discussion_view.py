from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class DiscussionView(Protocol):
    def plan(self, agent: str, content: dict) -> None: ...
    def turn(self, agent: str, round_no: int, content: dict) -> None: ...
    def interjection(self, round_no: int, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def consensus(self, content: dict) -> None: ...
    def review(self, attempt: int, content: dict) -> None: ...
    def evaluation(self, attempt: int, decision) -> None: ...
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

    def review(self, attempt: int, content: dict) -> None:
        self._out(f"\n━━━ 计划审查 (Codex) · 第 {attempt} 次 ━━━\n{content.get('summary', '')}")
        for f in content.get("findings", []):
            self._out(f"  - ({f.get('level')}) {f.get('issue')} → {f.get('recommendation')}")

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self._out(f"[评估] 第 {attempt} 次审查判定:{val}")

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
    def review(self, attempt: int, content: dict) -> None: ...
    def evaluation(self, attempt: int, decision) -> None: ...
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

    def review(self, attempt: int, content: dict) -> None:
        self.events.append(("review", attempt, content))

    def evaluation(self, attempt: int, decision) -> None:
        self.events.append(("evaluation", attempt, decision))

    def note(self, text: str) -> None:
        self.events.append(("note", text))


class TwoPaneView:
    """rich two-pane live view: Claude (left) / Codex (right) + bottom status panel.

    Falls back to buffer-only (no Live) when `enabled` is False or stdout is not a TTY.
    Provides control/gate methods that pause the Live around interactive input.
    """

    def __init__(self, *, console=None, enabled: bool | None = None, topic: str = ""):
        from rich.console import Console

        self.console = console or Console()
        self.enabled = self.console.is_terminal if enabled is None else enabled
        self.topic = topic
        self.claude_lines: list[str] = []
        self.codex_lines: list[str] = []
        self.status_lines: list[str] = []
        self._live = None

    def __enter__(self):
        if self.enabled:
            from rich.live import Live

            self._live = Live(self._render(), console=self.console, refresh_per_second=8, screen=False)
            self._live.__enter__()
        return self

    def __exit__(self, *exc):
        if self._live is not None:
            self._live.__exit__(*exc)
            self._live = None
        return False

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _render(self):
        from rich.layout import Layout
        from rich.panel import Panel

        layout = Layout()
        layout.split_column(
            Layout(Panel(self.topic or "MACR discuss"), size=3, name="header"),
            Layout(name="body"),
            Layout(Panel("\n".join(self.status_lines[-12:]), title="你 / 状态"), size=10, name="status"),
        )
        layout["body"].split_row(
            Layout(Panel("\n".join(self.claude_lines[-60:]), title="Claude")),
            Layout(Panel("\n".join(self.codex_lines[-60:]), title="Codex")),
        )
        return layout

    def _pane(self, agent: str) -> list[str]:
        return self.claude_lines if agent == "claude" else self.codex_lines

    def plan(self, agent: str, content: dict) -> None:
        pane = self._pane(agent)
        pane.append(f"[第0轮 计划] {content.get('summary', '')}")
        pane.extend(f"  - {s}" for s in content.get("steps", []))
        self._refresh()

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        pane = self._pane(agent)
        pane.append(f"[第{round_no}轮]")
        if content.get("concerns"):
            pane.append("concerns: " + "; ".join(content["concerns"]))
        pane.append("response: " + content.get("response", ""))
        if content.get("revised_steps"):
            pane.append("revised: " + "; ".join(content["revised_steps"]))
        self._refresh()

    def interjection(self, round_no: int, text: str) -> None:
        self.status_lines.append(f"你(第{round_no}轮后): {text}")
        self._refresh()

    def status(self, text: str) -> None:
        self.status_lines.append(text)
        self._refresh()

    def consensus(self, content: dict) -> None:
        self.status_lines.append("共识 / Consensus: " + content.get("summary", ""))
        self._refresh()

    def review(self, attempt: int, content: dict) -> None:
        self.status_lines.append(f"计划审查#{attempt}: {content.get('summary', '')}")
        for f in content.get("findings", []):
            self.status_lines.append(f"  ({f.get('level')}) {f.get('issue')}")
        self._refresh()

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self.status_lines.append(f"评估#{attempt}: {val}")
        self._refresh()

    def note(self, text: str) -> None:
        self.status_lines.append(text)
        self._refresh()

    def _paused(self, fn):
        if self._live is not None:
            self._live.stop()
        try:
            return fn()
        finally:
            if self._live is not None:
                self._live.start()

    def control(self, state, round_no, *, printer=None):
        from macr.discussion_control import interactive_discussion_control

        return self._paused(lambda: interactive_discussion_control(state, round_no))

    def consensus_gate(self, state, *, printer=None):
        from macr.human_gate import consensus_human_gate

        return self._paused(lambda: consensus_human_gate(state))

    def final_gate(self, state, *, printer=None):
        from macr.human_gate import collab_human_gate

        return self._paused(lambda: collab_human_gate(state))
