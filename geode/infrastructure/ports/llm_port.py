"""LLMClientPort — Protocol interface for LLM provider adapters.

Layer 1 infrastructure port that defines the contract for all LLM integrations.
Uses Protocol (structural typing) for consistency with memory ports.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClientPort(Protocol):
    """Protocol for LLM client adapters.

    Implementations: ClaudeAdapter, OpenAIAdapter, MockAdapter.

    The three core methods cover all LLM interaction patterns:
    - generate: free-form text generation
    - generate_structured: JSON-parsed structured output
    - generate_stream: streaming text generation
    """

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """Generate a text response."""
        ...

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Generate a JSON-structured response."""
        ...

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]:
        """Generate a streaming text response."""
        ...
