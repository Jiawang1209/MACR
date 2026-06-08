from __future__ import annotations

from macr.web.session import RunSession


class WebView:
    """Implements the DiscussionView protocol (used by run_discuss) and provides a
    `printer(text)` method (used by run_collab). Every callback emits a structured
    event onto the session's bus: rich `stage` events for discuss, `note` lines for
    collab's printer.
    """

    def __init__(self, session: RunSession):
        self._s = session

    # DiscussionView context-manager protocol (run_discuss does `with view:`)
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _stage(self, kind: str, label: str, *, agent: str | None = None,
               status: str | None = None, body: dict | None = None) -> None:
        self._s.emit({"type": "stage", "stage": {
            "kind": kind, "label": label, "agent": agent, "status": status, "body": body or {}}})

    def plan(self, agent: str, content: dict) -> None:
        self._stage("plan", f"Plan ({agent})", agent=agent,
                    body={"summary": content.get("summary", ""), "steps": content.get("steps", [])})

    def turn(self, agent: str, round_no: int, content: dict) -> None:
        self._stage("turn", f"Turn r{round_no} ({agent})", agent=agent,
                    body={"response": content.get("response", ""), "concerns": content.get("concerns", []),
                          "revised_steps": content.get("revised_steps", [])})

    def interjection(self, round_no: int, text: str) -> None:
        self._stage("turn", f"Human interjection r{round_no}", agent="human", body={"text": text})

    def consensus(self, content: dict) -> None:
        self._stage("consensus", "Consensus",
                    body={"summary": content.get("summary", ""), "steps": content.get("steps", []),
                          "rationale": content.get("rationale", "")})

    def review(self, attempt: int, content: dict) -> None:
        self._stage("plan_review", f"Plan Review #{attempt}", agent="codex",
                    status=content.get("decision"),
                    body={"summary": content.get("summary", ""), "findings": content.get("findings", [])})

    def evaluation(self, attempt: int, decision) -> None:
        val = getattr(decision, "value", decision)
        self._stage("evaluator", f"Evaluator #{attempt}", status=val)

    def status(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})

    def note(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})

    def printer(self, text: str) -> None:
        self._s.emit({"type": "note", "text": text})
