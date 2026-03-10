"""LLMClientPort — Protocol interface for LLM provider adapters.

Layer 1 infrastructure port that defines the contract for all LLM integrations.
Uses Protocol (structural typing) for consistency with memory ports.

Also provides lightweight callable protocols (LLMJsonCallable / LLMTextCallable)
and thread-safe injection via ``contextvars`` so that node modules never import
concrete LLM clients directly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClientPort(Protocol):
    """Protocol for LLM client adapters.

    Implementations: ClaudeAdapter, OpenAIAdapter, MockAdapter.

    The three core methods cover all LLM interaction patterns:
    - generate: free-form text generation
    - generate_structured: JSON-parsed structured output
    - generate_stream: streaming text generation
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        ...

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
        """Generate a structured response validated against a Pydantic model."""
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
        """Generate with tool-use loop. Returns ToolUseResult."""
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


class LLMParsedCallable(Protocol):
    """Callable that returns a Pydantic model instance from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> T: ...


# ---------------------------------------------------------------------------
# Tool-use callable protocol
# ---------------------------------------------------------------------------


class LLMToolCallable(Protocol):
    """Callable that runs a tool-use loop with an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        max_tool_rounds: int = ...,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Thread-safe injection via contextvars
# ---------------------------------------------------------------------------

_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar("llm_json", default=None)
_llm_text_ctx: ContextVar[LLMTextCallable | None] = ContextVar("llm_text", default=None)
_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar("llm_parsed", default=None)
_llm_tool_ctx: ContextVar[LLMToolCallable | None] = ContextVar("llm_tool", default=None)

# Secondary LLM contextvars for ensemble/cross-LLM mode
_secondary_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar(
    "secondary_llm_json", default=None
)
_secondary_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar(
    "secondary_llm_parsed", default=None
)


def set_llm_callable(
    json_fn: LLMJsonCallable,
    text_fn: LLMTextCallable,
    parsed_fn: LLMParsedCallable | None = None,
    tool_fn: LLMToolCallable | None = None,
    secondary_json_fn: LLMJsonCallable | None = None,
    secondary_parsed_fn: LLMParsedCallable | None = None,
) -> None:
    """Inject LLM callables (typically called by GeodeRuntime.create())."""
    _llm_json_ctx.set(json_fn)
    _llm_text_ctx.set(text_fn)
    if parsed_fn is not None:
        _llm_parsed_ctx.set(parsed_fn)
    if tool_fn is not None:
        _llm_tool_ctx.set(tool_fn)
    # Always update secondary contextvars (set to None to clear if not provided)
    _secondary_llm_json_ctx.set(secondary_json_fn)
    _secondary_llm_parsed_ctx.set(secondary_parsed_fn)


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


def get_llm_parsed() -> LLMParsedCallable:
    """Return the injected parsed callable. Raises if not injected."""
    fn = _llm_parsed_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM parsed callable not injected. "
            "Call set_llm_callable(parsed_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_tool() -> LLMToolCallable:
    """Return the injected tool-use callable. Raises if not injected."""
    fn = _llm_tool_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM tool callable not injected. "
            "Call set_llm_callable(tool_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_secondary_llm_json() -> LLMJsonCallable | None:
    """Return the secondary JSON callable, or None if not configured."""
    return _secondary_llm_json_ctx.get()


def get_secondary_llm_parsed() -> LLMParsedCallable | None:
    """Return the secondary parsed callable, or None if not configured."""
    return _secondary_llm_parsed_ctx.get()
