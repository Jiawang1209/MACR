import json

from macr.web.models import Artifact, RunDetail, RunSummary, Stage


def test_run_summary_defaults():
    s = RunSummary(run_id="R1", command_type="collab", task="do it")
    assert s.decision is None and s.broken is False


def test_run_detail_round_trips_json():
    detail = RunDetail(
        run_id="R1", command_type="collab", task="do it",
        repo="/tmp/r", worktree="/tmp/wt", decision="approve",
        stages=[Stage(kind="plan", label="Planner", agent="claude",
                      body={"summary": "s", "steps": ["a"]})],
        artifacts=[Artifact(name="diff.v1.patch", kind="diff")],
    )
    raw = json.loads(detail.model_dump_json())
    assert raw["stages"][0]["kind"] == "plan"
    assert raw["stages"][0]["status"] is None
    assert raw["artifacts"][0]["kind"] == "diff"
