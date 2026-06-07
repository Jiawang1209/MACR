from macr.testrunner import run_tests


def test_passing_command(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import sys; sys.exit(0)"], timeout=30)
    assert tr.passed is True and tr.exit_code == 0 and tr.timed_out is False


def test_failing_command(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import sys; sys.exit(1)"], timeout=30)
    assert tr.passed is False and tr.exit_code == 1


def test_command_not_found(tmp_path):
    tr = run_tests(tmp_path, ["definitely-not-a-real-cmd-xyz"], timeout=30)
    assert tr.passed is False and tr.exit_code == 127


def test_captures_output(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "print('hello-out')"], timeout=30)
    assert "hello-out" in tr.log


def test_timeout(tmp_path):
    tr = run_tests(tmp_path, ["python", "-c", "import time; time.sleep(5)"], timeout=1)
    assert tr.passed is False and tr.timed_out is True
