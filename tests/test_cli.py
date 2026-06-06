from macr import cli
from macr.llm import FakeLLM
from macr.schemas import HumanFeedback


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
