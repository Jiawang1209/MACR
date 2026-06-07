from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import AgentBackend
from macr.agents.trace import TraceSink
from macr.collab_orchestrator import _build_final, _implementation_loop, _record_subagents
from macr.discuss_roles import CONSENSUS, DISCUSS_PLANNER, DISCUSS_TURN, render_transcript
from macr.discussion_control import ControlDecision, interactive_discussion_control
from macr.human_gate import collab_human_gate, consensus_human_gate
from macr.runlog import RunLog
from macr.schemas import HumanFeedback, SharedState
from macr.utils import next_run_id
from macr.worktree import Worktree

HumanGate = Callable[..., HumanFeedback]
DiscussionControl = Callable[..., ControlDecision]


def _disc_dir(run_path: Path) -> Path:
    d = run_path / "discussion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _print_plan(printer, agent: str, content: dict) -> None:
    printer(f"\n━━━ {agent} · 第 0 轮(计划)━━━")
    printer(content.get("summary", ""))
    for s in content.get("steps", []):
        printer(f"  - {s}")


def _print_turn(printer, agent: str, round_no: int, content: dict) -> None:
    printer(f"\n━━━ {agent} · 第 {round_no} 轮 ━━━")
    if content.get("concerns"):
        printer("[concerns] " + "; ".join(content["concerns"]))
    printer("[response] " + content.get("response", ""))
    if content.get("revised_steps"):
        printer("[revised steps] " + "; ".join(content["revised_steps"]))


def run_discuss(
    topic: str,
    *,
    repo: Path,
    test_cmd: list[str],
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,
    impl_codex_backend: AgentBackend,
    runs_dir: Path,
    worktrees_dir: Path,
    max_rounds: int = 3,
    max_revisions: int = 2,
    consensus_gate: HumanGate = consensus_human_gate,
    human_gate: HumanGate = collab_human_gate,
    discussion_control: DiscussionControl = interactive_discussion_control,
    printer: Callable[..., None] = print,
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=topic, topic=topic, target_repo=str(repo))
    log._write("topic.md", f"{topic}\n")
    disc = _disc_dir(run_path)
    worktree: Worktree | None = None
    aborted = False
    final_rejected = False

    def record(round_no, agent, kind, content):
        state.discussion.append({"round": round_no, "agent": agent, "kind": kind, "content": content})

    try:
        worktree = Worktree.create(repo, run_id, worktrees_dir)
        state.worktree_path = str(worktree.path)
        try:
            for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                sink = TraceSink(run_path / "subagents", f"plan.{agent}")
                msg = backend.run_role(DISCUSS_PLANNER, state, run_id=run_id, task_id=run_id, trace=sink)
                record(0, agent, "plan", msg.content)
                _record_subagents(state, sink, f"plan.{agent}", 0)
                (disc / f"plan.{agent}.md").write_text(
                    f"# {agent} plan\n\n{msg.content.get('summary','')}\n\n"
                    + "\n".join(f"- {s}" for s in msg.content.get("steps", [])) + "\n",
                    encoding="utf-8")
                _print_plan(printer, agent, msg.content)

            for round_no in range(0, max_rounds + 1):
                if round_no >= 1:
                    for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                        sink = TraceSink(run_path / "subagents", f"turn.{agent}.v{round_no}")
                        msg = backend.run_role(DISCUSS_TURN, state, run_id=run_id, task_id=run_id, trace=sink)
                        record(round_no, agent, "turn", msg.content)
                        _record_subagents(state, sink, f"turn.{agent}", round_no)
                        (disc / f"round{round_no}.{agent}.json").write_text(
                            json.dumps(msg.content, ensure_ascii=False, indent=2), encoding="utf-8")
                        _print_turn(printer, agent, round_no, msg.content)

                decision = discussion_control(state, round_no, printer=printer)
                if decision.action == "abort":
                    aborted = True
                    break
                if decision.action == "interject" and decision.interjection:
                    record(round_no, "human", "interjection", decision.interjection)
                    (disc / f"round{round_no}.human.txt").write_text(decision.interjection + "\n", encoding="utf-8")
                    printer(f"\n━━━ 你(human)· 第 {round_no} 轮后插话 ━━━\n{decision.interjection}")
                if decision.action == "end":
                    break
        except AgentError as exc:
            printer(f"[discussion blocked] {exc}")

        (disc / "transcript.md").write_text(render_transcript(state.discussion) + "\n", encoding="utf-8")

        if not aborted:
            try:
                sink = TraceSink(run_path / "subagents", "consensus")
                cons_msg = claude_backend.run_role(CONSENSUS, state, run_id=run_id, task_id=run_id, trace=sink)
                state.consensus = cons_msg.content
                _record_subagents(state, sink, "consensus", 0)
                c = cons_msg.content
                log._write("consensus.md",
                           f"# Consensus\n\n{c.get('summary','')}\n\n## Steps\n"
                           + "\n".join(f"{i}. {s}" for i, s in enumerate(c.get('steps', []), 1))
                           + f"\n\n## Rationale\n{c.get('rationale','')}\n")
                printer(f"\n━━━ 共识 / Consensus ━━━\n{c.get('summary','')}")
            except AgentError as exc:
                printer(f"[consensus blocked] {exc}")

            if state.consensus is not None:
                fb1 = consensus_gate(state, printer=printer)
                state.human_feedback = fb1
                printer(f"[human·consensus] {fb1.decision}")
                if fb1.decision == "approve":
                    state.agent_outputs["planner"].append({
                        "summary": state.consensus.get("summary", ""),
                        "steps": list(state.consensus.get("steps", [])),
                        "tools_needed": [], "risks": [],
                    })
                    state.task_plan = list(state.consensus.get("steps", []))
                    _implementation_loop(
                        state, run_path=run_path, log=log, worktree=worktree,
                        claude_backend=claude_backend, codex_backend=impl_codex_backend,
                        test_cmd=test_cmd, max_revisions=max_revisions, timeout=timeout, printer=printer)
                    fb2 = human_gate(state, printer=printer)
                    state.human_feedback = fb2
                    final_rejected = fb2.decision == "reject"
                    printer(f"[human·final] {fb2.decision}")

        final = _build_final(state)
        state.final_output = final
        log.write_final(final)

        # spec §3/§10: keep the worktree on abort and on consensus reject (preserve the scene for
        # inspection); only clean it up when the FINAL gate② rejected.
        if worktree is not None and final_rejected:
            worktree.cleanup()
            state.worktree_path = None
    finally:
        log.write_state(state)
    return state
