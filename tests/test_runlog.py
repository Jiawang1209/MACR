import json

from macr.runlog import RunLog
from macr.schemas import SharedState


def test_runlog_writes_all_files(tmp_path):
    run_path = tmp_path / "R20260606_001"
    log = RunLog(run_path)
    log.write_input("build a thing")
    log.write_planner({"summary": "plan", "steps": ["a"]})
    log.write_executor({"artifact": "code v1", "notes": "", "evidence": []}, attempt=1)
    log.write_reviewer({"summary": "lgtm", "findings": [], "decision": "approve"})
    log.write_evaluator({"decision": "PASS", "reasons": ["ok"], "confidence": 0.9})
    log.write_final("final text")
    state = SharedState(run_id="R20260606_001", user_query="build a thing")
    log.write_state(state)

    assert (run_path / "input.md").read_text().strip() == "build a thing"
    assert "plan" in (run_path / "planner.output.md").read_text()
    assert "code v1" in (run_path / "executor.output.md").read_text()
    assert (run_path / "reviewer.output.md").exists()
    ev = json.loads((run_path / "evaluator.output.json").read_text())
    assert ev["decision"] == "PASS"
    assert (run_path / "final.md").read_text() == "final text"
    st = json.loads((run_path / "state.json").read_text())
    assert st["run_id"] == "R20260606_001"


def test_runlog_executor_revision_keeps_history(tmp_path):
    run_path = tmp_path / "R1"
    log = RunLog(run_path)
    log.write_executor({"artifact": "v1", "notes": "", "evidence": []}, attempt=1)
    log.write_executor({"artifact": "v2", "notes": "", "evidence": []}, attempt=2)
    # latest always at executor.output.md; history preserved per attempt
    assert "v2" in (run_path / "executor.output.md").read_text()
    assert "v1" in (run_path / "executor.output.v1.md").read_text()
    assert "v2" in (run_path / "executor.output.v2.md").read_text()
