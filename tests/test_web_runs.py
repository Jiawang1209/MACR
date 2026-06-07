import json
from pathlib import Path

import pytest

from macr.web.runs import (
    ArtifactError, RunCorrupt, RunNotFound, infer_command_type, list_runs, load_run, read_artifact,
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


def _discuss_state():
    return {
        "run_id": "R1", "user_query": "build add()", "topic": "build add()",
        "target_repo": "/tmp/repo", "worktree_path": "/tmp/wt",
        "agent_outputs": {
            "planner": [], "executor": [{"artifact": "def add", "notes": ""}],
            "reviewer": [
                {"summary": "plan-rv", "findings": [], "decision": "approve"},  # plan review
                {"summary": "impl-rv", "findings": [], "decision": "approve"},  # impl review
            ],
            "evaluator": [],
        },
        "reviews": [
            {"summary": "plan-rv", "findings": [], "decision": "approve"},
            {"summary": "impl-rv", "findings": [], "decision": "approve"},
        ],
        "decisions": [
            {"stage": "plan_review", "attempt": 0, "decision": "PASS"},
            {"attempt": 1, "decision": "PASS", "test_passed": True},
        ],
        "test_results": [{"command": "python check.py", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["diff ..."],
        "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [
            {"round": 0, "agent": "claude", "kind": "plan", "content": {"summary": "c-plan", "steps": ["s"]}},
            {"round": 0, "agent": "codex", "kind": "plan", "content": {"summary": "x-plan", "steps": ["s"]}},
            {"round": 1, "agent": "claude", "kind": "turn",
             "content": {"response": "r", "concerns": [], "revised_steps": []}},
        ],
        "consensus": {"summary": "agreed", "steps": ["do-1"], "rationale": "r", "open_questions": []},
    }


def test_load_run_discuss_stage_sequence(tmp_path):
    _write_run(tmp_path, "R1", _discuss_state())
    detail = load_run(tmp_path, "R1")
    assert detail.command_type == "discuss"
    kinds = [s.kind for s in detail.stages]
    # two plans + one turn + consensus + one plan_review + impl loop (exec/tests/reviewer/eval) + gate
    assert kinds == ["plan", "plan", "turn", "consensus", "plan_review",
                     "executor", "tests", "reviewer", "evaluator", "gate"]
    # the impl reviewer must be the SECOND reviewer entry (plan review consumed the first)
    impl_review = next(s for s in detail.stages if s.kind == "reviewer")
    assert impl_review.body["summary"] == "impl-rv"
    pr = next(s for s in detail.stages if s.kind == "plan_review")
    assert pr.status == "PASS" and pr.body["summary"] == "plan-rv"


def test_list_runs_newest_first_and_marks_broken(tmp_path):
    _write_run(tmp_path, "R20260607_001", _collab_state())
    _write_run(tmp_path, "R20260607_002", _run_state())
    broken = tmp_path / "R20260607_003"
    broken.mkdir()
    (broken / "state.json").write_text("{ broken", encoding="utf-8")
    summaries = list_runs(tmp_path)
    ids = [s.run_id for s in summaries]
    assert ids == ["R20260607_003", "R20260607_002", "R20260607_001"]  # newest first
    assert summaries[0].broken is True
    assert summaries[1].command_type == "run"
    assert summaries[2].command_type == "collab" and summaries[2].decision == "approve"


def test_list_runs_empty_dir(tmp_path):
    assert list_runs(tmp_path) == []


def test_read_artifact_returns_text(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    (tmp_path / "R1" / "diff.v1.patch").write_text("the diff", encoding="utf-8")
    assert read_artifact(tmp_path, "R1", "diff.v1.patch") == "the diff"


def test_read_artifact_rejects_traversal(tmp_path):
    _write_run(tmp_path, "R1", _collab_state())
    for bad in ("../R1/state.json", "/etc/passwd", "sub/../../x", "a/b"):
        with pytest.raises(ArtifactError):
            read_artifact(tmp_path, "R1", bad)


def test_read_artifact_missing_run_raises_not_found(tmp_path):
    with pytest.raises(RunNotFound):
        read_artifact(tmp_path, "nope", "diff.v1.patch")
