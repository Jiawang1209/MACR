from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import AgentBackend
from macr.discussion_view import ConsoleView, DiscussionView
from macr.agents.trace import TraceSink
from macr.collab_orchestrator import _build_final, _implementation_loop, _record_subagents
from macr.collab_evaluator import evaluate_plan
from macr.discuss_roles import CONSENSUS, DISCUSS_PLANNER, DISCUSS_REVIEWER, DISCUSS_TURN, render_transcript
from macr.discussion_control import ControlDecision, interactive_discussion_control
from macr.human_gate import collab_human_gate, consensus_human_gate
from macr.runlog import RunLog
from macr.schemas import Decision, HumanFeedback, SharedState
from macr.utils import next_run_id
from macr.worktree import Worktree

HumanGate = Callable[..., HumanFeedback]
DiscussionControl = Callable[..., ControlDecision]


def _disc_dir(run_path: Path) -> Path:
    d = run_path / "discussion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _render_findings(reviewer: dict) -> str:
    lines = [f"[计划审查意见] {reviewer.get('summary', '')}"]
    for f in reviewer.get("findings", []):
        lines.append(f"  - ({f.get('level')}) {f.get('issue')} → {f.get('recommendation')}")
    return "\n".join(lines)


def _plan_review_loop(
    state: SharedState,
    *,
    run_id: str,
    run_path: Path,
    disc: Path,
    log: RunLog,
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,
    max_rounds: int,
    max_plan_revisions: int,
    record: Callable[..., None],
    view: DiscussionView,
) -> None:
    """Stage D: post-consensus plan review + bounded re-discussion (mutates state).

    Codex reviews the consensus plan; a deterministic evaluator decides. On NEEDS_FIX
    with budget left, the findings are injected back for one more discuss round and a
    re-consensus; otherwise the loop ends and the caller escalates to the human gate.
    """
    for attempt in range(max_plan_revisions + 1):
        try:
            rsink = TraceSink(run_path / "subagents", f"review.v{attempt}")
            rmsg = codex_backend.run_role(
                DISCUSS_REVIEWER, state, run_id=run_id, task_id=run_id, trace=rsink)
            reviewer = rmsg.content
            _record_subagents(state, rsink, f"review.v{attempt}", attempt)
        except AgentError as exc:
            view.note(f"[plan review blocked] {exc}")
            reviewer = None
        state.reviews.append(reviewer or {})
        state.agent_outputs["reviewer"].append(reviewer or {})
        if reviewer is not None:
            (disc / f"review.v{attempt}.json").write_text(
                json.dumps(reviewer, ensure_ascii=False, indent=2), encoding="utf-8")
            view.review(attempt, reviewer)

        decision = evaluate_plan(reviewer)
        state.decisions.append(
            {"stage": "plan_review", "attempt": attempt, "decision": decision.value})
        state.agent_outputs["evaluator"].append({"decision": decision.value})
        view.evaluation(attempt, decision)

        if decision is not Decision.NEEDS_FIX:
            break
        if attempt == max_plan_revisions:
            break  # exhausted → escalate to human gate with unresolved findings

        # NEEDS_FIX with budget left: inject findings, re-discuss one round, re-consensus
        rround = max_rounds + 1 + attempt
        findings_text = _render_findings(reviewer)
        record(rround, "codex_reviewer", "review", findings_text)
        (disc / f"review-round{attempt}.findings.txt").write_text(
            findings_text + "\n", encoding="utf-8")
        view.note(
            f"[plan review] needs_fix → 注回 {len(reviewer.get('findings', []))} 条意见,再谈一轮")
        try:
            for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                tsink = TraceSink(run_path / "subagents", f"review-turn.{agent}.v{attempt}")
                tmsg = backend.run_role(
                    DISCUSS_TURN, state, run_id=run_id, task_id=run_id, trace=tsink)
                record(rround, agent, "turn", tmsg.content)
                _record_subagents(state, tsink, f"review-turn.{agent}", attempt)
                (disc / f"review-round{attempt}.{agent}.json").write_text(
                    json.dumps(tmsg.content, ensure_ascii=False, indent=2), encoding="utf-8")
                view.turn(agent, rround, tmsg.content)
            csink = TraceSink(run_path / "subagents", f"consensus.v{attempt + 1}")
            cmsg = claude_backend.run_role(
                CONSENSUS, state, run_id=run_id, task_id=run_id, trace=csink)
            state.consensus = cmsg.content
            _record_subagents(state, csink, f"consensus.v{attempt + 1}", attempt + 1)
            c2 = cmsg.content
            log._write(
                "consensus.md",
                f"# Consensus (rev {attempt + 1})\n\n{c2.get('summary', '')}\n\n## Steps\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(c2.get('steps', []), 1))
                + f"\n\n## Rationale\n{c2.get('rationale', '')}\n")
            view.consensus(c2)
        except AgentError as exc:
            view.note(f"[consensus blocked] {exc}")
            break


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
    max_plan_revisions: int = 1,
    consensus_gate: HumanGate = consensus_human_gate,
    human_gate: HumanGate = collab_human_gate,
    discussion_control: DiscussionControl = interactive_discussion_control,
    view: DiscussionView | None = None,
    today: str | None = None,
    timeout: int = 1800,
    run_id: str | None = None,
    worker_backend: AgentBackend | None = None,
) -> SharedState:
    view = view or ConsoleView()
    run_id = run_id or next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=topic, topic=topic, target_repo=str(repo))
    log._write("topic.md", f"{topic}\n")
    view.note(f"[run {run_id}] artifacts → {run_path}")
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
                view.plan(agent, msg.content)

            for round_no in range(0, max_rounds + 1):
                if round_no >= 1:
                    for agent, backend in (("claude", claude_backend), ("codex", codex_backend)):
                        sink = TraceSink(run_path / "subagents", f"turn.{agent}.v{round_no}")
                        msg = backend.run_role(DISCUSS_TURN, state, run_id=run_id, task_id=run_id, trace=sink)
                        record(round_no, agent, "turn", msg.content)
                        _record_subagents(state, sink, f"turn.{agent}", round_no)
                        (disc / f"round{round_no}.{agent}.json").write_text(
                            json.dumps(msg.content, ensure_ascii=False, indent=2), encoding="utf-8")
                        view.turn(agent, round_no, msg.content)

                decision = discussion_control(state, round_no, printer=view.note)
                if decision.action == "abort":
                    aborted = True
                    break
                if decision.action == "interject" and decision.interjection:
                    record(round_no, "human", "interjection", decision.interjection)
                    (disc / f"round{round_no}.human.txt").write_text(decision.interjection + "\n", encoding="utf-8")
                    view.interjection(round_no, decision.interjection)
                if decision.action == "end":
                    break
        except AgentError as exc:
            view.note(f"[discussion blocked] {exc}")

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
                view.consensus(c)
            except AgentError as exc:
                view.note(f"[consensus blocked] {exc}")

            if state.consensus is not None:
                # Stage D: post-consensus plan review gate (Codex reviews; deterministic evaluator)
                _plan_review_loop(
                    state, run_id=run_id, run_path=run_path, disc=disc, log=log,
                    claude_backend=claude_backend, codex_backend=codex_backend,
                    max_rounds=max_rounds, max_plan_revisions=max_plan_revisions,
                    record=record, view=view,
                )

                fb1 = consensus_gate(state, printer=view.note)
                state.human_feedback = fb1
                view.note(f"[human·consensus] {fb1.decision}")
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
                        test_cmd=test_cmd, max_revisions=max_revisions, timeout=timeout, printer=view.status,
                        worker_backend=worker_backend)
                    fb2 = human_gate(state, printer=view.note)
                    state.human_feedback = fb2
                    final_rejected = fb2.decision == "reject"
                    view.note(f"[human·final] {fb2.decision}")

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
