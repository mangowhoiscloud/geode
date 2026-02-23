"""LLMClientPort — Protocol interface for LLM provider adapters.

Layer 1 infrastructure port that defines the contract for all LLM integrations.
Uses Protocol (structural typing) for consistency with memory ports.

Also provides lightweight callable protocols (LLMJsonCallable / LLMTextCallable)
and thread-safe injection via ``contextvars`` so that node modules never import
concrete LLM clients directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextvars import ContextVar
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


# ---------------------------------------------------------------------------
# Lightweight callable protocols for node-level DI
# ---------------------------------------------------------------------------


class LLMJsonCallable(Protocol):
    """Callable that returns parsed JSON from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> dict[str, Any]: ...


class LLMTextCallable(Protocol):
    """Callable that returns raw text from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Thread-safe injection via contextvars
# ---------------------------------------------------------------------------

_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar("llm_json", default=None)
_llm_text_ctx: ContextVar[LLMTextCallable | None] = ContextVar("llm_text", default=None)


def set_llm_callable(
    json_fn: LLMJsonCallable,
    text_fn: LLMTextCallable,
) -> None:
    """Inject LLM callables (typically called by GeodeRuntime.create())."""
    _llm_json_ctx.set(json_fn)
    _llm_text_ctx.set(text_fn)


def get_llm_json() -> LLMJsonCallable:
    """Return the injected JSON callable. Raises if not injected."""
    fn = _llm_json_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM JSON callable not injected. "
            "Call set_llm_callable() first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_text() -> LLMTextCallable:
    """Return the injected text callable. Raises if not injected."""
    fn = _llm_text_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM text callable not injected. "
            "Call set_llm_callable() first (done by GeodeRuntime.create())."
        )
    return fn
