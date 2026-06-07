from __future__ import annotations

from pathlib import Path
from typing import Callable

from macr.agent import AgentError
from macr.agents.base import AgentBackend
from macr.agents.trace import TraceSink
from macr.collab_evaluator import evaluate_collab
from macr.collab_roles import EXECUTOR_C, PLANNER_C, REVIEWER_C
from macr.human_gate import collab_human_gate
from macr.runlog import RunLog
from macr.schemas import Decision, HumanFeedback, SharedState, TestResult
from macr.testrunner import run_tests
from macr.utils import next_run_id
from macr.worktree import Worktree

HumanGate = Callable[..., HumanFeedback]


def _record_subagents(state: SharedState, sink: TraceSink, role: str, attempt: int) -> None:
    types = sorted({r.agent_type for r in sink.records})
    state.subagents.append(
        {"role": role, "attempt": attempt, "count": len(sink.records), "types": types}
    )


def _build_final(state: SharedState) -> str:
    diff = state.diffs[-1] if state.diffs else "(no diff)"
    tr = state.test_results[-1] if state.test_results else {}
    trail = " → ".join(d["decision"] for d in state.decisions) or "(no evaluation)"
    parts = [
        "# Final Output",
        f"\n## Task\n{state.user_query}",
        f"\n## Worktree\n{state.worktree_path}",
        f"\n## Tests\npassed={tr.get('passed')} exit_code={tr.get('exit_code')}",
        f"\n## Decision trail\n{trail}",
        f"\n## Final diff\n```diff\n{diff}\n```",
    ]
    if state.subagents:
        overview = "\n".join(
            f"- {s['role']} v{s['attempt']}: {s['count']} subagent(s) {s['types']}"
            for s in state.subagents
        )
        parts.append(f"\n## 嵌套 subagent 概览 / Nested subagents\n{overview}")
    hf = state.human_feedback
    if hf is not None:
        parts.append(f"\n## Human decision\n{hf.decision}")
        if hf.feedback:
            parts.append(f"\n## 人工批注 / Human annotation\n{hf.feedback}")
    return "\n".join(parts) + "\n"


def run_collab(
    task: str,
    *,
    repo: Path,
    test_cmd: list[str],
    claude_backend: AgentBackend,
    codex_backend: AgentBackend,
    runs_dir: Path,
    worktrees_dir: Path,
    max_revisions: int = 2,
    human_gate: HumanGate = collab_human_gate,
    printer: Callable[..., None] = print,
    today: str | None = None,
    timeout: int = 1800,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=task, target_repo=str(repo))
    log.write_input(task)
    worktree: Worktree | None = None

    try:
        worktree = Worktree.create(repo, run_id, worktrees_dir)
        state.worktree_path = str(worktree.path)
        try:
            planner_sink = TraceSink(run_path / "subagents", "planner.v1")
            planner_msg = claude_backend.run_role(
                PLANNER_C, state, run_id=run_id, task_id=run_id, trace=planner_sink)
            state.agent_outputs["planner"].append(planner_msg.content)
            state.task_plan = list(planner_msg.content.get("steps", []))
            log.write_planner(planner_msg.content)
            _record_subagents(state, planner_sink, "planner", 1)
            printer(f"[planner] {planner_msg.content.get('summary', '')}")

            total_attempts = max_revisions + 1
            for attempt in range(1, total_attempts + 1):
                exec_sink = TraceSink(run_path / "subagents", f"executor.v{attempt}")
                exec_msg = codex_backend.run_role(
                    EXECUTOR_C, state, run_id=run_id, task_id=run_id, trace=exec_sink)
                state.agent_outputs["executor"].append(exec_msg.content)
                log.write_executor(exec_msg.content, attempt)
                _record_subagents(state, exec_sink, "executor", attempt)

                diff = worktree.diff()
                state.diffs.append(diff)
                log.write_diff(diff, attempt)

                tr: TestResult = run_tests(worktree.path, test_cmd, timeout)
                state.test_results.append(tr.model_dump())
                log.write_test(tr.model_dump(), tr.log, attempt)
                printer(f"[tests #{attempt}] passed={tr.passed}")

                review_sink = TraceSink(run_path / "subagents", f"reviewer.v{attempt}")
                review_msg = claude_backend.run_role(
                    REVIEWER_C, state, run_id=run_id, task_id=run_id, trace=review_sink)
                state.agent_outputs["reviewer"].append(review_msg.content)
                state.reviews.append(review_msg.content)
                log.write_reviewer(review_msg.content)
                _record_subagents(state, review_sink, "reviewer", attempt)
                printer(f"[reviewer] {review_msg.content.get('decision', '')}")

                decision = evaluate_collab(test_result=tr, reviewer=review_msg.content, agent_failed=False)
                state.decisions.append({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
                log.write_evaluator({"attempt": attempt, "decision": decision.value, "test_passed": tr.passed})
                printer(f"[evaluator] {decision.value}")

                if decision in (Decision.PASS, Decision.BLOCKED):
                    break
                if attempt >= total_attempts:
                    break
        except AgentError as exc:
            # spec §6: a role failing schema validation twice -> BLOCKED -> Human Gate.
            record = {
                "attempt": len(state.decisions) + 1,
                "decision": Decision.BLOCKED.value,
                "test_passed": False,
                "error": str(exc),
            }
            state.decisions.append(record)
            log.write_evaluator(record)
            printer(f"[blocked] {exc}")

        feedback = human_gate(state, printer=printer)
        state.human_feedback = feedback
        final = _build_final(state)
        state.final_output = final
        log.write_final(final)
        printer(f"[human] {feedback.decision}")

        if feedback.decision == "reject" and worktree is not None:
            worktree.cleanup()
            state.worktree_path = None
    finally:
        log.write_state(state)
    return state
