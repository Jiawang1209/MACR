import threading

from macr.web.session import RunActive, RunManager, RunSession
import pytest


def test_emit_buffers_events_and_tracks_status():
    s = RunSession(run_id="R1", command="collab")
    assert s.status == "running"
    s.emit({"type": "note", "text": "hi"})
    s.emit({"type": "status", "status": "awaiting_gate"})
    assert [e["type"] for e in s.events] == ["note", "status"]
    assert s.status == "awaiting_gate"


def test_subscribe_returns_snapshot_and_streams_new_events():
    s = RunSession(run_id="R1", command="collab")
    s.emit({"type": "note", "text": "before"})
    received = []
    snapshot = s.subscribe(received.append)
    assert [e["text"] for e in snapshot] == ["before"]
    s.emit({"type": "note", "text": "after"})
    assert received == [{"type": "note", "text": "after"}]
    s.unsubscribe(received.append)  # no-op for a different ref; see next test


def test_unsubscribe_stops_streaming():
    s = RunSession(run_id="R1", command="collab")
    received = []
    push = received.append
    s.subscribe(push)
    s.emit({"type": "note", "text": "a"})
    s.unsubscribe(push)
    s.emit({"type": "note", "text": "b"})
    assert [e["text"] for e in received] == ["a"]


def test_gate_bridge_blocks_until_response():
    s = RunSession(run_id="R1", command="discuss")
    result = {}

    def run_thread():
        fb = s.request_gate("consensus", {"summary": "plan"})
        result["decision"] = fb.decision
        result["feedback"] = fb.feedback

    t = threading.Thread(target=run_thread)
    t.start()
    # wait until the run thread is awaiting the gate
    assert s.wait_for_gate(timeout=2.0)
    assert s.status == "awaiting_gate"
    assert any(e["type"] == "gate_request" and e["gate"] == "consensus" for e in s.events)
    s.respond_gate("approve", "looks good")
    t.join(timeout=2.0)
    assert result == {"decision": "approve", "feedback": "looks good"}
    assert s.status == "running"


def test_manager_launch_starts_session_via_injected_runner():
    started = {}

    def fake_runner(session, **kwargs):
        started["run_id"] = session.run_id
        started["kwargs"] = kwargs

    mgr = RunManager(runner=fake_runner)
    sess = mgr.launch(command="collab", task="do it", repo="/r", test_cmd=["true"], options={})
    assert mgr.active is sess
    assert started["run_id"] == sess.run_id
    assert started["kwargs"]["command"] == "collab"
    assert started["kwargs"]["task"] == "do it"


def test_manager_rejects_second_launch_while_active():
    mgr = RunManager(runner=lambda session, **kw: None)
    mgr.launch(command="collab", task="t", repo="/r", test_cmd=["true"], options={})
    with pytest.raises(RunActive):
        mgr.launch(command="discuss", task="t2", repo="/r", test_cmd=["true"], options={})


def test_manager_allows_new_launch_after_active_finishes():
    mgr = RunManager(runner=lambda session, **kw: None)
    s1 = mgr.launch(command="collab", task="t", repo="/r", test_cmd=["true"], options={})
    s1.emit({"type": "status", "status": "done"})
    s2 = mgr.launch(command="collab", task="t2", repo="/r", test_cmd=["true"], options={})
    assert mgr.active is s2 and s2 is not s1
