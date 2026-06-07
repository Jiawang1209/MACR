from macr.collab_evaluator import evaluate_collab, evaluate_plan
from macr.schemas import Decision, TestResult


def _passing():
    return TestResult(command="t", passed=True, exit_code=0)


def _failing():
    return TestResult(command="t", passed=False, exit_code=1)


def _review(blocking: bool):
    findings = [{"level": "blocking", "issue": "x", "evidence": "e", "recommendation": "r"}] if blocking else []
    return {"summary": "s", "findings": findings, "decision": "needs_fix" if blocking else "approve"}


def test_agent_failed_is_blocked():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(False), agent_failed=True) is Decision.BLOCKED


def test_tests_fail_is_needs_fix():
    assert evaluate_collab(test_result=_failing(), reviewer=_review(False), agent_failed=False) is Decision.NEEDS_FIX


def test_blocking_review_is_needs_fix():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(True), agent_failed=False) is Decision.NEEDS_FIX


def test_pass_when_tests_pass_and_no_blocking():
    assert evaluate_collab(test_result=_passing(), reviewer=_review(False), agent_failed=False) is Decision.PASS


def test_none_test_result_is_needs_fix():
    assert evaluate_collab(test_result=None, reviewer=_review(False), agent_failed=False) is Decision.NEEDS_FIX


def _plan_review(*, blocking=False, needs_fix=False):
    findings = [{"level": "blocking", "issue": "x", "evidence": "e", "recommendation": "r"}] if blocking else []
    return {"summary": "s", "findings": findings, "decision": "needs_fix" if needs_fix else "approve"}


def test_plan_review_none_is_blocked():
    assert evaluate_plan(None) is Decision.BLOCKED


def test_plan_review_needs_fix_decision():
    assert evaluate_plan(_plan_review(needs_fix=True)) is Decision.NEEDS_FIX


def test_plan_review_blocking_finding_is_needs_fix():
    assert evaluate_plan(_plan_review(blocking=True)) is Decision.NEEDS_FIX


def test_plan_review_clean_is_pass():
    assert evaluate_plan(_plan_review()) is Decision.PASS
