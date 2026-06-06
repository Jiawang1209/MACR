from __future__ import annotations

from pathlib import Path
from typing import Callable

from macr.agent import run_agent
from macr.human_gate import interactive_human_gate
from macr.llm import LLM
from macr.roles import EVALUATOR, EXECUTOR, PLANNER, REVIEWER
from macr.runlog import RunLog
from macr.schemas import Decision, HumanFeedback, SharedState
from macr.utils import next_run_id

HumanGate = Callable[..., HumanFeedback]


def _build_final(state: SharedState) -> str:
    ex = state.agent_outputs["executor"][-1] if state.agent_outputs["executor"] else {}
    trail = " → ".join(d["decision"] for d in state.decisions) or "(no evaluation)"
    parts = [
        "# Final Output",
        f"\n## Task\n{state.user_query}",
        f"\n## Artifact\n{ex.get('artifact', '')}",
        f"\n## Decision trail\n{trail}",
    ]
    hf = state.human_feedback
    if hf is not None:
        parts.append(f"\n## Human decision\n{hf.decision}")
        if hf.feedback:
            parts.append(f"\n## 人工批注 / Human annotation\n{hf.feedback}")
    return "\n".join(parts) + "\n"


def run_task(
    task: str,
    llm: LLM,
    runs_dir: Path,
    *,
    max_revisions: int = 2,
    human_gate: HumanGate = interactive_human_gate,
    printer: Callable[..., None] = print,
    today: str | None = None,
) -> SharedState:
    run_id = next_run_id(runs_dir, today=today)
    run_path = runs_dir / run_id
    log = RunLog(run_path)
    state = SharedState(run_id=run_id, user_query=task)
    log.write_input(task)
    task_id = run_id

    # --- Planner (once) ---
    planner_msg = run_agent(PLANNER, state, llm, task_id=task_id, run_id=run_id)
    state.agent_outputs["planner"].append(planner_msg.content)
    state.task_plan = list(planner_msg.content.get("steps", []))
    log.write_planner(planner_msg.content)
    printer(f"[planner] {planner_msg.content.get('summary', '')}")

    # --- Execute / Review / Evaluate loop ---
    total_attempts = max_revisions + 1
    for attempt in range(1, total_attempts + 1):
        executor_msg = run_agent(EXECUTOR, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["executor"].append(executor_msg.content)
        log.write_executor(executor_msg.content, attempt)
        printer(f"[executor #{attempt}] {executor_msg.content.get('notes', '') or 'artifact produced'}")

        reviewer_msg = run_agent(REVIEWER, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["reviewer"].append(reviewer_msg.content)
        state.reviews.append(reviewer_msg.content)
        log.write_reviewer(reviewer_msg.content)
        printer(f"[reviewer] {reviewer_msg.content.get('decision', '')}")

        evaluator_msg = run_agent(EVALUATOR, state, llm, task_id=task_id, run_id=run_id)
        state.agent_outputs["evaluator"].append(evaluator_msg.content)
        decision = evaluator_msg.content["decision"]
        state.decisions.append({"attempt": attempt, "decision": decision})
        log.write_evaluator(evaluator_msg.content)
        printer(f"[evaluator] {decision}")

        if decision == Decision.PASS.value:
            break
        if decision == Decision.BLOCKED.value:
            break
        # NEEDS_FIX: loop again if budget remains, else fall through to gate
        if attempt >= total_attempts:
            break

    # --- Human Gate ---
    feedback = human_gate(state, printer=printer)
    state.human_feedback = feedback
    final = _build_final(state)
    state.final_output = final
    log.write_final(final)
    log.write_state(state)
    printer(f"[human] {feedback.decision}")
    return state
