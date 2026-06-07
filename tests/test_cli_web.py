from macr import cli


def test_web_command_builds_app_without_serving(tmp_path, monkeypatch):
    """`macr web` parses args and hands a FastAPI app to the injected serve fn (no real server)."""
    served = {}

    def fake_serve(app, *, host, port):
        served["host"], served["port"] = host, port
        served["has_routes"] = any(r.path == "/api/runs" for r in app.routes)
        return 0

    rc = cli.main(
        ["web", "--runs-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "9123"],
        serve=fake_serve,
    )
    assert rc == 0
    assert served["host"] == "127.0.0.1" and served["port"] == 9123
    assert served["has_routes"] is True


def test_web_command_help_lists_flags(capsys):
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["web", "--help"])
    out = capsys.readouterr().out
    assert "--runs-dir" in out and "--port" in out
