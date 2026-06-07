import json
from pathlib import Path

import pytest

from macr.web.runs import (
    RunCorrupt, RunNotFound, infer_command_type, load_run,
)


def _write_run(runs_dir: Path, run_id: str, state: dict) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _collab_state():
    return {
        "run_id": "R1", "user_query": "add add()", "target_repo": "/tmp/repo",
        "worktree_path": "/tmp/wt",
        "agent_outputs": {
            "planner": [{"summary": "plan it", "steps": ["read", "append"]}],
            "executor": [{"artifact": "def add", "notes": "done"}],
            "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
            "evaluator": [],
        },
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS", "test_passed": True}],
        "test_results": [{"command": "python check.py", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["diff --git a/mymod.py b/mymod.py\n+def add(): ..."],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def _run_state():
    return {
        "run_id": "R1", "user_query": "write a poem", "target_repo": None,
        "agent_outputs": {
            "planner": [{"summary": "plan", "steps": ["s"]}],
            "executor": [{"artifact": "poem", "notes": ""}],
            "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
            "evaluator": [{"decision": "PASS", "reasons": [], "confidence": 0.9}],
        },
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS"}],
        "test_results": [], "diffs": [],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def test_infer_command_type():
    assert infer_command_type(_collab_state()) == "collab"
    assert infer_command_type(_run_state()) == "run"
    assert infer_command_type({"discussion": [{"round": 0}], "consensus": None}) == "discuss"
    assert infer_command_type({"discussion": [], "consensus": {"summary": "x"}}) == "discuss"


def test_load_run_collab_stage_sequence(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "collab"
    assert detail.task == "add add()"
    assert detail.decision == "approve"
    kinds = [s.kind for s in detail.stages]
    assert kinds == ["plan", "executor", "tests", "reviewer", "evaluator", "gate"]
    tests_stage = next(s for s in detail.stages if s.kind == "tests")
    assert tests_stage.status == "passed"
    assert detail.stages[-1].kind == "gate" and detail.stages[-1].status == "approve"


def test_load_run_run_has_no_tests_or_diff(tmp_path):
    _write_run(tmp_path, "R1", _run_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "run"
    kinds = [s.kind for s in detail.stages]
    assert kinds == ["plan", "executor", "reviewer", "evaluator", "gate"]
    assert all(s.kind != "tests" for s in detail.stages)


def test_load_run_missing_raises_not_found(tmp_path):
    with pytest.raises(RunNotFound):
        load_run(tmp_path, "nope")


def test_load_run_corrupt_state_raises(tmp_path):
    d = tmp_path / "R1"
    d.mkdir()
    (d / "state.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(RunCorrupt):
        load_run(tmp_path, "R1")
