import pytest

from macr import cli
from macr.llm import FakeLLM
from macr.schemas import HumanFeedback


def test_cli_version_flag(capsys):
    """`macr --version` prints the package version and exits 0."""
    from macr import __version__

    with pytest.raises(SystemExit) as ei:
        cli.main(["--version"])
    assert ei.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_discuss_help_has_flag_descriptions(capsys):
    """discuss --help documents --repo/--test-cmd (parity with collab, which already does)."""
    with pytest.raises(SystemExit):
        cli.main(["discuss", "--help"])
    out = capsys.readouterr().out
    # --repo / --test-cmd must carry a human description, not appear bare.
    assert "git" in out  # --repo help mentions the git repo
    assert "test command" in out or "测试" in out  # --test-cmd help


def test_run_help_has_flag_descriptions(capsys):
    """run --help documents --max-revisions/--model (no longer bare)."""
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    out = capsys.readouterr().out
    assert "revision" in out or "修订" in out  # --max-revisions help
    assert "model" in out or "模型" in out  # --model help


def test_run_blank_task_errors(tmp_path, monkeypatch, capsys):
    """A blank task is rejected with a clear error before any agent runs."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", "   "], llm=_scripted_llm())
    assert rc == 2
    assert "task" in capsys.readouterr().err.lower()


def test_run_negative_max_revisions_errors(tmp_path, monkeypatch, capsys):
    """Negative --max-revisions is rejected with a clear error."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", "task", "--max-revisions=-1"], llm=_scripted_llm())
    assert rc == 2
    assert "max-revisions" in capsys.readouterr().err


def _scripted_llm():
    return FakeLLM([
        {"summary": "p", "steps": ["s"], "tools_needed": [], "risks": []},
        {"artifact": "done", "notes": "", "evidence": []},
        {"summary": "ok", "findings": [], "decision": "approve"},
        {"decision": "PASS", "reasons": ["good"], "confidence": 0.9},
    ])


def test_cli_run_approve_returns_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "build a thing", "--max-revisions", "2"],
        llm=_scripted_llm(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    assert (tmp_path / ".macr" / "runs").exists()


def test_cli_run_reject_returns_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "task"],
        llm=_scripted_llm(),
        human_gate=lambda state, **kw: HumanFeedback(decision="reject", feedback="no", timestamp="t"),
    )
    assert rc == 1


def test_cli_missing_api_key_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No injected llm -> cli must build AnthropicLLM, which needs a key
    rc = cli.main(["run", "task"])
    assert rc == 2


def test_run_prints_artifact_path(tmp_path, monkeypatch, capsys):
    """At the end of a run, the .macr/runs/<id> artifact dir is printed so the user can find it."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "build a thing"],
        llm=_scripted_llm(),
        human_gate=lambda state, **kw: HumanFeedback(decision="approve", feedback="", timestamp="t"),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "artifacts" in out
    assert ".macr/runs" in out


def test_run_yes_auto_approves_without_stdin(tmp_path, monkeypatch):
    """--yes makes the human gate auto-approve; no stdin read; zero exit."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(
        ["run", "build a thing", "--yes"],
        llm=_scripted_llm(),
        # NOTE: do NOT inject human_gate — let --yes wire auto_approve_gate
    )
    assert rc == 0


def test_run_non_tty_without_yes_errors_clearly(tmp_path, monkeypatch, capsys):
    """Non-TTY + interactive gate + no --yes → exit 2 with a --yes hint (not raw EOFError)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(
        ["run", "task"],
        llm=_scripted_llm(),
        # gate NOT injected → resolves to interactive run gate → guard fires
    )
    assert rc == 2
    assert "--yes" in capsys.readouterr().err
