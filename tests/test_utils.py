from macr.utils import now_iso, next_run_id


def test_now_iso_is_iso8601_z():
    s = now_iso()
    assert s.endswith("Z")
    assert "T" in s


def test_next_run_id_first_is_001(tmp_path):
    assert next_run_id(tmp_path, today="20260606") == "R20260606_001"


def test_next_run_id_increments(tmp_path):
    (tmp_path / "R20260606_001").mkdir()
    (tmp_path / "R20260606_002").mkdir()
    assert next_run_id(tmp_path, today="20260606") == "R20260606_003"


def test_next_run_id_ignores_other_days(tmp_path):
    (tmp_path / "R20260101_009").mkdir()
    assert next_run_id(tmp_path, today="20260606") == "R20260606_001"
