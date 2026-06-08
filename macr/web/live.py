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


import threading
from pathlib import Path

from macr.schemas import HumanFeedback


def _final_gate_data(state) -> dict:
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    return {"worktree": state.worktree_path, "diff": diff,
            "tests": {"passed": tr.get("passed"), "exit_code": tr.get("exit_code")}}


def _consensus_gate_data(state) -> dict:
    c = state.consensus or {}
    review = state.reviews[-1] if state.reviews else {}
    return {"summary": c.get("summary", ""), "steps": c.get("steps", []),
            "open_questions": c.get("open_questions", []),
            "plan_review_decision": review.get("decision")}


def _make_gate(session: RunSession, gate: str, data_fn):
    def gate_fn(state, *, printer=None) -> HumanFeedback:
        return session.request_gate(gate, data_fn(state))
    return gate_fn


def start_run(session: RunSession, *, command: str, task: str, repo: str, test_cmd,
              options: dict) -> threading.Thread:
    """Spawn the orchestrator in a background thread with a WebView + web gates.

    `options` carries runs_dir / worktrees_dir / backends / numeric limits. Tests pass
    FakeAgentBackend(s); production passes real CLI backends (built by the caller).
    """
    runs_dir = Path(options.get("runs_dir", ".macr/runs"))
    worktrees_dir = Path(options.get("worktrees_dir", ".macr/worktrees"))

    def target() -> None:
        view = WebView(session)
        try:
            if command == "collab":
                from macr.collab_orchestrator import run_collab
                state = run_collab(
                    task, repo=Path(repo), test_cmd=test_cmd,
                    claude_backend=options["claude_backend"], codex_backend=options["codex_backend"],
                    runs_dir=runs_dir, worktrees_dir=worktrees_dir,
                    max_revisions=options.get("max_revisions", 2),
                    human_gate=_make_gate(session, "final", _final_gate_data),
                    printer=view.printer, run_id=session.run_id,
                    timeout=options.get("timeout", 1800))
            else:
                from macr.discussion import run_discuss
                from macr.discussion_control import auto_discussion_control
                state = run_discuss(
                    task, repo=Path(repo), test_cmd=test_cmd,
                    claude_backend=options["claude_backend"], codex_backend=options["codex_backend"],
                    impl_codex_backend=options["impl_codex_backend"],
                    runs_dir=runs_dir, worktrees_dir=worktrees_dir,
                    max_rounds=options.get("max_rounds", 3),
                    max_revisions=options.get("max_revisions", 2),
                    max_plan_revisions=options.get("max_plan_revisions", 1),
                    consensus_gate=_make_gate(session, "consensus", _consensus_gate_data),
                    human_gate=_make_gate(session, "final", _final_gate_data),
                    discussion_control=auto_discussion_control, view=view,
                    run_id=session.run_id, timeout=options.get("timeout", 1800))
            decision = state.human_feedback.decision if state.human_feedback else None
            session.emit({"type": "status", "status": "done"})
            session.emit({"type": "done", "run_id": session.run_id, "decision": decision})
        except Exception as exc:  # noqa: BLE001 — surface any failure to the client
            session.emit({"type": "status", "status": "error"})
            session.emit({"type": "error", "message": str(exc)})

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def start_live_run(session: RunSession, *, command: str, task: str, repo: str, test_cmd,
                   options: dict) -> threading.Thread:
    """RunManager default runner: assigns a real run_id and builds real CLI backends."""
    from macr.agents.cli_backend import ClaudeCliBackend, CodexCliBackend
    from macr.utils import next_run_id

    runs_dir = Path(options.get("runs_dir", ".macr/runs")).resolve()
    session.run_id = next_run_id(runs_dir)
    enable = not options.get("no_subagents", False)
    timeout = options.get("timeout", 1800)
    opts = dict(options)
    opts["runs_dir"] = runs_dir
    opts["worktrees_dir"] = Path(options.get("worktrees_dir", ".macr/worktrees")).resolve()
    opts["claude_backend"] = ClaudeCliBackend(timeout=timeout, enable_subagents=enable)
    if command == "collab":
        opts["codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable)
    else:
        opts["codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable, sandbox="read-only")
        opts["impl_codex_backend"] = CodexCliBackend(timeout=timeout, enable_subagents=enable,
                                                     sandbox="workspace-write")
    return start_run(session, command=command, task=task, repo=repo, test_cmd=test_cmd, options=opts)
