import json

from macr.runlog import RunLog


def test_write_diff_and_test(tmp_path):
    log = RunLog(tmp_path / "R1")
    log.write_diff("THE DIFF", attempt=1)
    log.write_test({"command": "t", "passed": False, "exit_code": 1}, "log output", attempt=1)
    assert "THE DIFF" in (tmp_path / "R1" / "diff.v1.patch").read_text()
    assert "log output" in (tmp_path / "R1" / "test.v1.log").read_text()
    data = json.loads((tmp_path / "R1" / "test.v1.json").read_text())
    assert data["passed"] is False
