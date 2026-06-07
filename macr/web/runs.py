from __future__ import annotations

import json
from pathlib import Path

from macr.web.models import Artifact, RunDetail, RunSummary, Stage


class RunNotFound(Exception):
    """Run id has no directory / no state.json."""


class RunCorrupt(Exception):
    """state.json exists but cannot be parsed."""


class ArtifactError(Exception):
    """Requested artifact name is invalid or not in the run dir."""


def _load_state(runs_dir: Path, run_id: str) -> dict:
    state_path = Path(runs_dir) / run_id / "state.json"
    if not state_path.is_file():
        raise RunNotFound(run_id)
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RunCorrupt(f"{run_id}: {exc}") from exc


def infer_command_type(state: dict) -> str:
    if state.get("discussion") or state.get("consensus"):
        return "discuss"
    if state.get("target_repo"):
        return "collab"
    return "run"


def _task_text(state: dict) -> str:
    return state.get("topic") or state.get("user_query") or ""


def _final_decision(state: dict) -> str | None:
    hf = state.get("human_feedback")
    return hf.get("decision") if hf else None


def _planner_stage(state: dict, agent: str | None) -> Stage | None:
    items = state.get("agent_outputs", {}).get("planner", [])
    if not items:
        return None
    p = items[0]
    return Stage(kind="plan", label="Planner", agent=agent,
                 body={"summary": p.get("summary", ""), "steps": p.get("steps", [])})


def _impl_loop_stages(state: dict, *, with_tests: bool, exec_agent: str | None,
                      review_agent: str | None, reviewer_offset: int = 0) -> list[Stage]:
    ao = state.get("agent_outputs", {})
    execs = ao.get("executor", [])
    reviewers = ao.get("reviewer", [])[reviewer_offset:]
    tests = state.get("test_results", [])
    impl_decisions = [d for d in state.get("decisions", []) if d.get("stage") != "plan_review"]
    stages: list[Stage] = []
    for i, ex in enumerate(execs):
        n = i + 1
        stages.append(Stage(kind="executor", label=f"Executor #{n}", agent=exec_agent,
                            body={"artifact": ex.get("artifact", ""), "notes": ex.get("notes", "")}))
        if with_tests and i < len(tests):
            tr = tests[i]
            stages.append(Stage(kind="tests", label=f"Tests #{n}",
                                status="passed" if tr.get("passed") else "failed",
                                body={"command": tr.get("command", ""),
                                      "exit_code": tr.get("exit_code"), "log": tr.get("log", "")}))
        if i < len(reviewers):
            rv = reviewers[i]
            stages.append(Stage(kind="reviewer", label=f"Reviewer #{n}", agent=review_agent,
                                status=rv.get("decision"),
                                body={"summary": rv.get("summary", ""), "findings": rv.get("findings", [])}))
        if i < len(impl_decisions):
            stages.append(Stage(kind="evaluator", label=f"Evaluator #{n}",
                                status=impl_decisions[i].get("decision")))
    return stages


def _gate_stage(state: dict) -> Stage | None:
    hf = state.get("human_feedback")
    if not hf:
        return None
    return Stage(kind="gate", label="Human Gate", status=hf.get("decision"),
                 body={"feedback": hf.get("feedback", "")})


def _stages_linear(state: dict, command_type: str) -> list[Stage]:
    is_collab = command_type == "collab"
    plan_agent = "claude" if is_collab else None
    exec_agent = "codex" if is_collab else None
    review_agent = "claude" if is_collab else None
    stages: list[Stage] = []
    p = _planner_stage(state, plan_agent)
    if p:
        stages.append(p)
    stages += _impl_loop_stages(state, with_tests=is_collab, exec_agent=exec_agent,
                                review_agent=review_agent)
    g = _gate_stage(state)
    if g:
        stages.append(g)
    return stages


def build_stages(state: dict) -> list[Stage]:
    command_type = infer_command_type(state)
    if command_type == "discuss":
        return _stages_discuss(state)
    return _stages_linear(state, command_type)


ARTIFACT_KINDS = (("diff.", "diff"), ("test.", "test_log"), ("final.md", "final"))


def list_artifacts(run_dir: Path) -> list[Artifact]:
    out: list[Artifact] = []
    for f in sorted(run_dir.iterdir()):
        if not f.is_file():
            continue
        for prefix, kind in ARTIFACT_KINDS:
            if f.name.startswith(prefix) or f.name == prefix:
                out.append(Artifact(name=f.name, kind=kind))
                break
    return out


def load_run(runs_dir: Path, run_id: str) -> RunDetail:
    state = _load_state(runs_dir, run_id)
    command_type = infer_command_type(state)
    return RunDetail(
        run_id=state.get("run_id", run_id),
        command_type=command_type,
        task=_task_text(state),
        repo=state.get("target_repo"),
        worktree=state.get("worktree_path"),
        decision=_final_decision(state),
        stages=build_stages(state),
        artifacts=list_artifacts(Path(runs_dir) / run_id),
    )


def _stages_discuss(state: dict) -> list[Stage]:
    stages: list[Stage] = []
    # 1. discussion: plans / turns / human interjections (injected "review" entries are
    #    skipped here — they surface as plan_review stages below).
    for e in state.get("discussion", []):
        kind = e.get("kind")
        agent = e.get("agent")
        content = e.get("content", {}) if isinstance(e.get("content"), dict) else {}
        if kind == "plan":
            stages.append(Stage(kind="plan", label=f"Plan ({agent})", agent=agent,
                                body={"summary": content.get("summary", ""),
                                      "steps": content.get("steps", [])}))
        elif kind == "turn":
            stages.append(Stage(kind="turn", label=f"Turn r{e.get('round')} ({agent})", agent=agent,
                                body={"response": content.get("response", ""),
                                      "concerns": content.get("concerns", []),
                                      "revised_steps": content.get("revised_steps", [])}))
        elif kind == "interjection":
            stages.append(Stage(kind="turn", label=f"Human interjection r{e.get('round')}",
                                agent="human", body={"text": e.get("content", "")}))
    # 2. consensus
    c = state.get("consensus")
    if c:
        stages.append(Stage(kind="consensus", label="Consensus",
                            body={"summary": c.get("summary", ""), "steps": c.get("steps", []),
                                  "rationale": c.get("rationale", "")}))
    # 3. plan-review loop (codex reviews the consensus plan)
    plan_reviews = [d for d in state.get("decisions", []) if d.get("stage") == "plan_review"]
    reviews = state.get("reviews", [])
    for d in plan_reviews:
        att = d.get("attempt", 0)
        rv = reviews[att] if att < len(reviews) else {}
        stages.append(Stage(kind="plan_review", label=f"Plan Review #{att}", agent="codex",
                            status=d.get("decision"),
                            body={"summary": rv.get("summary", ""), "findings": rv.get("findings", [])}))
    # 4. implementation loop — impl reviewers start after the plan reviewers in agent_outputs.reviewer
    stages += _impl_loop_stages(state, with_tests=True, exec_agent="codex",
                                review_agent="claude", reviewer_offset=len(plan_reviews))
    # 5. final human gate
    g = _gate_stage(state)
    if g:
        stages.append(g)
    return stages
