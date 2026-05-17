"""Tests for L1 LLMClientPort Protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from core.llm.router import LLMClientPort
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class MockLLMClient:
    """Mock implementation satisfying LLMClientPort via structural typing."""

    def __init__(self, response: str = "mock response"):
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
        self.calls.append((system, user))
        return {"result": self._response}

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

    async def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        self.calls.append((system, user))
        for token in self._response.split():
            yield token

    async def agenerate_with_tools(
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
    def test_protocol_is_runtime_checkable(self) -> None:
        """LLMClientPort is a runtime-checkable Protocol."""
        client = MockLLMClient()
        assert isinstance(client, LLMClientPort)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class missing methods does not satisfy LLMClientPort."""

        class Incomplete:
            def generate(self, system: str, user: str) -> str:
                return ""

        assert not isinstance(Incomplete(), LLMClientPort)

    def test_generate(self) -> None:
        client = MockLLMClient("hello world")
        result = client.generate("system", "user")
        assert result == "hello world"
        assert len(client.calls) == 1

    def test_generate_structured(self) -> None:
        client = MockLLMClient("structured")
        result = client.generate_structured("system", "user")
        assert result == {"result": "structured"}

    def test_agenerate_stream(self) -> None:
        client = MockLLMClient("hello world")
        async def _collect() -> list[str]:
            return [token async for token in client.agenerate_stream("system", "user")]

        tokens = asyncio.run(_collect())
        assert tokens == ["hello", "world"]

    def test_generate_with_kwargs(self) -> None:
        client = MockLLMClient()
        client.generate("sys", "usr", model="test-model", max_tokens=100, temperature=0.5)
        assert len(client.calls) == 1

    def test_core_methods_in_protocol(self) -> None:
        """LLMClientPort defines the core async-only stream method."""
        # Protocol members are defined in __protocol_attrs__ or annotations
        protocol_methods = {
            name
            for name in ("generate", "generate_structured", "agenerate_stream")
            if hasattr(LLMClientPort, name)
        }
        assert protocol_methods == {"generate", "generate_structured", "agenerate_stream"}
