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


def test_spa_index_served_when_dist_present(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    app = create_app(runs_dir=tmp_path, spa_dist=dist)
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "spa" in r.text


def test_no_spa_mount_when_dist_absent(tmp_path):
    # create_app must not crash when no built SPA is present
    app = create_app(runs_dir=tmp_path, spa_dist=tmp_path / "missing")
    assert TestClient(app).get("/api/runs").status_code == 200


from macr.web.session import RunManager


def test_launch_starts_run_and_active_reports_it(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: session.emit({"type": "note", "text": "started"}))
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    repo = tmp_path / "repo"; repo.mkdir()
    r = c.post("/api/runs/launch", json={"command": "collab", "task": "do it",
                                         "repo": str(repo), "test_cmd": "true"})
    assert r.status_code == 200 and r.json()["run_id"]
    active = c.get("/api/runs/active")
    assert active.status_code == 200 and active.json()["command"] == "collab"


def test_launch_rejects_concurrent_with_409(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: None)
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    repo = tmp_path / "repo"; repo.mkdir()
    body = {"command": "collab", "task": "t", "repo": str(repo), "test_cmd": "true"}
    assert c.post("/api/runs/launch", json=body).status_code == 200
    assert c.post("/api/runs/launch", json=body).status_code == 409


def test_launch_validates_inputs_with_400(tmp_path):
    mgr = RunManager(runner=lambda session, **kw: None)
    app = create_app(runs_dir=tmp_path, manager=mgr)
    c = TestClient(app)
    r = c.post("/api/runs/launch", json={"command": "collab", "task": "t",
                                         "repo": str(tmp_path / "nope"), "test_cmd": "true"})
    assert r.status_code == 400
    repo = tmp_path / "repo"; repo.mkdir()
    r2 = c.post("/api/runs/launch", json={"command": "collab", "task": "  ",
                                          "repo": str(repo), "test_cmd": "true"})
    assert r2.status_code == 400


def test_active_returns_204_when_idle(tmp_path):
    app = create_app(runs_dir=tmp_path, manager=RunManager(runner=lambda s, **k: None))
    assert TestClient(app).get("/api/runs/active").status_code == 204
