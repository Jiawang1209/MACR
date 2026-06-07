from __future__ import annotations

from macr.schemas import Decision, TestResult


def evaluate_collab(
    *,
    test_result: TestResult | None,
    reviewer: dict | None,
    agent_failed: bool,
) -> Decision:
    """Deterministic quality gate (spec §6). No model call."""
    if agent_failed:
        return Decision.BLOCKED
    if test_result is None or not test_result.passed:
        return Decision.NEEDS_FIX
    findings = (reviewer or {}).get("findings", [])
    if any(f.get("level") == "blocking" for f in findings):
        return Decision.NEEDS_FIX
    return Decision.PASS


def evaluate_plan(reviewer: dict | None) -> Decision:
    """Deterministic plan-review gate (Stage D). No model call."""
    if reviewer is None:
        return Decision.BLOCKED
    if reviewer.get("decision") == "needs_fix":
        return Decision.NEEDS_FIX
    if any(f.get("level") == "blocking" for f in reviewer.get("findings", [])):
        return Decision.NEEDS_FIX
    return Decision.PASS
