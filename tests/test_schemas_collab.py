from macr.schemas import SharedState, TestResult


def test_test_result_defaults():
    tr = TestResult(command="pytest -q", passed=True, exit_code=0)
    assert tr.log == "" and tr.timed_out is False


def test_shared_state_collab_fields_default():
    s = SharedState(run_id="R1", user_query="q")
    assert s.target_repo is None
    assert s.worktree_path is None
    assert s.diffs == []
    assert s.test_results == []


def test_shared_state_collab_fields_roundtrip():
    s = SharedState(run_id="R1", user_query="q", target_repo="/repo")
    s.diffs.append("diff text")
    s.test_results.append({"passed": False})
    dumped = s.model_dump()
    assert dumped["target_repo"] == "/repo"
    assert dumped["diffs"] == ["diff text"]
    assert dumped["test_results"][0]["passed"] is False
