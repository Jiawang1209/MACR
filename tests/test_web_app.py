import json
from pathlib import Path

from fastapi.testclient import TestClient

from macr.web.app import create_app


def _write_run(runs_dir: Path, run_id: str, state: dict) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _state():
    return {
        "run_id": "R1", "user_query": "do it", "target_repo": "/tmp/repo",
        "agent_outputs": {"planner": [{"summary": "p", "steps": ["s"]}],
                          "executor": [{"artifact": "a", "notes": ""}],
                          "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}],
                          "evaluator": []},
        "reviews": [{"summary": "ok", "findings": [], "decision": "approve"}],
        "decisions": [{"attempt": 1, "decision": "PASS", "test_passed": True}],
        "test_results": [{"command": "t", "passed": True, "exit_code": 0, "log": "OK\n"}],
        "diffs": ["d"], "human_feedback": {"decision": "approve", "feedback": "", "timestamp": "t"},
        "discussion": [], "consensus": None,
    }


def _client(tmp_path):
    return TestClient(create_app(runs_dir=tmp_path))


def test_list_runs_endpoint(tmp_path):
    _write_run(tmp_path, "R1", _state())
    r = _client(tmp_path).get("/api/runs")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["run_id"] == "R1" and body[0]["command_type"] == "collab"


def test_run_detail_endpoint(tmp_path):
    _write_run(tmp_path, "R1", _state())
    r = _client(tmp_path).get("/api/runs/R1")
    assert r.status_code == 200
    assert [s["kind"] for s in r.json()["stages"]] == \
        ["plan", "executor", "tests", "reviewer", "evaluator", "gate"]


def test_run_detail_missing_is_404(tmp_path):
    assert _client(tmp_path).get("/api/runs/nope").status_code == 404


def test_run_detail_corrupt_is_422(tmp_path):
    d = tmp_path / "R1"
    d.mkdir()
    (d / "state.json").write_text("{ broken", encoding="utf-8")
    assert _client(tmp_path).get("/api/runs/R1").status_code == 422


def test_artifact_endpoint_and_traversal(tmp_path):
    _write_run(tmp_path, "R1", _state())
    (tmp_path / "R1" / "final.md").write_text("the final", encoding="utf-8")
    c = _client(tmp_path)
    assert c.get("/api/runs/R1/artifacts/final.md").text == "the final"
    assert c.get("/api/runs/R1/artifacts/..%2F..%2Fetc%2Fpasswd").status_code == 400
