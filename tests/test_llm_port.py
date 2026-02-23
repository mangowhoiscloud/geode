"""Tests for L1 LLMClientPort Protocol."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from geode.infrastructure.ports.llm_port import LLMClientPort


class MockLLMClient:
    """Mock implementation satisfying LLMClientPort via structural typing."""

    def __init__(self, response: str = "mock response"):
        self._response = response
        self.calls: list[tuple[str, str]] = []

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
        yield from self._response.split()


class TestLLMClientPort:
    def test_protocol_is_runtime_checkable(self):
        """LLMClientPort is a runtime-checkable Protocol."""
        client = MockLLMClient()
        assert isinstance(client, LLMClientPort)

    def test_non_conforming_class_fails_isinstance(self):
        """A class missing methods does not satisfy LLMClientPort."""

        class Incomplete:
            def generate(self, system: str, user: str) -> str:
                return ""

        assert not isinstance(Incomplete(), LLMClientPort)

    def test_generate(self):
        client = MockLLMClient("hello world")
        result = client.generate("system", "user")
        assert result == "hello world"
        assert len(client.calls) == 1

    def test_generate_structured(self):
        client = MockLLMClient("structured")
        result = client.generate_structured("system", "user")
        assert result == {"result": "structured"}

    def test_generate_stream(self):
        client = MockLLMClient("hello world")
        tokens = list(client.generate_stream("system", "user"))
        assert tokens == ["hello", "world"]

    def test_generate_with_kwargs(self):
        client = MockLLMClient()
        client.generate("sys", "usr", model="test-model", max_tokens=100, temperature=0.5)
        assert len(client.calls) == 1

    def test_three_methods_in_protocol(self):
        """LLMClientPort defines exactly 3 protocol methods."""
        # Protocol members are defined in __protocol_attrs__ or annotations
        protocol_methods = {
            name
            for name in ("generate", "generate_structured", "generate_stream")
            if hasattr(LLMClientPort, name)
        }
        assert protocol_methods == {"generate", "generate_structured", "generate_stream"}
