from macr.roles import EVALUATOR, EXECUTOR, PLANNER, REVIEWER, ROLES
from macr.schemas import (
    EvaluatorOutput,
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_roles_registry():
    assert set(ROLES) == {"planner", "executor", "reviewer", "evaluator"}


def test_role_specs_wired_correctly():
    assert PLANNER.content_model is PlannerOutput
    assert EXECUTOR.content_model is ExecutorOutput
    assert REVIEWER.content_model is ReviewerOutput
    assert EVALUATOR.content_model is EvaluatorOutput
    assert PLANNER.tool_name == "submit_plan"
    assert EVALUATOR.message_type is MessageType.EVALUATION


def test_planner_user_includes_task():
    state = SharedState(run_id="R1", user_query="build a parser")
    assert "build a parser" in PLANNER.build_user(state)


def test_executor_user_includes_plan_steps():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["planner"].append({"summary": "s", "steps": ["step-one"], "risks": []})
    assert "step-one" in EXECUTOR.build_user(state)


def test_executor_user_includes_review_feedback_on_revision():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["planner"].append({"summary": "s", "steps": ["x"], "risks": []})
    state.agent_outputs["executor"].append({"artifact": "v1", "notes": "", "evidence": []})
    state.agent_outputs["reviewer"].append(
        {"summary": "needs work", "findings": [], "decision": "needs_fix"}
    )
    user = EXECUTOR.build_user(state)
    assert "needs work" in user


def test_reviewer_user_includes_executor_artifact():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["executor"].append({"artifact": "THE CODE", "notes": "", "evidence": []})
    assert "THE CODE" in REVIEWER.build_user(state)


def test_evaluator_user_includes_artifact_and_review():
    state = SharedState(run_id="R1", user_query="q")
    state.agent_outputs["executor"].append({"artifact": "ART", "notes": "", "evidence": []})
    state.agent_outputs["reviewer"].append(
        {"summary": "REV", "findings": [], "decision": "approve"}
    )
    user = EVALUATOR.build_user(state)
    assert "ART" in user and "REV" in user


def test_tool_schema_is_generated_from_model():
    schema = PLANNER.content_model.model_json_schema()
    assert "summary" in schema["properties"]
