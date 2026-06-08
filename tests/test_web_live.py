import subprocess
import threading
from pathlib import Path

from macr.agents.base import FakeAgentBackend
from macr.web.live import WebView
from macr.web.session import RunSession


def _events_of_type(session, t):
    return [e for e in session.events if e["type"] == t]


def test_webview_plan_emits_stage_event():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.plan("claude", {"summary": "the plan", "steps": ["a", "b"]})
    stages = _events_of_type(s, "stage")
    assert len(stages) == 1
    st = stages[0]["stage"]
    assert st["kind"] == "plan" and st["agent"] == "claude"
    assert st["body"]["summary"] == "the plan" and st["body"]["steps"] == ["a", "b"]


def test_webview_consensus_and_evaluation_and_note():
    s = RunSession(run_id="R1", command="discuss")
    v = WebView(s)
    v.consensus({"summary": "agreed", "steps": ["x"], "rationale": "r"})
    v.evaluation(0, "PASS")
    v.note("hello")
    kinds = [e["stage"]["kind"] for e in _events_of_type(s, "stage")]
    assert "consensus" in kinds and "evaluator" in kinds
    assert _events_of_type(s, "note")[0]["text"] == "hello"


def test_webview_printer_emits_note():
    s = RunSession(run_id="R1", command="collab")
    v = WebView(s)
    v.printer("[tests #1] passed=True")
    assert _events_of_type(s, "note")[0]["text"] == "[tests #1] passed=True"


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=path, check=True)


def test_start_run_collab_end_to_end_with_fakes(tmp_path):
    from macr.web.live import start_run

    repo = tmp_path / "repo"
    _init_repo(repo)

    def _editor(role, state):
        if role.name == "executor" and state.worktree_path:
            (Path(state.worktree_path) / "a.txt").write_text("edited\n")

    claude = FakeAgentBackend({"planner": [{"summary": "p", "steps": ["s"]}],
                               "reviewer": [{"summary": "ok", "findings": [], "decision": "approve"}]})
    codex = FakeAgentBackend({"executor": [{"artifact": "done", "notes": "", "evidence": []}]}, on_run=_editor)

    s = RunSession(run_id="LIVE1", command="collab")
    thread = start_run(
        s, command="collab", task="do it", repo=str(repo), test_cmd=["true"],
        options={"runs_dir": tmp_path / "runs", "worktrees_dir": tmp_path / "wts",
                 "claude_backend": claude, "codex_backend": codex},
    )
    # collab has one final gate — wait for it, then approve
    assert s.wait_for_gate(timeout=5.0)
    assert any(e["type"] == "gate_request" and e["gate"] == "final" for e in s.events)
    s.respond_gate("approve", "")
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert s.status == "done"
    done = [e for e in s.events if e["type"] == "done"]
    assert done and done[0]["decision"] == "approve" and done[0]["run_id"] == "LIVE1"
    assert (tmp_path / "runs" / "LIVE1" / "state.json").exists()
