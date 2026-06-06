import pytest

from macr.llm import FakeLLM, LLMError, extract_tool_input


def test_fakellm_pops_in_order():
    llm = FakeLLM([{"a": 1}, {"b": 2}])
    assert llm.call_role(system="s", user="u", tool_name="t", tool_schema={}) == {"a": 1}
    assert llm.call_role(system="s", user="u", tool_name="t", tool_schema={}) == {"b": 2}


def test_fakellm_records_calls():
    llm = FakeLLM([{"a": 1}])
    llm.call_role(system="sys", user="usr", tool_name="submit_plan", tool_schema={})
    assert llm.calls[0]["tool_name"] == "submit_plan"
    assert llm.calls[0]["user"] == "usr"


def test_fakellm_exhausted_raises():
    llm = FakeLLM([])
    with pytest.raises(LLMError):
        llm.call_role(system="s", user="u", tool_name="t", tool_schema={})


class _Block:
    def __init__(self, type_, name=None, input_=None):
        self.type = type_
        self.name = name
        self.input = input_


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


def test_extract_tool_input_finds_matching_tool():
    resp = _Resp([_Block("text"), _Block("tool_use", name="submit_plan", input_={"summary": "x"})])
    assert extract_tool_input(resp, "submit_plan") == {"summary": "x"}


def test_extract_tool_input_missing_raises():
    resp = _Resp([_Block("text")])
    with pytest.raises(LLMError):
        extract_tool_input(resp, "submit_plan")
