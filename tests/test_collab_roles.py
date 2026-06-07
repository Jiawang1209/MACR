from macr.collab_roles import COLLAB_ROLES, EXECUTOR_C, PLANNER_C, REVIEWER_C
from macr.schemas import (
    ExecutorOutput,
    MessageType,
    PlannerOutput,
    ReviewerOutput,
    SharedState,
)


def test_registry_and_wiring():
    assert set(COLLAB_ROLES) == {"planner", "executor", "reviewer"}
    assert PLANNER_C.content_model is PlannerOutput
    assert EXECUTOR_C.content_model is ExecutorOutput
    assert REVIEWER_C.content_model is ReviewerOutput
    assert REVIEWER_C.message_type is MessageType.REVIEW
    assert PLANNER_C.agent_id == "claude_planner"
    assert EXECUTOR_C.agent_id == "codex_executor"


def test_planner_user_has_task():
    s = SharedState(run_id="R1", user_query="add a CLI flag")
    assert "add a CLI flag" in PLANNER_C.build_user(s)


def test_executor_user_has_plan_and_revision_context():
    s = SharedState(run_id="R1", user_query="q")
    s.agent_outputs["planner"].append({"summary": "p", "steps": ["edit main.py"], "risks": []})
    assert "edit main.py" in EXECUTOR_C.build_user(s)
    s.diffs.append("some diff")
    s.test_results.append({"command": "t", "passed": False, "exit_code": 1, "log": "ASSERT boom", "timed_out": False})
    s.agent_outputs["reviewer"].append({"summary": "fix it", "findings": [], "decision": "needs_fix"})
    user = EXECUTOR_C.build_user(s)
    assert "fix it" in user and "boom" in user


def test_reviewer_user_has_diff_and_test_result():
    s = SharedState(run_id="R1", user_query="q")
    s.diffs.append("THE DIFF")
    s.test_results.append({"command": "t", "passed": True, "exit_code": 0, "log": "1 passed", "timed_out": False})
    user = REVIEWER_C.build_user(s)
    assert "THE DIFF" in user and ("passed" in user or "PASS" in user)
