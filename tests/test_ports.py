"""Tests for Clean Architecture ports and adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from core.infrastructure.ports.llm_port import LLMClientPort
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class MockLLM:
    """Mock LLM adapter implementing LLMClientPort protocol."""

    def __init__(self, response: str = '{"key": "value"}'):
        self._response = response
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return "mock-model"

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        self.calls.append((system, user))
        return self._response

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        import json

        self.calls.append((system, user))
        return json.loads(self._response)

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T:
        self.calls.append((system, user))
        return output_model.model_validate({"result": self._response})

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]:
        self.calls.append((system, user))
        yield self._response

    def generate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        self.calls.append((system, user))
        return {"text": self._response, "tool_calls": [], "usage": [], "rounds": 1}


class TestLLMClientPort:
    def test_mock_implements_protocol(self):
        """MockLLM satisfies LLMClientPort protocol (structural typing)."""
        mock: LLMClientPort = MockLLM()
        result = mock.generate("system", "user")
        assert isinstance(result, str)

    def test_mock_json(self):
        mock: LLMClientPort = MockLLM('{"score": 4.2}')
        data = mock.generate_structured("system", "user")
        assert data["score"] == 4.2

    def test_call_tracking(self):
        mock = MockLLM()
        mock.generate("sys1", "usr1")
        mock.generate("sys2", "usr2")
        assert len(mock.calls) == 2

    def test_isinstance_check(self):
        """LLMClientPort is runtime_checkable."""
        mock = MockLLM()
        assert isinstance(mock, LLMClientPort)
