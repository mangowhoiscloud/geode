"""Paperclip-style LLM port protocols + :class:`ClaudeAdapter` wrapper.

PR-MAINPATH-67 (2026-05-24) — surviving half of the deleted ``_legacy``
module. The legacy ``AgenticLLMPort`` / ``resolve_agentic_adapter`` /
``_ADAPTER_MAP`` symbols were deleted alongside the agentic-loop fallback
branch; the symbols here remain in active use:

- :class:`LLMClientPort` — Protocol consumed by ``core/runtime.py``,
  ``core/wiring/container.py``, ``core/verification/cross_llm.py``.
- :class:`LLMJsonCallable` / :class:`LLMTextCallable` /
  :class:`LLMParsedCallable` — node-level DI Protocols consumed by
  ``core/llm/router/_di.py``.
- :class:`ClaudeAdapter` — thin wrapper that adapts the Protocol surface
  to the router functions, consumed by ``core/wiring/container.py`` as
  the default ``LLMClientPort`` implementation.

This is **not** the Layer 4 ``LLMAdapter`` Protocol (``base.py``) used
for agentic loop dispatch; the two contracts are independent and stay
side-by-side until the paperclip surface is also migrated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    # Pydantic is a heavy import (~100 ms cumulative). Push it behind
    # ``TYPE_CHECKING`` so module load no longer pulls the full pydantic
    # graph into the cold-start path; ``TypeVar`` ``bound=`` accepts a
    # forward-reference string at runtime so the annotation still type-
    # checks under mypy.
    from pydantic import BaseModel

# ---------------------------------------------------------------------------
# LLMClientPort — Protocol interface for LLM provider adapters
# ---------------------------------------------------------------------------

T2 = TypeVar("T2", bound="BaseModel")


@runtime_checkable
class LLMClientPort(Protocol):
    """Protocol for LLM client adapters.

    Implementations: ClaudeAdapter (router functions), OpenAIAdapter, MockAdapter.
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
    ) -> str: ...

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T2],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T2: ...

    def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]: ...

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any: ...


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
        output_model: type[T2],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> T2: ...


# ---------------------------------------------------------------------------
# ClaudeAdapter — thin wrapper that delegates to router functions
# ---------------------------------------------------------------------------

T = TypeVar("T", bound="BaseModel")


class ClaudeAdapter:
    """Anthropic Claude adapter implementing :class:`LLMClientPort`.

    Wraps the router functions into the port interface.
    Uses lazy imports from :mod:`core.llm.router` to avoid circular imports.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        from core.config import settings

        return settings.model

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        from core.llm.router import call_llm

        result: str = call_llm(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
        return result

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        from core.llm.router import call_llm_json

        result: dict[str, Any] = call_llm_json(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
        return result

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
        from core.llm.router import call_llm_parsed

        return call_llm_parsed(
            system,
            user,
            output_model=output_model,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        from core.llm.router import call_llm_streaming_async

        async for token in call_llm_streaming_async(
            system,
            user,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield token

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        """Async boundary for provider tool-use calls."""
        from core.llm.router import call_llm_with_tools_async

        result = await call_llm_with_tools_async(
            system,
            user,
            tools=tools,
            tool_executor=tool_executor,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
        )
        return result


__all__ = [
    "ClaudeAdapter",
    "LLMClientPort",
    "LLMJsonCallable",
    "LLMParsedCallable",
    "LLMTextCallable",
]
