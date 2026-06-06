from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Raised when the model call fails or returns no usable tool output."""


@runtime_checkable
class LLM(Protocol):
    def call_role(
        self, *, system: str, user: str, tool_name: str, tool_schema: dict
    ) -> dict:
        """Return the raw tool-input dict the model produced for `tool_name`."""
        ...


def extract_tool_input(response: Any, tool_name: str) -> dict:
    """Pull the input of the first `tool_use` block matching tool_name."""
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input)
    raise LLMError(f"model did not call tool '{tool_name}'")


class FakeLLM:
    """Test double: returns scripted dicts in order; records calls."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def call_role(self, *, system: str, user: str, tool_name: str, tool_schema: dict) -> dict:
        self.calls.append(
            {"system": system, "user": user, "tool_name": tool_name, "tool_schema": tool_schema}
        )
        if not self._responses:
            raise LLMError("FakeLLM exhausted")
        return self._responses.pop(0)


class AnthropicLLM:
    """Real implementation using the Anthropic SDK with forced tool-use."""

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 4096, client: Any = None):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            import anthropic  # imported lazily so tests never need the network

            client = anthropic.Anthropic()
        self._client = client

    def call_role(self, *, system: str, user: str, tool_name: str, tool_schema: dict) -> dict:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[{"name": tool_name, "description": f"Submit the {tool_name} result.", "input_schema": tool_schema}],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # surface SDK/network errors as LLMError
            raise LLMError(f"Anthropic call failed: {exc}") from exc
        return extract_tool_input(response, tool_name)
