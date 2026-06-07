import json
import subprocess
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.collab_orchestrator import run_collab
from macr.schemas import HumanFeedback, SubagentRecord


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def _editor(role, state):
    if role.name == "executor" and state.worktree_path:
        (Path(state.worktree_path) / "a.txt").write_text("changed\n")


def test_subagents_captured_and_aggregated(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    claude = FakeAgentBackend(
        {"planner": [{"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []}],
         "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]},
        subagents={"planner": [SubagentRecord(source="claude", agent_type="Explore", ref="r1")]},
    )
    codex = FakeAgentBackend(
        {"executor": [{"artifact": "x", "notes": "", "evidence": []}]},
        on_run=_editor,
        subagents={"executor": [SubagentRecord(source="codex", agent_type="unknown", ref="t1")]},
    )
    state = run_collab(
        "task", repo=repo, test_cmd=["true"],
        claude_backend=claude, codex_backend=codex,
        runs_dir=tmp_path / "runs", worktrees_dir=tmp_path / "wts",
        max_revisions=2, human_gate=lambda s, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
        printer=lambda *_: None, today="20260607",
    )
    run_path = tmp_path / "runs" / "R20260607_001"
    assert (run_path / "subagents" / "planner.v1.subagents.json").exists()
    assert (run_path / "subagents" / "executor.v1.subagents.json").exists()
    by_role = {s["role"]: s for s in state.subagents}
    assert by_role["planner"]["count"] == 1 and by_role["planner"]["types"] == ["Explore"]
    assert by_role["executor"]["count"] == 1
    assert "subagent" in (run_path / "final.md").read_text().lower()
    saved = json.loads((run_path / "state.json").read_text())
    assert any(s["role"] == "planner" for s in saved["subagents"])
